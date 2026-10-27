"""Finite bool/int type sets across native branches and loop back edges."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from wrapping_reference import execute


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeUnionTests(unittest.TestCase):
    def compare(self, source, inputs=("0\n", "1\n", "2\n", "5\n"), *, wrapping=False):
        for integer in ("i64", "i128"):
            result = transpile(source, TranspileOptions(integer=integer, filename="union.py"))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native", source)
            self.assertTrue("enum NativeScalar" in result.rust_source)
            self.assertFalse("enum Value" in result.rust_source)
            self.assertFalse("struct Runtime" in result.rust_source)
            for release in (False, True):
                with self.subTest(integer=integer, release=release):
                    with tempfile.TemporaryDirectory(prefix="pytors-native-union-") as directory:
                        rs = Path(directory, "main.rs")
                        rs.write_text(result.rust_source)
                        compiled = subprocess.run(
                            ["rustc", "--edition=2021", *(["-O"] if release else []), str(rs), "-o", str(rs.with_suffix(""))],
                            capture_output=True, text=True, timeout=120,
                        )
                        self.assertEqual(compiled.returncode, 0, compiled.stderr)
                        for data in inputs:
                            actual = subprocess.run([str(rs.with_suffix(""))], input=data,
                                                    capture_output=True, text=True, timeout=5)
                            expected = execute(source, integer, data) if wrapping else subprocess.run(
                                [sys.executable, "-I", "-c", source], input=data,
                                capture_output=True, text=True, timeout=5,
                            )
                            self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                            self.assertEqual(actual.stdout, expected.stdout, data + "\n" + actual.stderr)

    def test_branch_phis_retain_types_through_copies_and_overwrites(self):
        self.compare('''
n=int(input())
if n:value=True
else:value=7
left=right=value
print(value,left,right,value+3,int(value),not value)
value=[2,3]
print(sum(value),left,right)
value=False
print(value,left,right)
''')

    def test_conditional_and_boolean_expressions_keep_selected_value_tags(self):
        self.compare('''
n=int(input())
x=True if n else 0
y=x and 17
z=x or 23
print(x,y,z,False and int(input()),True or int(input()))
print((False and 3) or (True and 0),n and False,n or True)
print(int(input()))
''', ("0\n77\n", "1\n88\n", "-1\n99\n"))

    def test_for_back_edges_break_continue_and_zero_iterations(self):
        self.compare('''
n=int(input())
x=True
i=99
for i in range(n):
    print(x)
    if i%2:x=True
    else:x=i+1
    if i==2:continue
    if i==4:break
print(x,i)
''', ("0\n", "1\n", "3\n", "9\n"))

    def test_while_back_edges_preserve_truth_and_numeric_conversions(self):
        self.compare('''
n=int(input())
x=False
i=0
while i<n:
    print(x,x+1)
    i+=1
    if i%2:x=i
    else:x=True
    if i==2:continue
    if i==4:break
print(x,i)
''')

    def test_loop_target_type_union_preserves_preexisting_zero_case(self):
        self.compare('''
n=int(input())
value=True
for value in range(n):
    pass
print(value)
''')

    def test_bitwise_union_returns_bool_only_for_two_actual_bools(self):
        self.compare('''
n=int(input())
a=True if n%2 else 2
b=False if n%3 else 3
print(a&b,a|b,a^b,a&1,1|a,a^3)
print((a&b)^True,not a,a<b,a==b)
''', ("0\n", "1\n", "2\n", "3\n", "6\n"))

    def test_unsupported_container_unions_keep_general_backend(self):
        for source in (
            "if int(input()):x=[1]\nelse:x=True\nprint(x)",
            "n=int(input())\nx=True if n else 2\na=[x]\nprint(a)",
        ):
            with self.subTest(source=source):
                result = transpile(source)
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.backend, "aot")

    def test_union_numeric_operations_preserve_fixed_width_normalization(self):
        self.compare('''
n=int(input())
value=(2**127-1) if n else True
print(value,value+1,value*3,-value)
value ^= False if n%2 else 7
print(value,value//-3,value%-3,value<<128,value>>128)
''', wrapping=True)
