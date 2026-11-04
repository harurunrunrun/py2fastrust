"""Ordinary source selects positional metadata before lowering, without markers."""
import ast
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze,UNKNOWN
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_positional_selection import requires_frames
import test_native_lambda_callbacks as helpers

CASES={'record_unpack': ('record=[7,"label"]\n'
                   'number,label=record\n'
                   'print(number+1,label.upper())\n',
                   'def main():\n'
                   ' record=[7,"label"]\n'
                   ' number,label=record\n'
                   ' print(number+1,label.upper())\n'
                   '\n'
                   'if __name__=="__main__":main()\n'),
 'constant_slots': ('record=[4,"word"]\nprint(record[0]+3,record[-1].upper())\n',
                    'def main():\n'
                    ' record=[4,"word"]\n'
                    ' print(record[0]+3,record[-1].upper())\n'
                    '\n'
                    'if __name__=="__main__":main()\n'),
 'record_iteration': ('rows=[[2,"beta"],[1,"alpha"]]\n'
                      'for number,label in rows:print(number+1,label.upper())\n',
                      'def main():\n'
                      ' rows=[[2,"beta"],[1,"alpha"]]\n'
                      ' for number,label in rows:print(number+1,label.upper())\n'
                      '\n'
                      'if __name__=="__main__":main()\n'),
 'keyed_record_sort': ('rows=[[2,"beta"],[1,"alpha"]]\n'
                       'rows.sort(key=lambda row:row[0])\n'
                       'for number,label in rows:print(number+1,label.upper())\n',
                       'def main():\n'
                       ' rows=[[2,"beta"],[1,"alpha"]]\n'
                       ' rows.sort(key=lambda row:row[0])\n'
                       ' for number,label in rows:print(number+1,label.upper())\n'
                       '\n'
                       'if __name__=="__main__":main()\n'),
 'record_alias': ('record=[3,"alias"]\n'
                  'other=record\n'
                  'number,label=other\n'
                  'print(number*2,label.upper())\n',
                  'def main():\n'
                  ' record=[3,"alias"]\n'
                  ' other=record\n'
                  ' number,label=other\n'
                  ' print(number*2,label.upper())\n'
                  '\n'
                  'if __name__=="__main__":main()\n'),
 'uniform_nested_iteration': ('rows=[[1,2],[3,4]]\n'
                              'for first,second in rows:print(first+second)\n',
                              'def main():\n'
                              ' rows=[[1,2],[3,4]]\n'
                              ' for first,second in rows:print(first+second)\n'
                              '\n'
                              'if __name__=="__main__":main()\n')}
CONTROLS={'heterogeneous_print_only': 'record=[7,"label"]\nprint(record)\n',
 'heterogeneous_length_only': 'record=[7,"label"]\nprint(len(record))\n',
 'heterogeneous_unused': 'record=[7,"label"]\nprint(3+4)\n',
 'ordinary_uniform_lists': 'values=[3,1,2]\nvalues.sort()\nprint(sum(values),values)\n',
 'ordinary_io_dp': 'n=int(input())\n'
                   'values=list(map(int,input().split()))\n'
                   'dp=[0]*(n+1)\n'
                   'for i in range(n):dp[i+1]=dp[i]+values[i]\n'
                   'print(dp[n])\n',
 'list_alias_mutation': 'values=[1,2]\nother=values\nother.append(3)\nprint(values)\n'}

class PositionalSelectionProofTests(unittest.TestCase):
    def test_original_ast_and_source_are_unchanged(self):
        for sources in CASES.values():
            for source in sources:
                unit=build_program(source,"record.py").main;before=ast.dump(unit.tree,include_attributes=True)
                self.assertFalse(any(isinstance(n,ast.ClassDef)for n in ast.walk(unit.tree)))
                selected=select_frames(unit)
                self.assertTrue(selected.required)
                self.assertIn("fixed list record positional constraints",selected.reasons)
                self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
                unit.check_identity(source,"record.py")

    def test_unused_or_printed_heterogeneous_literals_do_not_select_globally(self):
        for source in CONTROLS.values():
            unit=build_program(source,"control.py").main;analysis=analyze(unit)
            self.assertFalse(requires_frames(unit,analysis))
            self.assertNotIn("fixed list record positional constraints",select_frames(unit).reasons)

    def test_unreached_literal_and_consumer_do_not_select(self):
        source='def unused():\n record=[1,"x"]\n a,b=record\n print(a+1,b.upper())\nprint(7)\n'
        unit=build_program(source,"unreached.py").main
        self.assertFalse(requires_frames(unit,analyze(unit)))

    def test_solved_heap_is_read_only(self):
        unit=build_program(CASES["record_alias"][0],"heap.py").main;analysis=analyze(unit)
        self.assertTrue(analysis.heap)
        key=next(iter(analysis.heap))
        with self.assertRaises(TypeError):analysis.heap[key]=UNKNOWN

    def test_selected_failure_does_not_retry_emitters(self):
        source=CASES["record_unpack"][0]
        for integer in ("i64","i128","bigint"):
            with patch("py2fastrust.native_classes.try_generate_classes",return_value=None)as selected,patch("py2fastrust.native_scalar.ScalarGenerator.statements",side_effect=AssertionError("ordinary retry")),patch("py2fastrust.native_bigint.try_generate_bigint",side_effect=AssertionError("BigInt retry")),patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM retry")):
                result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertEqual(selected.call_count,1)
            self.assertEqual(result.diagnostics[0].code,"E006")

    def test_homogeneous_scalar_path_remains_selected(self):
        source=CONTROLS["ordinary_uniform_lists"]
        with patch("py2fastrust.native_classes.try_generate_classes",side_effect=AssertionError("unneeded frame route")):
            self.assertTrue(transpile(source).success)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class PositionalSelectionExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

def install(name):
    def test(self):
        for source in CASES[name]:self.exercise(source)
    test.__name__="test_"+name
    setattr(PositionalSelectionExecutionTests,test.__name__,test)
for name in CASES:install(name)
