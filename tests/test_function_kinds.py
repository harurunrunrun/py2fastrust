"""Proved native function variants retain Python scalar kinds and array aliases."""

import re
import shutil
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
import test_native_functions as helpers
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class FunctionKindTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeFunctionTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeFunctionTests.tearDownClass.__func__)
    compile = helpers.NativeFunctionTests.compile
    differential = helpers.NativeFunctionTests.differential
    run_source = test_runtime.RuntimeTests.run_source

    def test_same_definition_has_bool_and_integer_variants(self):
        source = '''
def identity(x):
 return x
def positive(x):
 return x>0
print(identity(7),identity(True),identity(False),identity(-2))
print(positive(3),positive(-1),positive(True),positive(False))
'''
        rust = try_generate_native(source, "variants.py", "i64")
        self.assertIsNotNone(rust)
        self.assertRegex(rust, r"fn native_function_0_int\(native_argument_0: NativeInt")
        self.assertRegex(rust, r"fn native_function_0_bool\(native_argument_0: bool")
        self.assertEqual(len(re.findall(r"fn native_function_0_", rust)), 2)
        result = transpile(source, TranspileOptions())
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "native")
        self.differential(source)

    def test_boolean_defaults_keywords_and_return_operators_keep_their_kind(self):
        self.differential('''
def choose(value=True,/,*,enabled=False):
 if enabled:
  return value & enabled
 return value | enabled
def negate(value):
 return not value
def advance(value=True):
 return value+1
print(choose(),choose(False,enabled=True),choose(True,enabled=True))
print(negate(3),negate(True),negate(False),advance(),advance(7))
''')

    def test_readonly_integer_arrays_are_borrowed_without_copying(self):
        source = '''
def total(xs,offset=0):
 result=offset
 for item in xs:
  result+=item
 return result
def pair(left,right):
 return total(left)+total(right)
values=[1,2,3]
print(total(values),total([4,5],7),pair(values,values))
values.append(9)
print(total(values),*values)
'''
        rust = try_generate_native(source, "arrays.py", "i64")
        self.assertIsNotNone(rust)
        self.assertIn("native_argument_0: &[NativeInt]", rust)
        self.assertNotIn(".clone()", rust[rust.index("fn native_function_"):])
        self.differential(source)

    def test_one_array_function_specializes_scalar_arguments_and_bool_results(self):
        self.differential('''
def matches(values,expected):
 return sum(values)==expected
def scaled(values,scale):
 return sum(values)*scale
print(matches([1,2],3),matches([],False),matches([1],True))
print(scaled([2,3],True),scaled([2,3],3),scaled([],False))
''')

    def test_all_arguments_evaluate_before_reordering_and_defaults_are_pure(self):
        self.differential('''
def mark(value):
 print(value)
 return value
def combine(a,/,b,*,c=True):
 print(c)
 return a+sum(b)+c
print(combine(mark(1),c=mark(False),b=[mark(2),mark(3)]))
print(combine(mark(True),[mark(4)],c=mark(True)))
def first(values,index):
 return values[index]
values=[8,9]
print(first(values,mark(1)))
''')

    def test_transitive_variants_and_late_defined_callees(self):
        source = '''
def first(x):
 return later(x)
def later(x):
 return x
def outer(values,flag):
 return first(flag)+sum(values)
print(first(True),first(3),outer([2,4],True),outer([],5))
'''
        self.differential(source)

    def test_function_variants_emit_union_helpers_and_keep_array_loop_tags(self):
        source = '''
def show(flag):
 if flag:value=True
 else:value=7
 print(value,value+1,value&True)
def rows(values,flag):
 result=0
 for value in values:
  if flag:result=True
  else:result=value
 print(result,result^False)
show(0)
show(True)
rows([2,3],True)
rows([],False)
rows([2,3],0)
'''
        rust = try_generate_native(source, "function_unions.py", "i64")
        self.assertIsNotNone(rust)
        self.assertIn("enum NativeScalar", rust)
        self.assertNotIn("enum Value", rust)
        self.assertIn("native_argument_0: &[NativeInt]", rust)
        self.differential(source)

    def test_array_bounds_and_argument_errors_keep_output_and_trace(self):
        self.differential('''
def item(values,index):
 print(len(values))
 return values[index]
print(7)
print(item([2,3],int(input())))
''', ("0\n", "-1\n", "5\n", "invalid\n"), trace=True)

    def test_fixed_width_bool_and_array_calls_use_the_same_integer_policy(self):
        self.differential('''
def calculate(values,flag,offset):
 total=offset+flag
 for value in values:
  total=(total*3+value)//-3
 return total
values=[2**64-1,2**127-1,-2**128]
print(calculate(values,True,2**127),calculate(values,False,2**64))
''', wrapping=True)

    def test_mutation_escaping_aliases_recursion_and_unknown_kinds_use_general_aot(self):
        programs = [
            "def f(xs):\n xs[0]=7\n return sum(xs)\na=[1]\nprint(f(a),a)",
            "def f(xs):\n xs[0]+=7\n return sum(xs)\na=[1]\nprint(f(a),a)",
            "def f(xs):\n xs.append(7)\n return sum(xs)\na=[1]\nprint(f(a),a)",
            "def f(xs):\n xs.sort()\n return sum(xs)\na=[2,1]\nprint(f(a),a)",
            "def f(xs):\n xs=[]\n return sum(xs)\nprint(f([1]))",
            "def f(xs):\n alias=xs\n return sum(alias)\nprint(f([1]))",
            "def f(xs): return xs\nprint(f([1]))",
            "def f(xs=[]): return len(xs)\nprint(f())",
            "def mutate(xs):\n xs.append(2)\n return sum(xs)\ndef f(xs): return mutate(xs)\nprint(f([1]))",
            "def f(x): return f(not x)\nprint(f(True))",
            "def f(x): return x\nprint(f(1j))",
            "def f(x):\n if x:return True\n return 3\nprint(f(1))",
            "def f(x): return later(x)\nprint(f(True))\ndef later(x):return x",
            "def f(xs): return sum(xs)\nrows=[[1,2]]\nprint(f(rows[0]))",
        ]
        for source in programs:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "fallback.py", "i64"))
        result = transpile(programs[0], TranspileOptions())
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "aot")

    def test_constant_default_metadata_cannot_hide_definition_effects_or_errors(self):
        cases = [
            ("def f(x=len([int(input())])):return x\nprint(int(input()))", "9\n8\n"),
            ("def f(x=not len([int(input())])):return x\nprint(f(),int(input()))", "9\n8\n"),
            ("print(3)\ndef f(x=len([1//0])):return x\nprint(7)", ""),
        ]
        for source, stdin in cases:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "default_effect.py", "i64"))
                result = transpile(source, TranspileOptions())
                self.assertTrue(result.success)
                self.assertEqual(result.backend, "aot")
                self.run_source(source, stdin=stdin)


if __name__ == "__main__":
    unittest.main()
