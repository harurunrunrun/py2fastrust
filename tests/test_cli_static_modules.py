"""The CLI bundles fixed-name package imports into standalone native Rust."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StaticModuleCLITests(unittest.TestCase):
    def test_packages_and_local_imports_run_without_source_files(self):
        with tempfile.TemporaryDirectory(prefix="pytors-cli-static-") as directory:
            root = Path(directory)
            package = root / "helpers"
            package.mkdir()
            (package / "__init__.py").write_text("from .calc import twice\n")
            (package / "calc.py").write_text(
                "print('initialize')\n"
                "def twice(value):\n return value * 2\n"
                "def append(values, value):\n values.append(value)\n"
            )
            source = root / "main.py"
            source.write_text(
                "from helpers import twice\n"
                "import helpers.calc as operations\n"
                "def run():\n"
                " import helpers.calc as again\n"
                " values = []\n"
                " for value in range(3):\n"
                "  again.append(values, value)\n"
                " print(twice(sum(values)), values, again is operations)\n"
                "run()\n"
            )
            oracle = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name='__main__')",
                 str(root), str(source)], capture_output=True, text=True, timeout=10
            )
            self.assertEqual((oracle.returncode, oracle.stderr), (0, ""))
            products = []
            for integer in ("i64", "i128", "bigint"):
                output = root / (integer + ".rs")
                generated = subprocess.run(
                    [sys.executable, "-m", "py2fastrust", str(source), "--int", integer,
                     "--license", "none", "-o", str(output)],
                    capture_output=True, text=True, timeout=30
                )
                self.assertEqual(generated.returncode, 0, generated.stderr)
                self.assertLess(output.stat().st_size, 512 * 1024)
                self.assertNotIn("enum Value", output.read_text())
                for optimized in (False, True):
                    binary = root / (integer + ("_release" if optimized else "_debug"))
                    compiled = subprocess.run(
                        ["rustc", "--edition=2021", *(["-O"] if optimized else []),
                         str(output), "-o", str(binary)],
                        capture_output=True, text=True, timeout=90
                    )
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    products.append(binary)
            for path in package.glob("*.py"):
                path.unlink()
            source.unlink()
            for binary in products:
                with self.subTest(binary=binary.name):
                    actual = subprocess.run(
                        [str(binary)], cwd="/tmp", capture_output=True, text=True, timeout=10,
                        env={**os.environ, "PATH": "/pytors-no-python-runtime",
                             "PYTHONPATH": "/pytors-no-python-runtime"}
                    )
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (oracle.returncode, oracle.stdout, oracle.stderr))


if __name__ == "__main__":
    unittest.main()
