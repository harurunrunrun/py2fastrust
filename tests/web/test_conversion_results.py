"""The Pages verifier must accept actual CLI rejection results and continue."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("node"), "node is required")
class ConversionResultTests(unittest.TestCase):
    def test_actual_cli_rejections_continue_to_a_later_success(self):
        sources = ("print(1)\n", "print(eval('40 + 2'))\n", "def broken(:\n", "print('again')\n")
        cases = []
        previous = ""
        with tempfile.TemporaryDirectory(prefix="pytors-conversion-results-") as temporary:
            for index, source in enumerate(sources):
                directory = Path(temporary) / str(index)
                directory.mkdir()
                (directory / "main.py").write_text(source, encoding="utf-8")
                converted = transpile(source, TranspileOptions(filename="main.py", module_paths=(directory,)))
                cli = subprocess.run([sys.executable, "-m", "py2fastrust", "main.py", "-o", "main.rs"],
                                     cwd=directory, env={**os.environ, "PYTHONPATH": str(ROOT)},
                                     capture_output=True, text=True, timeout=30)
                output = converted.rust_source if converted.success else previous
                if converted.success:
                    self.assertEqual((directory / "main.rs").read_text(), converted.rust_source)
                else:
                    self.assertEqual(cli.returncode, 2, cli.stderr)
                    self.assertFalse((directory / "main.rs").exists())
                cases.append({"name": str(index),
                    "status": "Conversion complete." if converted.success else "Error: Conversion failed. See diagnostics below.",
                    "result": {"rust_source": converted.rust_source,
                               "diagnostics": [diagnostic.__dict__ for diagnostic in converted.diagnostics]},
                    "cli": {"status": cli.returncode, "stdout": cli.stdout, "stderr": cli.stderr},
                    "output": output, "previousOutput": previous})
                previous = output
            module = (ROOT / "tests/web/conversion-results.mjs").as_uri()
            script = (f"import {{ verifyConversionResult, conversionSummary }} from {json.dumps(module)};\n"
                      "import { readFileSync } from 'node:fs';\n"
                      "const cases = JSON.parse(readFileSync(0, 'utf8')).map(verifyConversionResult);\n"
                      "console.log(JSON.stringify({ cases, summary: conversionSummary({ success: true, cases }) }));\n")
            checked = subprocess.run(["node", "--input-type=module", "-e", script],
                                     input=json.dumps(cases), capture_output=True, text=True, timeout=30)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            report = json.loads(checked.stdout)
            expected = ["failed" if case["result"]["rust_source"] is None else "passed" for case in cases]
            self.assertEqual([case["conversion"] for case in report["cases"]], expected)
            self.assertEqual(expected[2], "failed")  # Invalid syntax remains a rejection as support grows.
            self.assertEqual(expected[-1], "passed")
            self.assertEqual(report["summary"]["converted"], expected.count("passed"))
            self.assertEqual(report["summary"]["conversion_failures"], expected.count("failed"))
            self.assertFalse(report["summary"]["all_converted"])
