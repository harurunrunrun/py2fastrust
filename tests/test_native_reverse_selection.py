"""Select range reversal using shared capability facts and integer width."""
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_module_linking import needs_linking
import test_native_union_ordering as helpers

SOURCE='''span=range
def upper():
 print("upper")
 return 7
print(list(reversed(span(-4,upper()))))
print(list(reversed(span(7,-4,-1))))
print(list(reversed(span(-4,7,3-2))))
'''
MODULE_SOURCE='''from collections import deque
queue=deque([1,2])
print(sum(reversed(range(1,5))),queue)
'''

class NativeReverseSelectionProofTests(unittest.TestCase):
    def test_proved_unit_steps_and_canonical_aliases_keep_fixed_direct_emission(self):
        unit=build_program(SOURCE,'reverse.py').main
        for mode in('i64','i128'):
            with self.subTest(mode=mode):
                self.assertFalse(select_frames(unit,integer=mode).required)
                with patch('py2fastrust.native_classes.try_generate_classes',side_effect=AssertionError('proved fixed-width range redirected')):
                    result=transpile(SOURCE,TranspileOptions(integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                self.assertNotIn('struct ClassScope',result.rust_source)
    def test_bigint_and_general_steps_select_the_native_reverse_provider(self):
        unit=build_program(SOURCE,'reverse.py').main
        self.assertTrue(select_frames(unit,integer='bigint').required)
        for mode in('i64','i128','bigint'):
            general=build_program('print(list(reversed(range(2,13,3))))','general.py').main
            self.assertTrue(select_frames(general,integer=mode).required)
    def test_module_admission_receives_the_selected_integer_mode(self):
        program=build_program(MODULE_SOURCE,'module_reverse.py')
        self.assertFalse(needs_linking(program,integer='i64'))
        self.assertFalse(needs_linking(program,integer='i128'))
        self.assertTrue(needs_linking(program,integer='bigint'))

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeReverseSelectionExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise
    def test_range_operands_run_once_before_reversal_in_every_mode(self):self.exercise(SOURCE,('',))
    def test_linked_member_admission_and_direct_mode_results_agree(self):self.exercise(MODULE_SOURCE,('',))

if __name__=='__main__':unittest.main()
