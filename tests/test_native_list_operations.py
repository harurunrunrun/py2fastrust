"""Compositional list operators retain values, evaluation order and width rules."""

import shutil
import random
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_list_operations as operators
import test_native_integer_methods as _integers


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeListOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = _integers.NativeIntegerMethodTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.harness.tearDownClass()

    def compare(self, source, inputs=("",), *, string_mode="ascii"):
        for mode in ("i64", "i128", "bigint"):
            for release in (False, True):
                binary, _ = self.harness.compile(source, mode, release, string_mode=string_mode)
                for data in inputs:
                    with self.subTest(mode=mode, release=release, data=data):
                        self.harness.compare(binary, source, mode, data)

    def test_concat_repeat_and_nested_operators_produce_independent_integer_lists(self):
        self.compare('''a=[1,2]
b=[3,4]
c=(a+b)*2
d=3*a+b
c[0]=99
d.append(7)
print(a,b,c,d,(a*0)+b,False*a,a*True)
''')

    def test_bool_and_tuple_elements_keep_their_original_tags(self):
        self.compare('''a=[True,False]
b=[1,2]
c=a+b
d=b+a
c.append(True)
print(a,b,c,d,a*3,2*a)
x=[(True,"猫")]
y=[(3,"海")]
z=x+y
z[0]=(False,"x")
print(x,y,z,2*x,x*False)
''', string_mode="unicode")

    def test_empty_operands_and_unicode_strings_keep_list_copy_semantics(self):
        self.compare('''a=["a","猫"]
b=[]+a
c=a+[]
d=(a+[])*2
b[0]="changed"
c.append("海")
print(a,b,c,d,[]+[],a*-3,False*a)
''', string_mode="unicode")

    def test_source_effects_and_readonly_function_arguments_are_ordered(self):
        self.compare('''def mark(n):
 print(n,end="|")
 return int(input())
def process(values,n):
 combined=values+values
 repeated=values*n
 print(combined,repeated,values)
 return sum(combined)
a=[mark(1),mark(2)]
b=a+[mark(3)]
c=a*mark(4)
d=mark(5)*[mark(6)]
print(a,b,c,d,process(a,2))
''', ("2\n3\n4\n2\n3\n9\n", "2\nbad\n", "2\n3\n4\n", "2\n3\n4\n0\n-2\n9\n"))

    def test_repeat_checks_index_width_even_for_an_empty_list(self):
        for expression in ("empty*int(input())", "int(input())*empty"):
            source = f"print(9)\nempty=[]\nanswer={expression}\nprint(answer,empty)\n"
            values = [0,-1,2**63-1,2**63,-2**63-1,2**127,-2**200,2**200]
            self.compare(source, tuple(str(value)+"\n" for value in values))

    def test_repeat_capacity_is_checked_before_allocation(self):
        self.compare("a=[1,2]\nprint(9)\nb=a*int(input())\nprint(a,b)\n",
                     ("-3\n", "0\n", "2\n", str(2**63-1)+"\n"))

    def test_all_modes_consume_the_same_semantic_operator_plan(self):
        source = "a=[True,False]\nb=[1,2]\nprint(a+b,3*a)\n"
        real = operators.plan_binary
        for mode in ("i64", "i128", "bigint"):
            with patch.object(operators, "plan_binary", side_effect=real) as planner:
                result = transpile(source, TranspileOptions(integer=mode))
                self.assertTrue(result.success, result.diagnostics)
                plans = [real(*call.args, **call.kwargs) for call in planner.call_args_list]
                self.assertTrue({"concat", "repeat"} <= {plan.operation for plan in plans if plan is not None})

    def test_preexisting_boolean_list_reduction_keeps_compile_and_run_coverage(self):
        self.compare("A=[True,False]\nprint(sum(A))\n")

    def test_seeded_compositions_of_literal_and_variable_operands(self):
        rng = random.Random(70291)
        lines = []
        for _ in range(40):
            domain = rng.choice((0,1,2))
            def value():
                number = rng.choice((True,False,-2,-1,0,1,2,2**64+3,-2**128-7))
                if domain == 0:
                    return number
                text = rng.choice(("", "a", "猫", "海\\'\n", "\x00"))
                return text if domain == 1 else (number,text)
            left = [value() for _ in range(rng.randrange(5))]
            right = [value() for _ in range(rng.randrange(5))]
            count = rng.randrange(-3,5)
            lines.extend((f"left={left!r}", f"right={right!r}",
                          "combined=left+right", f"repeated={count}*combined",
                          f"print(combined,repeated,left,right,({left!r}+right)*{count})"))
        self.compare("\n".join(lines)+"\n", string_mode="unicode")


if __name__ == "__main__":
    unittest.main()
