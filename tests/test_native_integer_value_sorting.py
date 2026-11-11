"""Integer value sorting keeps keys and observable identity on stable paths."""
import shutil
import unittest

from py2fastrust import transpile,TranspileOptions
import test_native_mapping_mutations as execution


class IntegerSortSelection(unittest.TestCase):
    def convert(self,source):
        result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        return result.rust_source

    def test_unobserved_equal_integer_values_need_no_stable_order(self):
        source=self.convert('a=[3,1,3,2,1]\na.sort()\nprint(a)\n')
        self.assertIn('.sort_unstable_by(',source)

    def test_identity_queries_and_computed_keys_keep_stable_sorting(self):
        for source in ('marker=None\na=[3,1,3]\na.sort()\nprint(marker is None,a)\n',
                'a=[(2,0),(1,1),(2,2),(1,3)]\na.sort(key=lambda row:row[0])\nprint(a)\n'):
            with self.subTest(source=source):
                self.assertNotIn('.sort_unstable_by(',self.convert(source))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IntegerSortExecution(unittest.TestCase):
    compare=execution.NativeMappingMutationTests.compare

    def test_duplicates_negative_values_and_reverse_in_all_integer_modes(self):
        self.compare('''a=[7,-2,7,0,-2,8,-9,0,1]
a.sort()
print(a)
a.sort(reverse=True)
print(a)
''')

    def test_equal_keys_retain_the_original_element_order(self):
        self.compare('''a=[(2,0),(1,1),(2,2),(1,3),(2,4)]
a.sort(key=lambda row:row[0])
print(a)
a.sort(key=lambda row:row[0],reverse=True)
print(a)
''')


if __name__=='__main__':
    unittest.main()
