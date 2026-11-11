"""Immediate view loans preserve canonical consumers and escaped identities."""
import shutil
import unittest

from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_class_capabilities import mapping_handles
import test_native_mapping_mutations as mutations


class MappingViewConsumerSelection(unittest.TestCase):
    def shared(self, source):
        unit=build_program(source,'view_consumer.py').main
        return mapping_handles(unit,select_frames(unit,integer='i64').analysis)

    def test_actual_list_and_integer_sum_consumers_can_borrow_an_owned_dictionary(self):
        for tail in ('print(list(d.keys()))', 'print(list(d.items()))',
                'print(list(d.values()))', 'print(sum(d.values()))',
                'collect=list\nprint(collect(d.values()))'):
            with self.subTest(tail=tail):
                self.assertFalse(self.shared('d={1:2,3:4}\n'+tail+'\n'))

    def test_saved_views_mutable_elements_and_other_arguments_keep_shared_storage(self):
        for source in ('d={1:2}\nv=d.values()\nprint(list(v))\n',
                'd={1:[2]}\nprint(list(d.values()))\n',
                'd={1:2}\nprint(sum(d.values(),3))\n',
                'd={1:2}\nprint(list(d.values(),3))\n',
                'def collect(value):return list(value)\nd={1:2}\nprint(collect(d.values()))\n'):
            with self.subTest(source=source):
                self.assertTrue(self.shared(source))

    def test_richer_queries_and_escaped_owners_keep_the_existing_program_representation(self):
        for source in ('d={1:2}\nprint(sum(d.values()),d.get(1))\n',
                'd={1:2}\nprint(sum(d.values()),d.get(1.0,0))\n',
                'd={1:2}\nother={2:3}\nprint(sum(d.values()),other.get(2))\n',
                'd={1:2}\nprint(sum(d.values()),d.copy())\n',
                'd={1:2}\nbox=[d]\nprint(sum(d.values()),box)\n'):
            with self.subTest(source=source):
                self.assertTrue(self.shared(source))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MappingViewConsumerExecution(unittest.TestCase):
    compare=mutations.NativeMappingMutationTests.compare

    def test_later_start_effect_and_mutable_view_elements_keep_their_original_owner(self):
        for source in ('''d={1:2}
def mark():
 d[1]=7
 return 3
print(sum(d.values(),mark()))
''', '''d={1:[2]}
values=list(d.values())
values[0].append(3)
print(d[1],values)
'''):
            with self.subTest(source=source):
                self.compare(source)

    def test_other_mapping_operations_keep_the_original_query_protocol(self):
        self.compare('d={1:2}\nother={2:3}\nprint(sum(d.values()),d.get(1),other.get(2))\n')

    def test_shallow_copy_keeps_the_existing_mapping_representation(self):
        self.compare('d={1:2}\nprint(sum(d.values()))\nother=d.copy()\nother[1]=7\nprint(d,other)\n')


if __name__=='__main__':
    unittest.main()
