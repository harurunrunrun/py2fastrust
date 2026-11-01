"""Only a broken built package, not conversion coverage, gates publication."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class CheckWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pytors-initialize-tests-")
        cls.site = Path(cls.temporary.name) / "built"
        build = subprocess.run([
            sys.executable, str(ROOT / "tools/build_web.py"),
            "--preview-source", str(ROOT), "--source-commit", "a" * 40,
            "--output", str(cls.site),
        ], capture_output=True, text=True, timeout=60)
        if build.returncode:
            cls.temporary.cleanup()
            raise AssertionError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pytors-site-check-")
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "site"
        shutil.copytree(self.site, self.output)
        self.manifest = json.loads((self.output / "web-manifest.json").read_text())

    def write_manifest(self):
        (self.output / "web-manifest.json").write_text(json.dumps(self.manifest))

    def check(self):
        return subprocess.run([
            sys.executable, str(ROOT / "tools/check_web.py"), "--site", str(self.output),
        ], capture_output=True, text=True, timeout=30)

    def test_actual_wheel_and_bridge_initialize_in_an_isolated_process(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = json.loads(result.stdout)
        self.assertIn(".whl/py2fastrust/__init__.py", metadata["package_origin"])
        self.assertTrue(metadata["package_origin"].startswith(str(self.output)))
        self.assertGreater(metadata["resource_count"], 20)
        self.assertTrue(all(metadata["smoke_checks"].values()))
        self.assertEqual(metadata["conversions_run"], 0)

    def test_conversion_failure_does_not_fail_package_initialization(self):
        bridge = self.output / "bridge.py"
        bridge.write_text(bridge.read_text() + '''\n
def convert(request_json):
    raise RuntimeError("Conversion deliberately unsupported in this test")
''')
        digest = hashlib.sha256(bridge.read_bytes()).hexdigest()
        self.manifest["bridge"]["sha256"] = digest
        self.manifest["site_files"]["bridge.py"] = digest
        self.write_manifest()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["conversions_run"], 0)

    def test_missing_or_nonboolean_compiler_checks_block_publication(self):
        bridge = self.output / "bridge.py"
        original = bridge.read_text()
        required = {"ast": True, "symtable": True, "compile": True,
                    "sha256": True, "resources": True}
        for checks in ({}, {"ast": True}, {**required, "compile": 1}):
            with self.subTest(checks=checks):
                response = json.dumps({"smoke_checks": checks, "resource_count": 132})
                bridge.write_text(original + "\n\ndef initialize(manifest_json):\n    return "
                                  + repr(response) + "\n")
                digest = hashlib.sha256(bridge.read_bytes()).hexdigest()
                self.manifest["bridge"]["sha256"] = digest
                self.manifest["site_files"]["bridge.py"] = digest
                self.write_manifest()
                result = self.check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("initialization checks did not pass", result.stderr)

    def test_modified_wheel_fails_before_initialization(self):
        wheel = self.output / self.manifest["wheel"]["path"]
        with wheel.open("ab") as stream:
            stream.write(b"changed")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Wheel size or SHA-256 mismatch", result.stderr)

    def test_modified_bridge_is_rejected(self):
        bridge = self.output / "bridge.py"
        bridge.write_text(bridge.read_text() + "\n# changed\n")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_actual_bridge_rejects_a_corrupt_resource_inventory(self):
        self.manifest["resources"][0]["sha256"] = "0" * 64
        self.write_manifest()
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Wheel resource integrity check failed", result.stderr)

    def test_syntax_error_in_a_lazy_package_module_blocks_publication(self):
        wheel = self.output / self.manifest["wheel"]["path"]
        name = "py2fastrust/native_scalar.py"
        with zipfile.ZipFile(wheel) as original:
            entries = [(entry, original.read(entry.filename)) for entry in original.infolist()]
        broken = b"def broken(:\n"
        self.assertIn(name, [entry.filename for entry, _ in entries])
        with zipfile.ZipFile(wheel, "w") as changed:
            for entry, contents in entries:
                changed.writestr(entry, broken if entry.filename == name else contents)
        data = wheel.read_bytes()
        self.manifest["wheel"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.manifest["source_files"][name] = hashlib.sha256(broken).hexdigest()
        self.write_manifest()
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SyntaxError", result.stderr)
        self.assertIn("native_scalar.py", result.stderr)


if __name__ == "__main__":
    unittest.main()
