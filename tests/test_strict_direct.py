"""Public conversion either generates direct Rust or reports its missing case."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from py2fastrust.native_bigint import try_generate_bigint


class StrictDirectTests(unittest.TestCase):
    def assert_direct(self, result):
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, "native")
        for marker in ("enum Value", "struct Runtime", "enum Op", "fn step(", "struct PegParser"):
            self.assertNotIn(marker, result.rust_source)

    def test_unsupported_normal_python_never_selects_general_codegen(self):
        sources = (
            "def outer(x):\n def inner():return x\n return inner\nprint(outer(3)())\n",
            "values=[1]\nalias=values\nalias.append(2)\nprint(values)\n",
            "def recurse(n):return recurse(n-1) if n else 0\nprint(recurse(3))\n",
            "try:\n print(1//0)\nexcept ZeroDivisionError:\n print(7)\n",
            "print(eval('1+2'))\n",
            "def sequence():yield 1\nprint(list(sequence()))\n",
        )
        with patch("py2fastrust.codegen.generate", side_effect=AssertionError("general backend entered")) as general:
            for integer in ("i64", "i128", "bigint"):
                for optimize in (False, True):
                    for source in sources:
                        with self.subTest(integer=integer, optimize=optimize, source=source):
                            result = transpile(source, TranspileOptions(integer=integer, optimize=optimize,
                                                                       filename="fresh_solution.py"))
                            self.assertFalse(result.success)
                            self.assertIsNone(result.rust_source)
                            self.assertEqual(result.diagnostics[0].code, "E006")
                            self.assertEqual(result.diagnostics[0].filename, "fresh_solution.py")
                            self.assertGreaterEqual(result.diagnostics[0].line, 1)
                            self.assertIn("Cannot lower ", result.diagnostics[0].message)
                            self.assertIn("Source:", result.diagnostics[0].message)
            general.assert_not_called()

    def test_proved_class_programs_never_select_general_codegen(self):
        sources = (
            "class Item:\n def __init__(self,value):self.value=value\nprint(Item(3).value)\n",
            "class Example:\n pass\n",
            "# first\nclass Unsupported:pass\n",
        )
        with patch("py2fastrust.codegen.generate", side_effect=AssertionError("general backend entered")) as general:
            for integer in ("i64", "i128", "bigint"):
                for optimize in (False, True):
                    for source in sources:
                        with self.subTest(integer=integer,optimize=optimize,source=source):
                            self.assert_direct(transpile(source, TranspileOptions(integer=integer,optimize=optimize)))
            general.assert_not_called()

    def test_proved_standard_calls_never_select_general_codegen(self):
        sources=("import math\nprint(math.isqrt(9))\n",
                 "from bisect import bisect_left\na=[1,3,3]\nprint(bisect_left(a,3))\n")
        with patch("py2fastrust.codegen.generate",side_effect=AssertionError("general backend entered"))as general:
            for integer in ("i64","i128","bigint"):
                for source in sources:
                    self.assert_direct(transpile(source,TranspileOptions(integer=integer)))
            general.assert_not_called()

    def test_diagnostics_locate_the_unsupported_ast_operation(self):
        for integer in ("i64", "i128", "bigint"):
            with self.subTest(integer=integer):
                result = transpile("# comments\n\nclass Example(object):\n pass\n", TranspileOptions(
                    integer=integer, filename="nested/source.py"))
                diagnostic = result.diagnostics[0]
                self.assertEqual((diagnostic.filename, diagnostic.line, diagnostic.column, diagnostic.code),
                                 ("nested/source.py", 3, 1, "E006"))
                result = transpile("ready=3\nvalue=object()\n", TranspileOptions(
                    integer=integer, filename="nested/source.py"))
                self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 7))

    def test_official_frontend_and_option_diagnostics_are_preserved(self):
        for source, options, code in (
            ("for\n", TranspileOptions(filename="syntax.py"), "E001"),
            ("return 1\n", TranspileOptions(filename="context.py"), "E001"),
            ("import unavailable_pytors_test_module\n", TranspileOptions(filename="module.py"), "E003"),
            ("print(1)\n", TranspileOptions(filename="mode.py", integer="u64"), "E004"),
            ("# pytors: --license unavailable\nprint(1)\n", TranspileOptions(filename="options.py"), "E004"),
        ):
            with self.subTest(source=source):
                result = transpile(source, options)
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code, code)
                self.assertEqual(result.diagnostics[0].filename, options.filename)

    def test_no_optimize_still_generates_direct_rust_without_pruning(self):
        with patch("py2fastrust.codegen.generate", side_effect=AssertionError("general backend entered")), \
             patch("py2fastrust.rust_pruning.prune_rust_source", side_effect=AssertionError("optional pruning entered")):
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(integer=integer):
                    result = transpile("print(7)\n", TranspileOptions(integer=integer, optimize=False))
                    self.assert_direct(result)
                    self.assertIn("fn main()", result.rust_source)

    def test_entrypoint_optional_diagnostics_and_pruning_flags(self):
        source = "# first\nclass Unsupported(object):pass\n"
        for integer in ("i64", "i128", "bigint"):
            diagnostics = []
            self.assertIsNone(try_generate_native(source, "entry.py", integer, diagnostic_out=diagnostics))
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual((diagnostics[0].code, diagnostics[0].line), ("E006", 2))
        diagnostics = []
        self.assertIsNone(try_generate_bigint(source, "big.py", diagnostic_out=diagnostics))
        self.assertEqual((diagnostics[0].filename, diagnostics[0].line), ("big.py", 2))

    def test_explicit_included_modules_are_not_silently_dropped(self):
        with tempfile.TemporaryDirectory(prefix="pytors-direct-module-") as directory:
            root = Path(directory)
            (root / "bundled.py").write_text("value=7\n", encoding="utf-8")
            with patch("py2fastrust.codegen.generate", side_effect=AssertionError("general backend entered")), \
                 patch("py2fastrust.api.try_generate_native", side_effect=AssertionError("module ignored")):
                result = transpile("print(7)\n", TranspileOptions(filename=str(root / "main.py"),
                                   module_paths=(root,), include_modules=("bundled",)))
            self.assertFalse(result.success)
            self.assertIsNone(result.rust_source)
            self.assertEqual(result.diagnostics[0].code, "E006")
            self.assertIn("--include-module", result.diagnostics[0].message)

    def test_missing_native_result_cannot_trigger_another_backend(self):
        with patch("py2fastrust.api.try_generate_native", return_value=None), \
             patch("py2fastrust.codegen.generate", side_effect=AssertionError("general backend entered")) as general:
            result = transpile("print(3)\n", TranspileOptions(filename="unimplemented.py"))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code, "E006")
        general.assert_not_called()

    def test_cli_error_keeps_existing_output_and_reports_position(self):
        with tempfile.TemporaryDirectory(prefix="pytors-direct-cli-") as directory:
            root = Path(directory)
            source = root / "solution.py"
            output = root / "solution.rs"
            source.write_text("# original\n\nclass Unsupported(object):pass\n", encoding="utf-8")
            output.write_text("keep", encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "py2fastrust", str(source), "--no-optimize", "-o", str(output)],
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(f"{source}:3:1: E006:", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(output.read_text(), "keep")

    def test_source_options_override_cli_without_backend_switch(self):
        with tempfile.TemporaryDirectory(prefix="pytors-direct-options-") as directory:
            root = Path(directory)
            source = root / "solution.py"
            output = root / "solution.rs"
            source.write_text("# pytors: --no-optimize --int i128\nprint(7)\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "py2fastrust", str(source), "--optimize", "--int", "i64", "-o", str(output)],
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            rust = output.read_text()
            self.assertIn("// Integer mode: i128.", rust)
            self.assertIn("fn native_pow(", rust)
            self.assertNotIn("struct Runtime", rust)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class DirectNoOptimizeExecutionTests(unittest.TestCase):
    def test_all_integer_modes_compile_and_execute_without_optimization(self):
        source = "A,B,C=map(int,input().split())\nanswer=max(0,(C-A+B-1)//B)\nprint(answer)\n"
        with tempfile.TemporaryDirectory(prefix="pytors-direct-noopt-") as directory:
            root = Path(directory)
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(integer=integer):
                    result = transpile(source, TranspileOptions(integer=integer, optimize=False))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    target = root / f"{integer}.rs"
                    binary = target.with_suffix("")
                    target.write_text(result.rust_source, encoding="utf-8")
                    built = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(binary)],
                                           text=True, capture_output=True, timeout=90)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    actual = subprocess.run([str(binary)], input="4 3 12\n", text=True, capture_output=True,
                                            env={**os.environ, "PATH": str(root / "unavailable")}, timeout=5)
                    self.assertEqual((actual.returncode, actual.stdout), (0, "3\n"), actual.stderr)


if __name__ == "__main__":
    unittest.main()
