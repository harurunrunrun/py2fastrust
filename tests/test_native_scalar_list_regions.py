"""Shared instance arrays get one Vec loan only without reentrant access."""
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_scalar_list_regions as regions
import test_native_source_state as state_tests
from test_native_scalar_data_locals import PREFIX,SOURCE


READ_ALIAS=PREFIX+'''shared = []
def observe(value):
    return shared[0].value + value.value
def run(items):
    for i in range(len(items)):
        left = items[i]
        items[i] = Number(observe(left))
shared = [Number(2), Number(3)]
run(shared)
print([item.value for item in shared])
'''

RESIZE_ALIAS=PREFIX+'''shared = [Number(0)]
def update(value):
    shared.append(Number(value.value + 10))
    return value.value
def run(items):
    for i in range(2):
        left = items[i]
        items[i] = Number(update(left))
shared = [Number(2), Number(3)]
run(shared)
print([item.value for item in shared])
'''

TWO_ROOTS=PREFIX+'''def run(items, other):
    for i in range(len(items)):
        items[i] = items[i] + other[i]
items = [Number(2), Number(3)]
run(items, items)
print([item.value for item in items])
'''


class NativeScalarListRegionTests(unittest.TestCase):
    def test_scalar_data_loop_uses_one_mutable_vec_lease(self):
        result=transpile(SOURCE,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertRegex(result.rust_source,r'class_slice_set_data_\d+\(&mut class_temp')

    def test_source_callees_that_access_a_possible_alias_decline_the_lease(self):
        for source in (READ_ALIAS,RESIZE_ALIAS,TWO_ROOTS):
            selected=[];original=regions.select
            def select(emitter,node):
                proof=original(emitter,node)
                if proof is not None and(not proof.mutable or len(proof.roots)==1):selected.append(proof)
                return proof
            with patch.object(regions,'select',select):
                result=transpile(source,TranspileOptions(license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertFalse(selected)

    def test_aliases_reentrant_reads_and_resizing_remain_correct(self):
        sources={'scalar_region_data':SOURCE,'scalar_region_alias':READ_ALIAS,
                 'scalar_region_resize':RESIZE_ALIAS,'scalar_region_two_roots':TWO_ROOTS}
        with patch.dict(state_tests.SOURCES,sources):
            for name in sources:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,('',))


if __name__=='__main__':unittest.main()
