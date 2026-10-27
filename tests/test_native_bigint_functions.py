"""Typed BigInt functions share scalar specialization and binding proofs."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
import test_native_bigint


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeBigIntFunctionTests(unittest.TestCase):
    compile=test_native_bigint.NativeBigIntTests.compile
    compare=test_native_bigint.NativeBigIntTests.compare
    differential=test_native_bigint.NativeBigIntTests.differential

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="pytors-native-bigint-functions-")
        cls.next_binary=0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_scalar_functions_specialize_integer_and_boolean_arguments(self):
        source='''def square(x):
    return x*x

def absolute(x):
    if x<0:
        return -x
    return x

def both(a,b):
    return a&b
print(square(1<<256),square(True),square(False))
print(absolute(-(10**120)),absolute(7))
print(both(True,False),both(1<<300,True),both(10**100,10**99))
'''
        binary,rust=self.compile(source)
        self.compare(binary,source)
        self.assertIn("fn native_function_0_int(",rust)
        self.assertIn("fn native_function_0_bool(",rust)

    def test_defaults_positional_only_keyword_only_and_argument_order(self):
        source='''def combine(a,/,b=10**100,*,c=-(2**150)):
    return a+b*c
print(combine(5),combine(5,c=7),combine(5,6,c=7))
print(combine(int(input()),c=int(input()),b=int(input())),int(input()))
'''
        self.differential(source,["11\n13\n17\n19\n"])

    def test_input_print_and_owned_parameters_do_not_change_callers(self):
        source='''def read_scaled(scale):
    print(7,end="|")
    a=int(input())
    return a*scale

def replace(value):
    value=10**200
    return value

def show(value):
    print(value,True,sep=":",flush=True)
    return
x=10**100
print(read_scaled(x))
print(replace(x),x)
show(x)
'''
        self.differential(source,["3\n","１２\n","bad\n",""])

    def test_mutual_call_dependencies_resolve_at_call_time(self):
        source='''def outer(value):
    return inner(value)+1

def inner(value):
    return value**2
print(outer(1<<256))
'''
        self.differential(source)
        source='''def outer(value):
    return inner(value)+1
print(outer(7))
def inner(value):
    return value**2
'''
        self.assertIsNone(try_generate_native(source,"main.py","bigint"))

    def test_return_paths_loops_and_branch_joins(self):
        source='''def solve(n):
    total=10**100
    for i in range(n):
        if i%3==0:
            continue
        total+=i*i
        if i>12:
            break
    if n:
        a=10**150
    else:
        a=10**160
    return total+a

def positive(n):
    if n>0:
        return True
    return False
print(solve(int(input())),positive(int(input())))
'''
        self.differential(source,["0\n0\n","17\n9\n","-5\n-7\n"])

    def test_numeric_defaults_are_evaluated_without_hiding_definition_errors(self):
        self.differential('''def f(a=(1<<300)+7,b=~(10**60),*,c=True):
    return a+b+int(c)
print(f(),f(True,c=False))
''')
        for source in ['def f(x=1//0):return x\nprint(f())\n',
                       'def f(x=len([int(input())])):return x\nprint(f())\n',
                       'def f(x=int(input())):return x\nprint(f())\n']:
            self.assertIsNone(try_generate_native(source,"main.py","bigint"))

    def test_statement_function_and_main_guard(self):
        source='''def solve():
    value=int(input())
    print(value**3)
if __name__=="__main__":
    solve()
'''
        self.differential(source,["7\n",f"{10**100}\n"])

    def test_error_traceback_keeps_compiled_function_call_sites(self):
        source='''def inner(value):
    return value//0
def outer(value):
    return inner(value+1)
print(9)
print(outer(10**100))
'''
        binary,_=self.compile(source)
        self.compare(binary,source)
        run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
        self.assertIn('line 6, in <module>',run.stderr)
        self.assertIn('line 4, in outer',run.stderr)
        self.assertIn('line 2, in inner',run.stderr)

    def test_immutable_aliases_and_argument_snapshots(self):
        source='''def change(a,b):
    a+=10**200
    b=False
    return a

def read(a,b):
    return a*100+b
value=10**100
print(change(value,value),value)
print(read(int(input()),int(input())),int(input()))
'''
        self.differential(source,["7\n9\n11\n"])

    def test_unproved_recursion_aliases_mutable_defaults_and_global_effects(self):
        for source in ['def f(n):\n return 1 if n<=0 else n*f(n-1)\nprint(f(7))\n',
                       'def a(x):return b(x)\ndef b(x):return a(x)\nprint(a(1))\n',
                       'def f(x):return x\ng=f\nprint(g(1))\n',
                       'def f(x=[]):return x\nprint(f())\n',
                       'x=7\ndef f():return x\nprint(f())\n',
                       'def f(x):\n global value\n value=x\nf(1)\n',
                       'def f(x):\n return x if x else False\nprint(f(7))\n']:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source,"main.py","bigint"))
