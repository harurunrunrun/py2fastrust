"""Scalar extrema retain evaluation order and produce compact Rust source."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from wrapping_reference import execute
import test_native


EXAMPLE = '''A, B, C = map(int, input().split())

ans = max(0, (C - A + B - 1) // B)

print(ans)
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeExtremaTests(unittest.TestCase):
    compile = test_native.NativeTests.compile
    differential = test_native.NativeTests.differential

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-native-extrema-")
        cls.next_binary = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reported_source_size_and_wrapping_in_both_build_profiles(self):
        for integer, bits in [("i64", 64), ("i128", 128)]:
            result = transpile(EXAMPLE, TranspileOptions(integer=integer, filename="main.py"))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native")
            self.assertLess(len(result.rust_source.encode("utf-8")), 512 * 1024)
            for forbidden in ["enum Op", "enum Value", "struct Runtime", "fn step(", "struct PegParser"]:
                self.assertNotIn(forbidden, result.rust_source)
            for unused in ["fn native_pow(", "fn native_shl(", "fn native_shr("]:
                self.assertNotIn(unused, result.rust_source)
            source = Path(self.tmp.name, f"example_{integer}.rs")
            source.write_text(result.rust_source, encoding="utf-8")
            inputs = ["1 2 10\n", "10 3 1\n", "-5 -3 7\n", "7 0 9\n",
                      "1 2\n", "1 2 3 4\n", "1 2 invalid\n", "\n", "",
                      f"{-2**(bits-1)} -1 {2**(bits-1)-1}\n"]
            for release in [False, True]:
                binary = Path(self.tmp.name, f"example_{integer}_{release}")
                build = subprocess.run(["rustc", "--edition=2021", *(["-O"] if release else []), str(source), "-o", str(binary)], capture_output=True, text=True, timeout=120)
                self.assertEqual(build.returncode, 0, build.stderr)
                for data in inputs:
                    with self.subTest(integer=integer, release=release, data=data):
                        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
                        expected = execute(EXAMPLE, integer, data)
                        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
                        if actual.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0], expected.exception_type)

    def test_positional_extrema_keep_boolean_ties_and_argument_order(self):
        self.differential('''
print(max(False,0),max(0,False),min(True,1),min(1,True))
print(min(False,True),max(False,True),max(False,0,True,1),min(True,1,False,0))
print(max(int(input()),int(input()),int(input())),int(input()))
print(min(int(input()),int(input()),int(input())),int(input()))
''', ["7\n3\n7\n99\n-2\n-7\n4\n88\n"])

    def test_iterables_ranges_views_and_defaults(self):
        self.differential('''
values=[9,3,7]
mapping={9:1,3:12,7:-2}
print(min(values),max(values),min(mapping),max(mapping.values()))
print(min((True,1)),max((1,True)),min([],default=True),max((),default=7))
print(max(values,default=False,key=None),min([True,False],default=9))
print(min(range(9,-7,-2)),max(range(9,-7,-2)))
print(max(map(int,input().split())),min(map(int,input().split())))
''', ["4 10 -8\n6 -4 20\n"])

    def test_default_evaluates_before_iteration_but_after_source(self):
        self.differential('''
values=[3,8]
print(max(values,default=int(input())),int(input()))
print(min(range(1,9,int(input())),default=int(input())),int(input()))
''', ["77\n88\n2\n99\n111\n", "77\n88\n0\n99\n111\n"])

    def test_function_specialization_and_empty_iterable_errors(self):
        self.differential('''
def clamp(value,low,high):
    return min(high,max(low,value))
print(clamp(int(input()),-4,9),clamp(7,2,3))
''', ["-10\n", "4\n", "30\n"])
        for name in ["min", "max"]:
            self.differential(f"print(1)\nprint({name}([]))\n")

    def test_unproved_callbacks_and_rebound_builtins_are_not_specialized(self):
        for source in ["max=lambda *args:7\nprint(max(1,2))\n",
                       "def min(a,b):return a+b\nprint(min(1,2))\n",
                       "print(max([1,2],key=lambda x:-x))\n",
                       "print(max(1,2,default=3))\n"]:
            self.assertIsNone(try_generate_native(source,"native_input.py","i64"))
