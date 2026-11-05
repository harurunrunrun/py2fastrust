"""Dynamic builtin-list unpacking selects ordered native binding before emission."""
import ast
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze
from py2fastrust.native_class_unpacking import requires_frames
from py2fastrust.native_frame_selection import select_frames
import test_native_lambda_callbacks as helpers

CASES={'input_edges': ['def main():\n'
                 '    n = int(input())\n'
                 '    rows = [list(map(int, input().split())) for _ in range(n)]\n'
                 '    total = 0\n'
                 '    for left, right, weight in rows:\n'
                 '        total += (right - left) * weight\n'
                 '    print(total)\n'
                 'main()\n',
                 ['3\n0 1 7\n1 2 4\n0 2 20\n', '0\n', '1\n1 2\n', '1\n1 2 3 4\n']],
 'input_comprehension': ['def main():\n'
                         '    rows = [list(map(int, input().split())) for _ in range(2)]\n'
                         '    answers = [left * 10 + right for left, right in rows]\n'
                         '    print(answers)\n'
                         'main()\n',
                         ['2 3\n4 5\n', '2 3\n4\n', '2 3\n4 5 6\n']],
 'aliased_rows_mutation': ['def main():\n'
                           '    row = list(map(int, input().split()))\n'
                           '    rows = [row, row]\n'
                           '    total = 0\n'
                           '    for left, right in rows:\n'
                           '        total += left + right\n'
                           '        row[0] += 1\n'
                           '    print(total, row[0], rows[0] is rows[1])\n'
                           'main()\n',
                           ['2 5\n']],
 'enumerated_rows': ['def main():\n'
                     '    rows = [list(map(int, input().split())) for _ in range(2)]\n'
                     '    for index, (left, right) in enumerate(rows, 5):\n'
                     '        print(index, left - right)\n'
                     'main()\n',
                     ['9 2\n7 3\n', '9 2\n7\n']],
 'nested_partial_target': ['def main():\n'
                           '    bucket = [0]\n'
                           '    def receiver():\n'
                           '        print("target")\n'
                           '        return bucket\n'
                           '    rows = [(1, list(map(int, input().split())))]\n'
                           '    for receiver()[0], (left, right) in rows:\n'
                           '        print(bucket[0], left, right)\n'
                           'main()\n',
                           ['4 6\n', '4\n', '4 6 8\n']],
 'bytes_input_rows': ['import sys\n'
                      'def main():\n'
                      '    n = int(sys.stdin.buffer.readline())\n'
                      '    rows = [list(map(int, sys.stdin.buffer.readline().split())) for _ '
                      'in range(n)]\n'
                      '    for left, right in rows:\n'
                      '        print(left * right)\n'
                      'main()\n',
                      ['2\n3 7\n4 8\n']]}

class DynamicListUnpackProofTests(unittest.TestCase):
    def test_reached_allocation_facts_select_without_source_rewriting(self):
        for name,(source,inputs)in CASES.items():
            unit=build_program(source,"rows.py").main
            before=ast.dump(unit.tree,include_attributes=True)
            self.assertTrue(requires_frames(unit,analyze(unit)),name)
            self.assertTrue(select_frames(unit).required,name)
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
            unit.check_identity(source,"rows.py")

    def test_unreached_or_non_unpacking_lists_do_not_select(self):
        controls=(
            "def unused():\n rows=[list(map(int,input().split()))for _ in range(2)]\n for a,b in rows:print(a+b)\nprint(7)\n",
            "def main():\n rows=[[0]*4 for _ in range(3)]\n rows[1][2]=5\n print(rows[1][2])\nmain()\n",
            "values=[1,2]\nfor value in values:print(value)\n",
            "a,b=[1,2]\nprint(a,b)\n",
            "a,b=list(range(2))\nprint(a,b)\n",
            "a,b=list(map(int,input().split()))\nprint(a+b)\n",
            "a,(b,c)=(1,(2,3))\nprint(a,b,c)\n",
        )
        for source in controls:
            unit=build_program(source,"control.py").main
            self.assertFalse(requires_frames(unit,analyze(unit)))

    def test_selected_failure_never_retries_another_emitter(self):
        source=CASES["input_edges"][0]
        for integer in ("i64","i128","bigint"):
            with patch("py2fastrust.native_classes.try_generate_classes",return_value=None)as chosen,patch("py2fastrust.native_scalar.ScalarGenerator.statements",side_effect=AssertionError("ordinary retry")),patch("py2fastrust.native_bigint.try_generate_bigint",side_effect=AssertionError("BigInt retry")),patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM retry")):
                result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertEqual(chosen.call_count,1)
            self.assertEqual(result.diagnostics[0].code,"E006")

class DynamicListUnpackExecution(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

def _test(source,inputs):
    def test(self):self.exercise(source,inputs)
    return test
for _name,(_source,_inputs)in CASES.items():
    setattr(DynamicListUnpackExecution,"test_"+_name,_test(_source,_inputs))

if __name__=="__main__":unittest.main()
