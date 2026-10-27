"""Ordinary native user calls with proved signatures and no dynamic globals."""

from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from wrapping_reference import execute


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-native-functions-")
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, integer, optimized):
        rust = try_generate_native(source, "native_functions.py", integer)
        self.assertIsNotNone(rust, source)
        self.assertIn("fn native_function_", rust)
        self.assertNotIn("enum Value", rust)
        self.assertNotIn("struct Runtime", rust)
        type(self).counter += 1
        path = Path(self.tmp.name) / f"functions{self.counter}.rs"
        path.write_text(rust, encoding="utf-8")
        command = ["rustc", "--edition=2021", *(["-O"] if optimized else []), str(path), "-o", str(path.with_suffix(""))]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(compiled.returncode, 0, compiled.stderr + "\n" + source)
        return path.with_suffix("")

    def differential(self, source, inputs=("",), modes=("i64", "i128"), optimized=(False, True), wrapping=False, trace=False):
        for integer in modes:
            expected = []
            for data in inputs:
                if wrapping:
                    value = execute(source, integer, data)
                    expected.append((value.stdout, value.returncode, value.exception_type, None))
                else:
                    value = subprocess.run([sys.executable, "-I", "-c", source], input=data, capture_output=True, text=True, timeout=5)
                    kind = value.stderr.strip().splitlines()[-1].split(":")[0] if value.returncode else None
                    expected.append((value.stdout, value.returncode, kind, value.stderr))
            for optimization in optimized:
                with self.subTest(integer=integer, optimized=optimization):
                    binary = self.compile(source, integer, optimization)
                    for data, (stdout, code, kind, stderr) in zip(inputs, expected):
                        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
                        self.assertEqual(actual.stdout, stdout, source + "\n" + data)
                        self.assertEqual(actual.returncode, code, actual.stderr)
                        if kind:
                            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0], kind)
                            if trace:
                                pattern = r"line (\d+), in ([^\n]+)"
                                self.assertEqual(re.findall(pattern, actual.stderr), re.findall(pattern, stderr))

    def test_multiple_calls_parameters_keywords_defaults_and_shadowing(self):
        self.differential('''
def mix(a,/,b=(2**5)//3,*,c=4):
 if a<0:
  return a-b*c
 return a+b*c
def square(x):
 return x*x
def shadow(square):
 return square+7
print(mix(3),mix(-2,c=7,b=3),square(mix(1,2,c=3)),shadow(11))
''')

    def test_argument_evaluation_order_before_parameter_reordering(self):
        self.differential('''
def mark(x):
 print(x)
 return x
def encode(a,/,b=3,*,c=4):
 return a+b*10+c*100
print(encode(mark(1),c=mark(2),b=mark(3)))
print(encode(mark(4),mark(5),c=mark(6)))
''')

    def test_integer_and_void_helpers_share_input_output(self):
        self.differential('''
def read_pair(scale):
 print(scale)
 a=int(input())
 b=int(input())
 return (a+b)*scale
def emit(value):
 print(value)
 return None
def solve():
 value=read_pair(3)
 emit(value)
if __name__=='__main__':
 solve()
''', ("5\n7\n", "1\ninvalid\n"), trace=True)

    def test_late_defined_callees_are_bound_at_every_call(self):
        self.differential('''
def first(x):
 return second(x)+third(x)
def third(x):
 return x*3
def second(x):
 return x*x
print(first(int(input())),second(5),first(-4))
''', ("7\n", "-8\n"))

    def test_function_local_containers_do_not_escape(self):
        self.differential('''
def calculate(n,offset):
 values=[0]*(n+2)
 seen=set()
 counts={}
 for i in range(n):
  key=(i+offset)%7
  seen.add(key)
  counts[key]=counts.get(key,0)+1
  values[i]=i*i
 return sum(values)+sum(seen)+sum(counts.values())
print(calculate(int(input()),3),calculate(0,7),calculate(8,-9))
''', ("0\n", "1\n", "17\n"))

    def test_exceptions_preserve_output_and_user_call_trace(self):
        self.differential('''
def bottom(x):
 print(8)
 return 10//x
def middle(x):
 return bottom(x-2)
def top(x):
 return middle(x)
print(1)
print(top(int(input())))
''', ("2\n", "4\n", "invalid\n"), trace=True)
        self.differential('''
def mark(x):
 print(x)
 return x
def pair(a,b):
 return a+b
print(pair(mark(7),1//0))
''', trace=True, optimized=(True,))

    def test_fixed_width_operations_across_calls(self):
        rng = random.Random(20261028)
        inputs = []
        for bits in (64, 128):
            values = [-(1 << (bits-1)), (1 << (bits-1))-1, 1 << bits, -1, 0, 1]
            values += [rng.randrange(-(1 << bits), 1 << bits) for _ in range(9)]
            inputs += [f"{value}\n{rng.randrange(-99,100)}\n{rng.randrange(0,13)}\n" for value in values]
        self.differential('''
def step(a,b,shift=3,*,bias=(1<<64)+3):
 return ((a*b+bias)>>shift)^(a+b)
def accumulate(a,b,n):
 total=0
 for i in range(n):
  a=step(a,b)
  total+=a**3
  b=(a//3)^b
 return total+a+b
print(accumulate(int(input()),int(input()),int(input())))
''', inputs, wrapping=True)

    def test_dynamic_globals_alias_defaults_binding_and_recursion_fall_back(self):
        programs = [
            "offset=3\ndef f(x): return x+offset\nprint(f(2))",
            "def f(x):\n global y\n y=x\n return x\nprint(f(2))",
            "def outer(x):\n def inner(y): return x+y\n return inner(2)\nprint(outer(3))",
            "def f(x=int(input())): return x\nprint(f())",
            "def f(x=[]): return len(x)\nprint(f())",
            "def f(x): return x\ng=f\nprint(g(1))",
            "def f(x): return x\nf=3\nprint(f)",
            "def f(x): return x\ndef f(x): return x+1\nprint(f(1))",
            "def f(x): return x\nprint(f.__defaults__)",
            "def f(x): return x\nprint(f([1]))",
            "def f(x): return [x]\nprint(f(1))",
            "def f(x):\n if x: return 1\nprint(f(0))",
            "def f(x): return x\nprint(f())",
            "def f(x): return x\nprint(f(1,2))",
            "def f(x): return x\nprint(f(1,x=2))",
            "def f(x,/): return x\nprint(f(x=1))",
            "def f(x): return x\nprint(f(y=1))",
            "def f(*xs): return len(xs)\nprint(f(1,2))",
            "def f(**xs): return len(xs)\nprint(f(x=1))",
            "def f(x): return x\nprint(f(*[1]))",
            "def f(x): return x\nprint(f(**{'x':1}))",
            "def f(x): return 1 if x==0 else f(x-1)\nprint(f(5))",
            "def f(x): return g(x)\ndef g(x): return f(x)\nprint(f(1))",
            "def first(x): return later(x)\nprint(first(1))\ndef later(x): return x",
            "if int(input()):\n def f(x): return x\nprint(f(1))",
            "def f(x): return y\nprint(f(1))",
            "def f(x): return x\n__builtins__=0\nprint(f(1))",
            "def f(x): return x\n__name__=3\nif __name__=='__main__': print(f(1))",
            "def f(len): return len+1\nprint(f(1))",
            "def f(x): pass\ny=f(1)\nprint(y)",
            "def f(x):\n print(x)\n return\n yield 2\nf(1)",
            "def f(x):\n return x\n yield from [2]\nprint(f(1))",
        ]
        programs.append("\n".join(f"def f{i}(x): return " + (f"f{i+1}(x)" if i<129 else "x")
                                  for i in range(130)) + "\nprint(f0(1))")
        for source in programs:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "fallback.py", "i64"))
        source = "def f(x): return x\ng=f\nprint(g(1))"
        result = transpile(source, TranspileOptions())
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "aot")

    def test_bigint_scalar_functions_use_native_rust(self):
        source = "def f(x): return x*x\nprint(f(1<<256))"
        self.assertIsNotNone(try_generate_native(source, "big.py", "bigint"))
        result = transpile(source, TranspileOptions(integer="bigint"))
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "native")


if __name__ == "__main__":
    unittest.main()
