"""Packaging gates: the browser wheel must retain every core resource."""

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("pytors_test_build", ROOT / "tools" / "build_web.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildWebTests(unittest.TestCase):
    def test_real_preview_build_retains_every_package_file_and_marks_provenance(self):
        with tempfile.TemporaryDirectory(prefix="pytors web build ") as directory:
            output = Path(directory) / "site"
            commit = "a" * 40
            completed = subprocess.run([
                sys.executable, str(ROOT / "tools" / "build_web.py"),
                "--preview-source", str(ROOT), "--source-commit", commit,
                "--output", str(output),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            manifest = json.loads((output / "web-manifest.json").read_text())
            self.assertTrue(manifest["preview"])
            self.assertEqual(manifest["source_commit"], commit)
            self.assertEqual(manifest["pyodide"]["version"], "314.0.7")
            self.assertTrue(manifest["wheel"]["path"].startswith("assets/" + commit + "/"))
            wheel_path = output / manifest["wheel"]["path"]
            wheel_data = wheel_path.read_bytes()
            self.assertEqual(hashlib.sha256(wheel_data).hexdigest(), manifest["wheel"]["sha256"])
            self.assertEqual(len(wheel_data), manifest["wheel"]["size"])
            expected = builder.package_files(ROOT)
            resources = builder.verify_wheel(wheel_path, expected)
            self.assertEqual(resources, manifest["resources"])
            self.assertGreater(len(resources), 20)
            for name, data in expected.items():
                self.assertEqual(manifest["source_files"]["py2fastrust/" + name],
                                 hashlib.sha256(data).hexdigest())
            for name in builder.SITE_FILES:
                self.assertEqual((output / name).read_bytes(), (ROOT / "web" / name).read_bytes())
            self.assertTrue((output / ".nojekyll").is_file())

    def test_export_uses_committed_snapshot_with_dirty_files_excluded(self):
        with tempfile.TemporaryDirectory(prefix="pytors git export ") as directory:
            repository = Path(directory) / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
            source_file = repository / "committed.txt"
            source_file.write_text("committed bytes\n")
            subprocess.run(["git", "-C", str(repository), "add", "committed.txt"], check=True)
            subprocess.run([
                "git", "-C", str(repository), "-c", "user.name=Codex",
                "-c", "user.email=codex@openai.com", "-c", "commit.gpgSign=false",
                "commit", "--quiet", "-m", "Test source snapshot",
            ], check=True)
            source_file.write_text("uncommitted replacement\n")
            (repository / "untracked.txt").write_text("not part of commit\n")
            exported = Path(directory) / "exported"
            commit, epoch = builder.export_commit(repository, "HEAD", exported)
            self.assertEqual(commit, builder.git(repository, "rev-parse", "HEAD"))
            self.assertTrue(epoch.isdigit())
            self.assertEqual((exported / "committed.txt").read_text(), "committed bytes\n")
            self.assertFalse((exported / "untracked.txt").exists())

    def test_inventory_includes_all_resource_families(self):
        inventory = builder.package_files(ROOT)
        self.assertIn("stdlib/collections.py", inventory)
        self.assertIn("grammar/python3.14.4.gram", inventory)
        self.assertIn("runtime/vm.rs", inventory)
        self.assertIn("licenses/CC0-1.0.txt", inventory)
        self.assertIn("unicode/NameAliases-16.0.0.txt", inventory)

    def test_wheel_missing_stale_and_extra_files_are_rejected(self):
        expected = {"api.py": b"# api", "runtime/vm.rs": b"// vm"}
        for actual in ({"api.py": b"# api"},
                       {"api.py": b"# api", "runtime/vm.rs": b"stale"},
                       {**expected, "extra.txt": b"untracked"}):
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as directory:
                wheel_path = Path(directory) / "fake.whl"
                with zipfile.ZipFile(wheel_path, "w") as wheel:
                    wheel.writestr("py2fastrust-0.1.dist-info/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
                    for name, data in actual.items():
                        wheel.writestr("py2fastrust/" + name, data)
                with self.assertRaises(ValueError):
                    builder.verify_wheel(wheel_path, expected)

    def test_platform_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel_path = Path(directory) / "fake.whl"
            with zipfile.ZipFile(wheel_path, "w") as wheel:
                wheel.writestr("py2fastrust-0.1.dist-info/WHEEL", "Root-Is-Purelib: false\nTag: cp314-linux\n")
            with self.assertRaisesRegex(ValueError, "pure Python"):
                builder.verify_wheel(wheel_path, {})

    def test_resource_hash_inventory_covers_bundled_python(self):
        expected = {"api.py": b"# api", "stdlib/collections.py": b"# bundled Python",
                    "runtime/vm.rs": b"// vm"}
        with tempfile.TemporaryDirectory() as directory:
            wheel_path = Path(directory) / "fake.whl"
            with zipfile.ZipFile(wheel_path, "w") as wheel:
                wheel.writestr("py2fastrust-0.1.dist-info/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
                for name, data in expected.items():
                    wheel.writestr("py2fastrust/" + name, data)
            resources = builder.verify_wheel(wheel_path, expected)
            self.assertEqual([item["path"] for item in resources], ["runtime/vm.rs", "stdlib/collections.py"])

    def test_production_build_rejects_preview_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "only.*preview"):
                builder.build_site(ROOT, Path(directory) / "site", "a" * 40,
                                   runtime_url="http://localhost/pyodide/")


if __name__ == "__main__":
    unittest.main()
