"""Shared check for former proof boundaries that may now convert.

For every integer mode, a source either converts and then behaves exactly like
CPython (stdout with object addresses masked, exit status and normalized
stderr, in debug and -O builds, with no rustc warnings), or it stays a
positioned E006 diagnostic. Support may differ between modes; a different
diagnostic code, an unpositioned diagnostic or a CPython mismatch fails.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from py2fastrust import TranspileOptions, transpile

MODES = ("i64", "i128", "bigint")


def _addresses(text):
    """Object reprs carry run-specific addresses in both CPython and native output."""
    return re.sub(r" at 0x[0-9a-f]+>", " at 0x...>", text)


def converted_or_positioned(test, source, inputs=("",)):
    """Return True when every mode converted (and matched CPython)."""
    from test_native_atexit import normalized_stderr
    converted = []
    with tempfile.TemporaryDirectory(prefix="pytors-boundary-") as directory:
        script = Path(directory) / "program.py"
        script.write_text(source)
        expected = {data: subprocess.run([sys.executable, "-I", "-S", str(script)], input=data,
                                         capture_output=True, text=True, timeout=20) for data in inputs}
        for mode in MODES:
            result = transpile(source, TranspileOptions(integer=mode, filename=str(script), license="none"))
            if not result.success:
                with test.subTest(source=source, integer=mode):
                    test.assertTrue(result.diagnostics, source)
                    test.assertEqual(result.diagnostics[0].code, "E006")
                    test.assertIsNotNone(result.diagnostics[0].line)
                converted.append(False)
                continue
            converted.append(True)
            test.assertEqual(result.backend, "native")
            test.assertLess(len(result.rust_source.encode()), 512 * 1024)
            rust = Path(directory) / (mode + ".rs")
            rust.write_text(result.rust_source)
            for optimized in (False, True):
                binary = rust.with_suffix(".opt" if optimized else ".debug")
                built = subprocess.run(["rustc", "--edition=2021", *(["-O"] if optimized else []), str(rust), "-o", str(binary)],
                                       capture_output=True, text=True, timeout=180)
                test.assertEqual(built.returncode, 0, built.stderr)
                test.assertNotIn("warning", built.stderr)
                for data in inputs:
                    actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=20,
                                            env={**os.environ, "PATH": "/no-python-runtime"})
                    reference = expected[data]
                    with test.subTest(source=source, integer=mode, optimized=optimized, stdin=data):
                        test.assertEqual((actual.returncode, _addresses(actual.stdout)),
                                         (reference.returncode, _addresses(reference.stdout)), actual.stderr)
                        test.assertEqual(normalized_stderr(actual.stderr), normalized_stderr(reference.stderr))
    return all(converted)
