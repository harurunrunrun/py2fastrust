"""Native scalar operations preserve Python bool/int result distinctions."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeScalarTypeTests(unittest.TestCase):
    def compare(self, source, inputs=("",)):
        for integer in ("i64", "i128"):
            result = transpile(source, TranspileOptions(integer=integer, filename="scalar_types.py"))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native", source)
            self.assertFalse("enum Value" in result.rust_source)
            for release in (False, True):
                with self.subTest(integer=integer, release=release):
                    with tempfile.TemporaryDirectory(prefix="pytors-native-scalars-") as directory:
                        rs = Path(directory, "main.rs")
                        binary = rs.with_suffix("")
                        rs.write_text(result.rust_source, encoding="utf-8")
                        compiled = subprocess.run(
                            ["rustc", "--edition=2021", *(["-O"] if release else []), str(rs), "-o", str(binary)],
                            capture_output=True, text=True, timeout=90,
                        )
                        self.assertEqual(compiled.returncode, 0, compiled.stderr)
                        for data in inputs:
                            actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
                            expected = subprocess.run([sys.executable, "-I", "-c", source], input=data,
                                                      capture_output=True, text=True, timeout=5)
                            self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                            self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
                            if actual.returncode:
                                self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                                                 expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_boolean_bitwise_results_and_mixed_numeric_operands(self):
        self.compare('''
a=int(input()) != 0
b=int(input()) != 0
print(a & b,a | b,a ^ b)
print((a & b) ^ a,(a | b) & b)
print(a & 1,1 & a,a | 2,2 | a,a ^ 3,3 ^ a)
print(True & False,True | False,True ^ False)
''', ("0\n0\n", "0\n1\n", "1\n0\n", "1\n1\n"))

    def test_augmented_assignment_keeps_boolean_bindings_through_loops(self):
        self.compare('''
a=True
b=False
a &= False
b |= True
print(a,b)
a ^= b
print(a,b)
for i in range(4):
    a &= i % 2 == 0
    b ^= i % 3 == 0
    print(a,b)
a += 2
b *= 3
print(a,b)
''')

    def test_bitwise_evaluation_consumes_each_operand_in_order(self):
        self.compare('''
print((int(input()) != 0) & (int(input()) != 0))
print((int(input()) != 0) | (int(input()) != 0))
print(int(input()))
''', ("0\n1\n1\n0\n77\n", "1\n0\n0\n1\n88\n"))
