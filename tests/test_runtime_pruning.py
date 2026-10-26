"""Proven runtime omission, adversarial fallbacks and standalone execution."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.codegen import generate
from py2fastrust.compiler import Compiler
from py2fastrust.reachability import dynamic_compilation_unreachable


SIMPLE = '''\
state = 0
state = "文字🙂"
values = [int(input()), -7, 2]
shared = [values, values]
shared[0][0] += 3
print(state, values, sum(values), shared[1] is values)
for i in range(3):
    values[i] = values[i] // 2
print(values, -17 // 5, -17 % 5, bytes([65, 0, 255]))
print(f"{state}:{len(values)}", "\N{SNOWMAN}", input(), sep="|", end="!\\n")
'''


class ReachabilityTests(unittest.TestCase):
    def proof(self, source):
        return dynamic_compilation_unreachable(source, Compiler("proof.py").compile(source))

    def test_unknown_calls_bindings_and_syntax_keep_dynamic_compiler(self):
        for source in (
            "int = eval\nprint(int('3+4'))",
            "callback = eval\nprint(callback('3+4'))",
            "print(sorted(['3+4', '2+3'], key=eval))",
            "match eval:\n case int:\n  print(int('3+4'))",
            "globals()['int'] = eval\nprint(int('3+4'))",
            "__builtins__.int = eval\nprint(int('3+4'))",
            "print([eval][0]('3+4'))",
            "print([x for x in range(3)])",
            "def f(): return 1\nprint(f())",
            "import math\nprint(math.isqrt(9))",
            "class C: pass\nprint(C())",
        ):
            with self.subTest(source=source):
                self.assertFalse(self.proof(source))
                result = transpile(source)
                self.assertTrue(result.success, result.diagnostics)
                if result.backend == "vm":
                    self.assertTrue("struct PegParser" in result.rust_source, "dynamic parser was incorrectly omitted")

    def test_simple_vm_proof_and_no_optimize_override(self):
        self.assertTrue(self.proof(SIMPLE))
        optimized = transpile(SIMPLE)
        complete = transpile(SIMPLE, TranspileOptions(optimize=False))
        self.assertEqual(optimized.backend, "vm")
        self.assertTrue(optimized.success, optimized.diagnostics)
        self.assertTrue(complete.success, complete.diagnostics)
        self.assertFalse("struct PegParser" in optimized.rust_source, "unreachable parser was retained")
        self.assertFalse("enum DExpr" in optimized.rust_source, "unreachable dynamic AST was retained")
        self.assertTrue("struct PegParser" in complete.rust_source, "--no-optimize must retain the parser")
        self.assertLess(len(optimized.rust_source), len(complete.rust_source) * 0.7)
        self.assertEqual(optimized.source_map, complete.source_map)

    def test_internal_codegen_defaults_to_full_runtime(self):
        source, _ = generate(Compiler("empty.py").compile(""))
        self.assertTrue("struct PegParser" in source)
        # An optional full-runtime generation must not leak between calls.
        self.assertTrue("struct PegParser" in transpile(SIMPLE, TranspileOptions(optimize=False)).rust_source)
        self.assertFalse("struct PegParser" in transpile(SIMPLE).rust_source)

    def test_source_option_can_disable_pruning(self):
        source = "# pytors: --no-optimize\n" + SIMPLE
        result = transpile(source, TranspileOptions(optimize=True))
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue("struct PegParser" in result.rust_source)

    def test_explicit_bundled_modules_are_kept_conservatively(self):
        with tempfile.TemporaryDirectory(prefix="py2fastrust-pruning-module-") as directory:
            Path(directory, "kept.py").write_text("value = 1\n", encoding="utf-8")
            result = transpile(SIMPLE, TranspileOptions(
                module_paths=(Path(directory),), include_modules=("kept",),
            ))
            self.assertTrue(result.success, result.diagnostics)
            self.assertTrue("struct PegParser" in result.rust_source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class PrunedExecutionTests(unittest.TestCase):
    def compare(self, source, *, integer="i64", release=False, data=""):
        result = transpile(source, TranspileOptions(integer=integer, filename="pruning_fixture.py"))
        self.assertTrue(result.success, result.diagnostics)
        with tempfile.TemporaryDirectory(prefix="py2fastrust-pruning-") as directory:
            rs = Path(directory) / "main.rs"
            binary = Path(directory) / "main"
            rs.write_text(result.rust_source, encoding="utf-8")
            command = ["rustc", "--edition=2021", str(rs), "-o", str(binary)]
            if release:
                command.append("-O")
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=180)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            actual = subprocess.run(
                [str(binary)], input=data, capture_output=True, text=True,
                env={**os.environ, "PATH": "/pytors-no-external-programs"}, timeout=10,
            )
            expected = subprocess.run(
                [sys.executable, "-I", "-c", source], input=data,
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
            self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
            if actual.returncode:
                self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                                 expected.stderr.strip().splitlines()[-1].split(":")[0])
                self.assertIn('File "pruning_fixture.py", line 3', actual.stderr)
        return result

    def test_pruned_vm_all_integer_modes_and_build_profiles(self):
        for integer in ("i64", "i128", "bigint"):
            for release in (False, True):
                with self.subTest(integer=integer, release=release):
                    result = self.compare(SIMPLE, integer=integer, release=release, data="12\n\n")
                    self.assertEqual(result.backend, "vm")
                    self.assertFalse("struct PegParser" in result.rust_source)

    def test_pruned_exception_keeps_prior_output_and_source_location(self):
        result = self.compare('state = "ready"\nprint(state)\nvalue = [1][3]\n')
        self.assertEqual(result.backend, "vm")
        self.assertFalse("struct PegParser" in result.rust_source)

    def test_indirect_dynamic_calls_retain_working_compiler(self):
        source = '''\
callback = eval
int = callback
print(int("3+4"))
print(sorted(["3+4", "2+3"], key=eval))
match eval:
    case binding:
        print(binding("5+6"))
globals()["int"] = eval
print(int("7+8"))
callback = compile
code = callback("print('dynamic')", "indirect.py", "exec")
exec(code)
'''
        result = self.compare(source)
        self.assertEqual(result.backend, "vm")
        self.assertTrue("struct PegParser" in result.rust_source)
