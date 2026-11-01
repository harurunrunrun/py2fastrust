"""Independent temporary values must never inherit another cell's facts."""
import gc
import shutil
import unittest

from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,Cell,shape
import test_native_module_linking as support


class TemporaryCellIdentityTests(unittest.TestCase):
    def test_discarded_temporary_values_keep_independent_type_facts(self):
        unit=build_program('value=0\n','isolation.py').main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit)
        node=unit.tree.body[0]
        for index in range(4096):
            kind=('str','bool','int','none','bytes')[index%5]
            destination=Cell()
            model.contribute(destination,Cell(kind),node)
            self.assertEqual(shape(destination),kind,(index,kind,shape(destination)))
            if index%64==0:gc.collect()

    def test_live_allocation_members_keep_their_own_constraints(self):
        unit=build_program('a=[1]\nb=["x"]\n','allocations.py').main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        first,second=unit.tree.body
        a=model.records[(0,id(first.value))]
        b=model.records[(0,id(second.value))]
        self.assertEqual(shape(a).element,'int')
        self.assertEqual(shape(b).element,'str')
        for index in range(512):
            temporary=Cell()
            model.contribute(temporary,Cell('bytes'if index%2 else'none'),first)
        self.assertEqual(shape(a).element,'int')
        self.assertEqual(shape(b).element,'str')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TemporaryCellExecutionTests(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise

    def test_reused_comprehension_targets_keep_each_assignment_type(self):
        self.exercise({'main.py':'''class Marker:pass
x=99
print([x for x in range(3) if x>0 for x in ('a','b')],x)
print([str(x) for x in range(3) for x in (True,False) if x],x)
'''})

    def test_separate_tuple_producers_keep_their_actual_payload_types(self):
        self.exercise({'main.py':'''class Marker:pass
outside='outer'
print([item for item in (1,2,3)])
print([item for item in ('a','b')])
print([item for item in (True,False)])
print([item for item in (None,None)])
print([item for item in (b'a',b'b')])
print([[item for item in (False,True)]for item in ('a','b')])
print(outside)
'''})


if __name__=='__main__':unittest.main()
