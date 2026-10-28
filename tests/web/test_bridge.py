"""Native API parity checks; real browser coverage lives in browser.spec.mjs."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, __version__, transpile
from py2fastrust.settings import LICENSES


ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_NATIVE_PROGRAMS=(
    ('class Item:pass\nn=3\nvalues=[[] for i in range(n)]\n',{}),
    ('from collections import deque\nvalues=deque([1])\n',{'integer':'bigint'}),
    ('values=[1]\nalias=values\n',{}),
    ('class Item:pass\nn=3\nvalues=[[] for i in range(n)]\nvalues[0].append(7)\nprint(values)\n',{}),
    ('from collections import deque\nvalues=deque([1])\nvalues.append(2)\nprint(values.popleft(),values)\n',{'integer':'bigint'}),
    ('values=[1]\nalias=values\nalias.append(2)\nprint(values,alias,values is alias)\n',{}),
)
spec = importlib.util.spec_from_file_location("pytors_test_bridge", ROOT / "web" / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def manifest():
    resources = []
    package = ROOT / "py2fastrust"
    for folder in ("runtime", "stdlib", "grammar", "licenses", "unicode", "vendor"):
        for path in sorted((package / folder).rglob("*")):
            if (path.is_file() and not path.name.endswith(".pyc")
                    and not any(part.startswith('.env') or part=='__pycache__' for part in path.relative_to(package).parts)):
                data = path.read_bytes()
                resources.append({"path": path.relative_to(package).as_posix(), "size": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest()})
    return {"resources": resources, "package": {"version": __version__}}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.original_cwd = Path.cwd()
        self.directory = tempfile.TemporaryDirectory(prefix="pytors-bridge-test-")
        bridge.WORK_DIRECTORY = Path(self.directory.name)
        self.metadata = json.loads(bridge.initialize(json.dumps(manifest())))

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.directory.cleanup()

    def convert(self, source, **options):
        return json.loads(bridge.convert(json.dumps({"source": source, "options": options})))

    def assert_api_parity(self, source, **options):
        actual = self.convert(source, **options)
        expected = transpile(source, TranspileOptions(filename="main.py",
                             module_paths=(bridge.WORK_DIRECTORY,), **options))
        self.assertEqual(actual["rust_source"], expected.rust_source)
        self.assertEqual(actual["diagnostics"], [
            {"filename": item.filename, "line": item.line, "column": item.column,
             "message": item.message, "code": item.code} for item in expected.diagnostics
        ])
        return actual

    def test_smoke_checks_and_complete_license_catalog(self):
        self.assertTrue(all(self.metadata["smoke_checks"].values()))
        self.assertEqual(self.metadata["licenses"], list(LICENSES))
        self.assertEqual(len(self.metadata["licenses"]), 21)
        self.assertIn("NONE", self.metadata["licenses"])
        self.assertEqual(self.metadata["integer_modes"], ["i64", "i128", "bigint"])
        self.assertEqual(self.metadata["string_modes"], ["ascii", "unicode"])
        self.assertEqual(self.metadata["defaults"]["string_mode"], "ascii")
        self.assertEqual(self.metadata["resource_count"], len(manifest()["resources"]))

    def test_resource_integrity_is_required_before_conversion(self):
        damaged = manifest()
        damaged["resources"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            bridge.initialize(json.dumps(damaged))
        with self.assertRaisesRegex(RuntimeError, "not initialized"):
            self.convert("print(1)")

    def test_bfs_and_repeated_conversions_match_api(self):
        bfs = (ROOT / "examples" / "bfs.py").read_text(encoding="utf-8")
        for source in ("print(1 + 2)\n", bfs, "print('again')\n", bfs):
            with self.subTest(source=source[:20]):
                self.assert_api_parity(source)
        self.assertEqual(list(bridge.WORK_DIRECTORY.iterdir()), [])

    def test_all_integer_modes_and_optimizer_choices_match_api(self):
        for integer in ("i64", "i128", "bigint"):
            for optimize in (True, False):
                with self.subTest(integer=integer, optimize=optimize):
                    self.assert_api_parity("print(2**70)\n", integer=integer, optimize=optimize)

    def test_string_modes_and_source_override_match_api(self):
        for mode in ("ascii", "unicode"):
            with self.subTest(string_mode=mode):
                self.assert_api_parity('s="hello"\nprint(s[2])\n', string_mode=mode)
        source='# pytors: --string-mode unicode\ns="あいう"\nprint(s[1])\n'
        self.assert_api_parity(source, string_mode="ascii")

    def test_every_license_has_the_full_core_header(self):
        source = '# original license: example\nprint("/* inert */")\n'
        for license in LICENSES:
            with self.subTest(license=license):
                result = self.assert_api_parity(source, license=license)
                rust = result["rust_source"]
                self.assertTrue(rust.startswith("// LICENSE: " + license + "\n"))
                from py2fastrust.settings import license_text
                text = license_text(license)
                for line in text.rstrip().split("\n"):
                    self.assertIn("// " + line + "\n" if line else "//\n", rust)
                self.assertIn("// If the original Python source specifies a license, that license takes precedence.\n", rust)

    def test_no_license_and_source_override_match_api(self):
        for mode in ("i64","i128","bigint"):
            result=self.assert_api_parity('print(3)\n',integer=mode,license="none")
            self.assertTrue(result['rust_source'].startswith('// LICENSE: NONE\n'))
            self.assertNotIn('Creative Commons Legal Code',result['rust_source'])
        source='# pytors: --license none\nprint(3)\n'
        result=self.assert_api_parity(source,license="MIT")
        self.assertTrue(result['rust_source'].startswith('// LICENSE: NONE\n'))

    def test_directives_override_options_with_original_source_intact(self):
        source = '# pytors: --int i128 --license Unlicense --no-optimize\nprint(2**70)\n'
        result = self.assert_api_parity(source, integer="i64", license="MIT", optimize=True)
        self.assertTrue(result["rust_source"].startswith("// LICENSE: Unlicense\n"))
        self.assertIn("// Integer mode: i128.", result["rust_source"])
        self.assertIn("// " + source.split("\n")[0] + "\n", result["rust_source"])

    def test_submitted_source_is_never_executed_or_written(self):
        # This would create a marker if the adapter evaluated submitted Python.
        source = 'open("executed", "w").write("bad")\nraise RuntimeError("must stay inert")\n'
        self.assert_api_parity(source)
        self.assertFalse((bridge.WORK_DIRECTORY / "executed").exists())
        self.assertFalse((bridge.WORK_DIRECTORY / "main.py").exists())

    def test_positioned_diagnostics_and_invalid_options_match_api(self):
        for source in ("if True print(1)\n", "return 2\n", "import missing_user_module\n",
                       "# pytors: --int invalid\nprint(1)\n"):
            with self.subTest(source=source):
                result = self.assert_api_parity(source)
                self.assertIsNone(result["rust_source"])
                self.assertTrue(result["diagnostics"])
                first = result["diagnostics"][0]
                self.assertEqual(first["filename"], "main.py")
                self.assertGreaterEqual(first["line"], 1)
                self.assertGreaterEqual(first["column"], 1)
        self.assert_api_parity("print(1)\n", integer="i32")
        self.assert_api_parity("print(1)\n", license="unknown")
        self.assert_api_parity("print(1)\n", string_mode="unknown")

    def test_missing_native_feature_reasons_and_source_details_survive_transport(self):
        cases=(
            ('def f(*items):return len(items)\nprint(f(1))\n',{},('signature','items','packing')),
            ('s=input()\nprint(s.replace("<img src=x>","x"))\n',{},("call 's.replace'",'receiver=str','<img src=x>')),
        )
        for source,options,tokens in cases:
            with self.subTest(source=source):
                result=self.assert_api_parity(source,**options)
                self.assertIsNone(result['rust_source'])
                diagnostic=result['diagnostics'][0]
                self.assertEqual((diagnostic['filename'],diagnostic['code']),('main.py','E006'))
                self.assertIn('Source:',diagnostic['message'])
                for token in tokens:self.assertIn(token,diagnostic['message'])

    def test_supported_native_programs_preserve_bridge_api_parity(self):
        for source,options in SUPPORTED_NATIVE_PROGRAMS:
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source,integer=mode):
                    result=self.assert_api_parity(source,**{**options,'integer':mode})
                    self.assertIsNotNone(result['rust_source'])
                    self.assertEqual(result['diagnostics'],[])
                    self.assertLess(len(result['rust_source'].encode()),512*1024)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_supported_native_programs_execute_without_python(self):
        with tempfile.TemporaryDirectory(prefix='pytors-bridge-native-')as directory:
            for index,(source,options)in enumerate(SUPPORTED_NATIVE_PROGRAMS):
                expected=subprocess.run([sys.executable,'-I','-S','-c',source],text=True,capture_output=True,timeout=10)
                self.assertEqual(expected.returncode,0,expected.stderr)
                for mode in ('i64','i128','bigint'):
                    result=self.assert_api_parity(source,**{**options,'integer':mode})
                    self.assertEqual(result['diagnostics'],[])
                    path=Path(directory)/f'case{index}_{mode}.rs';path.write_text(result['rust_source'])
                    self.assertNotIn('enum Instruction',result['rust_source'])
                    self.assertNotIn('enum Value {',result['rust_source'])
                    for release in(False,True):
                        with self.subTest(source=source,integer=mode,release=release):
                            binary=path.with_name(path.stem+str(release))
                            built=subprocess.run(['rustc','--crate-name','bridge','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                            self.assertEqual(built.returncode,0,built.stderr)
                            actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,
                                env={**os.environ,'PATH':'/no-python-runtime','PYTHONPATH':'/unavailable'})
                            self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(expected.returncode,expected.stdout,expected.stderr))

    def test_transport_values_are_validated(self):
        for value in ({"source": None}, {"source": "print(1)", "options": []},
                      {"source": "print(1)", "options": {"optimize": "false"}},
                      {"source": "print(1)", "options": {"string_mode": False}},
                      {"source": "print(1)", "options": {"string_mode": None}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.convert(json.dumps(value))


if __name__ == "__main__":
    unittest.main()
