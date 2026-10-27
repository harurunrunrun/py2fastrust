"""Installed package placement never becomes a vendored source filename."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import py2fastrust


DRIVER = '''
from dataclasses import asdict
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from py2fastrust import TranspileOptions,transpile
from py2fastrust.compiler import Compiler
request=json.load(sys.stdin)
options=TranspileOptions(filename="main.py",module_paths=(Path(sys.argv[2]),),
                         integer="i64",license="MIT",optimize=request.get("optimize",False))
result=transpile(request["source"],options)
data={"rust_source":result.rust_source,"backend":result.backend,
      "diagnostics":[asdict(item) for item in result.diagnostics],
      "source_map":[asdict(item) for item in result.source_map]}
if result.success:
    compiler=Compiler("main.py",module_paths=options.module_paths)
    program=compiler.compile(request["source"])
    data.update(code_filenames=[code.filename for code in program.codes],
                layout_files=sorted(compiler.local_layouts),
                future_files=sorted(compiler.future_flags),
                module_files=sorted(compiler.file_modules),
                native_imports=sorted(compiler.native_imports))
json.dump(data,sys.stdout)
'''


class StdlibRelocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-relocation-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.user = cls.root / "user"
        cls.user.mkdir()
        cls.placements = [cls.root / "checkout", cls.root / "relocated-site-packages"]
        package = Path(py2fastrust.__file__).parent
        for placement in cls.placements:
            shutil.copytree(package, placement / "py2fastrust",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*"))

    def convert(self, placement, source, *, module_path=None, optimize=False):
        result = subprocess.run(
            [sys.executable, "-I", "-c", DRIVER, str(placement), str(module_path or self.user)],
            input=json.dumps({"source": source, "optimize": optimize}),
            cwd=self.user, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_relocated_packages_emit_identical_rust_and_source_locations(self):
        cases = [
            ("# pytors: --int i128 --license Unlicense\nimport sys\nprint(2 ** 100)\n", True),
            ("import sys,functools,collections,bisect,heapq\nprint(functools.reduce(lambda a,b:a+b,[1,2]))\n", False),
        ]
        for source, optimize in cases:
            with self.subTest(source=source):
                first, second = [self.convert(path, source, optimize=optimize)
                                 for path in self.placements]
                self.assertFalse(first["diagnostics"], first["diagnostics"])
                self.assertFalse(second["diagnostics"], second["diagnostics"])
                self.assertTrue(first["rust_source"] == second["rust_source"],
                                "Rust output must be byte-identical after a real package relocation")
                self.assertEqual(first, second)
                self.assertIn("<pytors-stdlib>/__future__.py", first["code_filenames"])
                for placement in self.placements:
                    self.assertNotIn(str(placement), first["rust_source"])
                for location in first["source_map"]:
                    self.assertEqual(location["filename"],
                                     first["code_filenames"][location["code"]])
                files = set(first["code_filenames"])
                for key in ("layout_files", "future_files", "module_files"):
                    self.assertEqual(set(first[key]), files)
                if not optimize:
                    for name in ("__future__", "functools", "collections", "bisect", "heapq"):
                        self.assertIn(f"<pytors-stdlib>/{name}.py", files)
                        self.assertIn(name, first["native_imports"])

    def test_user_stdlib_shadow_keeps_real_path_and_is_not_trusted(self):
        # Even this directory spelling must not grant native-import trust.
        modules = self.user / "py2fastrust" / "stdlib"
        modules.mkdir(parents=True)
        shadow = modules / "collections.py"
        shadow.write_text("def deque(values):\n return [99]\n", encoding="utf-8")
        source = "from collections import deque\nq=deque([7])\nprint(q)\n"
        first, second = [self.convert(path, source, module_path=modules, optimize=True)
                         for path in self.placements]
        self.assertEqual(first, second)
        self.assertFalse(first["diagnostics"], first["diagnostics"])
        self.assertEqual(first["backend"], "vm")
        self.assertNotIn("collections", first["native_imports"])
        self.assertIn(str(shadow), first["code_filenames"])
        self.assertTrue(any(item["filename"] == str(shadow) for item in first["source_map"]))

    def test_user_relative_package_imports_keep_real_source_paths(self):
        package = self.user / "helpers"
        package.mkdir()
        init = package / "__init__.py"
        module = package / "util.py"
        init.write_text("from .util import value\n", encoding="utf-8")
        module.write_text("value=41\n", encoding="utf-8")
        first, second = [self.convert(path, "import helpers\nprint(helpers.value)\n")
                         for path in self.placements]
        self.assertEqual(first, second)
        self.assertFalse(first["diagnostics"], first["diagnostics"])
        self.assertIn(str(init), first["code_filenames"])
        self.assertIn(str(module), first["code_filenames"])

    def test_diagnostics_use_logical_vendored_and_real_user_filenames(self):
        for placement in self.placements:
            resource = placement / "py2fastrust" / "stdlib" / "heapq.py"
            original = resource.read_bytes()
            try:
                resource.write_text("value=1\ndef broken(:\n", encoding="utf-8")
                result = self.convert(placement, "import heapq\n")
                diagnostic = result["diagnostics"][0]
                self.assertEqual(diagnostic["filename"], "<pytors-stdlib>/heapq.py")
                self.assertEqual(diagnostic["line"], 2)
                self.assertEqual(diagnostic["code"], "E001")
            finally:
                resource.write_bytes(original)
        broken = self.user / "broken.py"
        broken.write_text("value=1\ndef broken(:\n", encoding="utf-8")
        for placement in self.placements:
            result = self.convert(placement, "import broken\n")
            self.assertEqual(result["diagnostics"][0]["filename"], str(broken))
            self.assertEqual(result["diagnostics"][0]["line"], 2)
            result = self.convert(placement, "def broken(:\n")
            self.assertEqual(result["diagnostics"][0]["filename"], "main.py")

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_standalone_traceback_uses_the_same_logical_vendored_filename(self):
        result = self.convert(self.placements[0],
                              "import functools\nfunctools.update_wrapper(None,None)\n")
        self.assertFalse(result["diagnostics"], result["diagnostics"])
        source = self.root / "traceback.rs"
        source.write_text(result["rust_source"], encoding="utf-8")
        binary = source.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(binary)],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(built.returncode, 0, built.stderr)
        actual = subprocess.run([str(binary)], env={"PATH": "/nonexistent"},
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(actual.returncode, 0)
        self.assertIn('File "<pytors-stdlib>/functools.py"', actual.stderr)
        self.assertIn('File "main.py"', actual.stderr)
        for placement in self.placements:
            self.assertNotIn(str(placement), actual.stderr)


if __name__ == "__main__":
    unittest.main()
