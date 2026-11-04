"""Literal provenance can select positional analysis before a coarse ABI is solved."""
import ast
import shutil
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_positional_selection import requires_frames
import test_native_iterator_reductions as _execution

SOURCES={'list_alias': 'def main():\n'
               ' record=[1,"alias"]\n'
               ' other=record\n'
               ' other[0]+=4\n'
               ' print(record[0],other[1],record is other)\n'
               'main()\n',
 'local_compatible_stores': 'def rhs():\n'
                            ' print("rhs")\n'
                            ' return 9\n'
                            'def main():\n'
                            ' record=[7,"label"]\n'
                            ' record[0]=rhs()\n'
                            ' record[-1]=record[-1].upper()\n'
                            ' record[0]+=3\n'
                            ' print(record[0],record[1])\n'
                            'main()\n'}
CONTROLS={'heterogeneous_length_only_module': 'record=[7,"label"]\nprint(len(record))\n',
 'heterogeneous_print_only_module': 'record=[7,"label"]\nprint(record)\n',
 'heterogeneous_unused_module': 'record=[7,"label"]\nprint(3+4)\n',
 'list_alias_mutation_module': 'values=[1,2]\nother=values\nother.append(3)\nprint(values)\n',
 'ordinary_io_dp_module': 'n=int(input())\n'
                          'values=list(map(int,input().split()))\n'
                          'dp=[0]*(n+1)\n'
                          'for i in range(n):dp[i+1]=dp[i]+values[i]\n'
                          'print(dp[n])\n',
 'ordinary_uniform_lists_module': 'values=[3,1,2]\nvalues.sort()\nprint(sum(values),values)\n'}
NESTED_EXCLUDED='def main():\n row=[1]\n record=[row,"child"]\n other=record[0]\n other[0]=8\n print(row[0],record[0][0],record[1])\nmain()\n'


class UnresolvedAllocationSelectionTests(unittest.TestCase):
    def test_real_unresolved_aggregate_retains_known_literal_children(self):
        for name,source in SOURCES.items():
            unit=build_program(source,'record.py').main;before=ast.dump(unit.tree,include_attributes=True)
            facts=analyze(unit);nodes={unit.ordinal(n):n for n in ast.walk(unit.tree)}
            unresolved=[]
            for scope in facts.scopes.values():
                for site,kind in scope.allocations.items():
                    node=nodes.get(site)
                    if isinstance(node,ast.List)and kind is None:
                        unresolved.append(tuple(scope.expressions.get(unit.ordinal(child))for child in node.elts))
            self.assertIn(('int','str'),unresolved,name)
            self.assertTrue(requires_frames(unit,facts),name)
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
            unit.check_identity(source,'record.py')

    def test_selector_chooses_the_typed_path_before_emission_in_all_modes(self):
        for source in SOURCES.values():
            for integer in ('i64','i128','bigint'):
                selection=select_frames(build_program(source,'record.py').main,integer=integer)
                self.assertTrue(selection.required)
                self.assertIn('fixed list record positional constraints',selection.reasons)

    def test_existing_ordinary_controls_do_not_gain_positional_selection(self):
        for name,source in CONTROLS.items():
            unit=build_program(source,'control.py').main
            self.assertFalse(requires_frames(unit,analyze(unit)),name)
            self.assertNotIn('fixed list record positional constraints',select_frames(unit).reasons)

    def test_typed_model_still_rejects_unproved_correlated_mutable_leaf_write(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(NESTED_EXCLUDED,TranspileOptions(integer=mode,filename='nested.py'))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('per-alternative',result.diagnostics[0].message)
            self.assertIn('write',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class UnresolvedAllocationExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=_execution.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def check(self,name):
        source=SOURCES[name]
        for mode in ('i64','i128','bigint'):
            for release in (False,True):
                compiled=self.harness.compile(source,mode,release=release)
                self.harness.compare(compiled,mode=mode,trace=True)

    def test_compatible_slot_stores_rhs_and_augmented_update(self):self.check('local_compatible_stores')

    def test_shared_list_alias_mutation_and_identity(self):self.check('list_alias')


if __name__=='__main__':unittest.main()
