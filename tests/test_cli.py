import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile
from py2fastrust.aot import rust_mask


class APITests(unittest.TestCase):
    def test_backend_selection_and_source_map(self):
        source = "s=0\nfor i in range(10):\n s += i\nprint(s)\n"
        result = transpile(source)
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "native")
        self.assertTrue(result.source_map)
        self.assertNotIn("enum Value", result.rust_source)
        result = transpile(source, TranspileOptions(optimize=False))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend, "native")
        self.assertNotIn("enum Value", result.rust_source)
        self.assertNotIn("struct Runtime", result.rust_source)
        self.assertIn("// Integer mode: i64; backend: native.",result.rust_source)
        self.assertNotRegex(rust_mask(result.rust_source),r"\bOp\b|\bInstr\b|\.ops\b|\bfn\s+step\b")

    def test_cli_no_optimize_emits_direct_rust_and_reports_native_in_header(self):
        with tempfile.TemporaryDirectory(prefix="pytors-cli-aot-") as directory:
            root=Path(directory)
            source=root/"main.py"
            output=root/"main.rs"
            source.write_text("value=[1,2]\nprint(value)\n")
            result=subprocess.run([sys.executable,"-m","py2fastrust",str(source),
                                   "--no-optimize","-o",str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            rust=output.read_text()
            self.assertIn("// Integer mode: i64; backend: native.",rust)
            self.assertNotRegex(rust_mask(rust),r"\bOp\b|\bInstr\b|\.ops\b|\bfn\s+step\b")
            self.assertNotIn("struct Runtime",rust)

    def test_bad_integer_option_and_syntax_diagnostics(self):
        result = transpile("x=1", TranspileOptions(integer="i32", filename="bad.py"))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code, "E004")
        result = transpile("x = (", TranspileOptions(filename="bad.py"))
        self.assertEqual(result.diagnostics[0].filename, "bad.py")
        self.assertEqual(result.diagnostics[0].line, 1)

    def test_cli_invalid_source_does_not_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.py"
            output = Path(directory) / "main.rs"
            source.write_text("x = (")
            output.write_text("keep")
            result = subprocess.run([sys.executable, "-m", "py2fastrust", str(source), "-o", str(output)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("bad.py:1:", result.stderr)
            self.assertEqual(output.read_text(), "keep")

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_cli_and_bundled_packages(self):
        with tempfile.TemporaryDirectory(prefix="py2fastrust-modules-") as directory:
            root = Path(directory)
            package = root / "helpers"
            package.mkdir()
            (package / "__init__.py").write_text("from .calc import twice\n")
            (package / "calc.py").write_text("def twice(x):\n return x*2\n")
            (root / "extra.py").write_text("value=13\n")
            source = root / "main.py"
            source.write_text("from helpers import twice\nprint(twice(4))\nexec('import extra\\nprint(extra.value)')\n")
            output = root / "main.rs"
            generated = subprocess.run([sys.executable, "-m", "py2fastrust", str(source), "-o", str(output),
                                        "--include-module", "extra"], capture_output=True, text=True)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.assertTrue(output.is_file())
            compiled = subprocess.run(["rustc", "--edition=2021", str(output), "-o", str(root / "main")],
                                      capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            # Execute away from all bundled .py files.
            result = subprocess.run([str(root / "main")], cwd="/tmp", capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "8\n13\n")


if __name__ == "__main__":
    unittest.main()
