"""A representation transfer cannot consume a vector with a live iterator."""
import shutil
import unittest
from py2fastrust.native import _Expression
from py2fastrust.native_tuples import coerce_structural
from py2fastrust.native_types import EMPTY,ListType
from py2fastrust import transpile,TranspileOptions
from tests import test_native_lexical_closures as lexical


SOURCES = (
    ('a=[1]\nfor i in range(1):\n a=[]\nfor x in a:\n pass\nprint(x)\n', ('',)),
    ('a=[7]\nfor i in range(int(input())):\n a=[]\nfor value in a:\n pass\nprint(value)\n', ('0\n','1\n','3\n')),
    ('def empty():\n print("source")\n return []\na=empty()\nfor value in a:\n pass\nprint("done")\n', ('',)),
    ('a=[1]\nalias=a\nfor i in range(1):\n a=[]\nfor value in alias:\n pass\nprint(value,a,alias is a)\n', ('',)),
    ('a=[]\nfor i in range(2):\n if i:a.append(9)\n for value in a:\n  print(value)\nprint(a)\n', ('',)),
)


class EmptyTransferContracts(unittest.TestCase):
    def test_shared_empty_handle_does_not_silently_copy_into_a_new_layout(self):
        # This unchanged source is not implemented yet. The new private-vector
        # conversion must not turn it into an identity-breaking contents copy.
        for mode in ('i64','i128','bigint'):
            result=transpile(SOURCES[3][0],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertIsNone(result.rust_source)
            self.assertTrue(result.diagnostics)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('shared list layout and identity',result.diagnostics[0].message)

    def test_uninhabited_private_element_type_keeps_one_checked_source_evaluation(self):
        result=coerce_structural(_Expression('read_effect()',ListType(EMPTY)),ListType('int'),None)
        self.assertEqual(result.count('read_effect()'),1)
        self.assertNotIn('.into_iter()',result)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class EmptyTransferExecution(unittest.TestCase):
    compare=lexical.LexicalClosureExecutionTests.compare

    def test_original_zero_iteration_and_rebinding_programs(self):
        for source,inputs in SOURCES[:3]+SOURCES[4:]:
            with self.subTest(source=source):
                self.compare(source,inputs,require_environment=False)


if __name__=='__main__':
    unittest.main()
