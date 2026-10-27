"""Native API parity checks; real browser coverage lives in browser.spec.mjs."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from py2fastrust import TranspileOptions, __version__, transpile
from py2fastrust.settings import LICENSES


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("pytors_test_bridge", ROOT / "web" / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def manifest():
    resources = []
    package = ROOT / "py2fastrust"
    for folder in ("runtime", "stdlib", "grammar", "licenses", "unicode"):
        for path in sorted((package / folder).iterdir()):
            if path.is_file() and not path.name.endswith(".pyc"):
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
        self.assertEqual(len(self.metadata["licenses"]), 20)
        self.assertEqual(self.metadata["integer_modes"], ["i64", "i128", "bigint"])
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

    def test_every_license_has_the_full_core_header(self):
        source = '# original license: example\nprint("/* inert */")\n'
        for license in LICENSES:
            with self.subTest(license=license):
                result = self.assert_api_parity(source, license=license)
                rust = result["rust_source"]
                self.assertTrue(rust.startswith("// LICENSE: " + license + "\n"))
                text = (ROOT / "py2fastrust" / "licenses" / (license + ".txt")).read_text()
                for line in text.rstrip().split("\n"):
                    self.assertIn("// " + line + "\n" if line else "//\n", rust)
                self.assertIn("// If the original Python source specifies a license, that license takes precedence.\n", rust)

    def test_directives_override_options_with_original_source_intact(self):
        source = '# pytors: --int i128 --license Unlicense --no-optimize\nprint(2**70)\n'
        result = self.assert_api_parity(source, integer="i64", license="MIT", optimize=True)
        self.assertTrue(result["rust_source"].startswith("// LICENSE: Unlicense\n"))
        self.assertIn("// Integer mode: i128; backend: vm.", result["rust_source"])
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

    def test_transport_values_are_validated(self):
        for value in ({"source": None}, {"source": "print(1)", "options": []},
                      {"source": "print(1)", "options": {"optimize": "false"}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.convert(json.dumps(value))


if __name__ == "__main__":
    unittest.main()
