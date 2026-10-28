"""Finite native ordering follows CPython values, errors, and operand order."""
import itertools
import re
import shutil
import subprocess
import sys
import unittest

import test_native_iterator_reductions as helpers
from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeUnionOrderingTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeIteratorReductionTests.tearDownClass.__func__)
    compile = helpers.NativeIteratorReductionTests.compile

    def exercise(self, source, inputs, *, modes=("i64", "i128", "bigint"), string_mode="ascii"):
        for mode in modes:
            for release in (False, True):
                with self.subTest(mode=mode, release=release):
                    source_text, binary, _ = self.compile(source, mode, release, string_mode=string_mode)
                    for data in inputs:
                        expected = subprocess.run([sys.executable, "-I", "-c", source_text],
                                                  input=data, capture_output=True, text=True, timeout=5)
                        actual = subprocess.run([str(binary)], input=data, capture_output=True,
                                                text=True, timeout=5, env={"PATH": "/unavailable"})
                        self.assertEqual((actual.returncode, actual.stdout),
                                         (expected.returncode, expected.stdout), (mode, data, actual.stderr))
                        if expected.returncode:
                            message=expected.stderr.splitlines()[-1]
                            if message.startswith("NameError:"):
                                # CPython's display formatter may append a name
                                # suggestion; that advisory is not str(error).
                                # Keep the exact base exception text and all
                                # TypeError operator/type messages checked.
                                message=message.partition(". Did you mean:")[0]
                            self.assertEqual(actual.stderr.splitlines()[-1], message, data)
                            frames = r'File "[^"]+", line (\d+), in ([^\n]+)'
                            self.assertEqual(re.findall(frames, actual.stderr), re.findall(frames, expected.stderr), data)

    def test_nullable_integers_all_order_relations_and_orientations(self):
        for operator in ("<", "<=", ">", ">="):
            self.exercise('''n=int(input())
x=None if n<0 else n
print(x '''+operator+''' 2,2 '''+operator+''' x)
''', ("-1\n", "0\n", "1\n", "2\n", "3\n"))

    def test_exhaustive_immutable_alternatives_report_concrete_operand_types(self):
        for operator in ("<", "<=", ">", ">="):
            self.exercise('''def choose(n):
 if n==0:return None
 if n==1:return True
 if n==2:return 2
 if n==3:return "text"
 if n==4:return b"bytes"
 return (1,False)
def mark(tag,value):
 print(tag,end="|")
 return value
a,b=map(int,input().split())
print(mark("left",choose(a)) '''+operator+''' mark("right",choose(b)))
''', tuple(f"{a} {b}\n" for a,b in itertools.product(range(6), repeat=2)))

    def test_nullable_short_circuit_guards_are_ordinary_value_operations(self):
        self.exercise('''def choose(n):
 if n%2:return None
 return n
for i in range(5):
 value=choose(i)
 print(value is None or value>=2,value is not None and value<4)
 print(value is None,value==None,value!=None)
''', ("",))

    def test_chained_comparison_captures_once_and_short_circuits(self):
        self.exercise('''def choose(n):
 if n<0:return None
 return n
def mark(tag,value):
 print(tag,end="|")
 return value
x=choose(int(input()))
print(mark("left",x)<mark("middle",1)<mark("last",3))
''', ("-1\n", "0\n", "1\n", "2\n"))
        self.exercise('''def choose(n):
 if n<0:return None
 return n
def mark(tag,value):
 print(tag,end="|")
 return value
x=choose(int(input()))
print(mark("first",0)<mark("second",1)<mark("third",x)<mark("fourth",9))
''', ("-1\n", "0\n", "2\n", "10\n"))

    def test_operand_lookup_errors_precede_comparison_type_errors(self):
        self.exercise('''def mark(value):
 print("later",end="|")
 return value
if int(input()):
 value=3
print("start",end="|")
print(None<value<mark(9))
''', ("0\n", "1\n"))

    def test_tuple_fields_keep_lexicographic_order_and_actual_error_operator(self):
        for operator in ("<", "<=", ">", ">="):
            self.exercise('''n=int(input())
field=1 if n else "one"
left=((None,field),b"a")
right=((None,2),b"b")
print(left '''+operator+''' right)
''', ("0\n", "1\n"))
        self.exercise('''n=int(input())
left=(True,3) if n else (None,3)
right=(1,2)
print(left<right,left<=right,left>right,left>=right)
''', ("0\n", "1\n"))

    def test_generator_comparison_error_retains_its_own_frame(self):
        self.exercise('''values=[None,2]
print("start",end="|")
print(sum(value>0 for value in values))
''', ("",))

    def test_unicode_text_and_bytes_nullable_ordering(self):
        self.exercise('''n=int(input())
text="α🦀" if n else None
print(text<"β",text<="α🦀",text>="α",text>"Ω")
''', ("0\n", "1\n"), string_mode="unicode")
        self.exercise('''n=int(input())
text=b"ab" if n else None
print(text<b"b",text<=b"ab",text>=b"a",text>b"aa")
''', ("0\n", "1\n"))

    def test_exact_fixed_integer_float_ordering_and_unordered_nan(self):
        for operator in ("<", "<=", ">", ">="):
            self.exercise('''n=int(input())
number=float(input())
value=number if n else None
print(value '''+operator+''' 9007199254740993,9007199254740993 '''+operator+''' value)
''', ("0\n1.5\n", "1\nnan\n", "1\ninf\n", "1\n-inf\n",
      "1\n-0.0\n", "1\n9007199254740992\n", "1\n9007199254740994\n"),
                modes=("i64", "i128"))
        self.exercise('''n=int(input())
value=True if n==1 else 3 if n else None
print(value<1.5,value<=1.0,value>2.5,value>=3.0)
''', ("0\n", "1\n", "2\n"), modes=("i64", "i128"))
        self.exercise('''n=int(input())
value=(1<<100)+1 if n else None
print(value>float(1<<100),float(1<<100)<value)
''', ("0\n", "1\n"), modes=("i128",))

    def test_big_integer_nullable_ordering_uses_exact_limbs(self):
        self.exercise('''n=int(input())
value=(1<<180)+n if n else None
print(value<(1<<181),value<=(1<<180),value>(1<<180),value>=(1<<180))
''', ("0\n", "1\n", "-1\n"), modes=("bigint",))

    def test_literal_and_temporary_index_owners_outlive_borrowed_consumers(self):
        self.exercise('''def make():
 print("make",end="|")
 return input()
print("abc"[-1],"abc"[-1]<"zz","abcd"[-1][0])
print(make()[0],("a"+input())[-1],str("uvw")[-1])
''', ("fox\nbar\n",))
        self.exercise('print("abc"[int(input())])\n',
                      ("-4\n","-3\n","-1\n","0\n","2\n","3\n"))
        self.exercise('print("海🐈"[-1],("海"+"🐈")[0])\n',("",),string_mode="unicode")

    def test_unproved_mutable_and_tuple_float_identity_remain_explicit_gaps(self):
        # These check proof boundaries, not accepted-language completion.
        for mode in ("i64", "i128", "bigint"):
            for source in (
                'value=[1] if int(input()) else None\nprint(value<[2])\n',
                'value=(float("nan"),) if int(input()) else None\nprint(value<=(float("nan"),))\n',
            ):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":
    unittest.main()
