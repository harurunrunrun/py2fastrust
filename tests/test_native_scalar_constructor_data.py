"""Stack initialization preserves source effects, aliasing and failure frames."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_scalar_constructor_data as data
import test_native_shared_scalar_fields as shared_tests
import test_native_source_state as state_tests


SOURCES={
    'effects_and_failure': '''events = []
class Number:
    def __init__(self, value):
        events.append(value)
        print("initialize", value)
        self.base = 17
        self.value = 20 // value
    def change(self):
        self.value += 1
def calculate(value):
    item = Number(value)
    alias = item
    alias.change()
    print(item.base, item.value, alias is item, events)
calculate(int(input()))
''',
    'mapped_aliases':shared_tests.SOURCES['map_aliases'],
    'partly_initialized_escape':shared_tests.SOURCES['partly_initialized_escape'],
    'missing_branch':shared_tests.SOURCES['missing_branch'],
}


def convert(source,mode='i64',**options):
    models=[]
    original=data.prepare
    def prepare(model):
        original(model)
        models.append(model)
    with patch.object(data,'prepare',prepare):
        result=transpile(source,TranspileOptions(integer=mode,license='none',**options))
    return result,models[-1]if models else None


class NativeScalarConstructorDataTests(unittest.TestCase):
    def test_sealed_shared_initialization_uses_data_before_rc_allocation(self):
        for name in ('effects_and_failure','mapped_aliases'):
            for mode in ('i64','i128'):
                with self.subTest(name=name,mode=mode):
                    result,model=convert(SOURCES[name],mode,optimize=False)
                    self.assertTrue(result.success,result.diagnostics)
                    owner=next(owner for owner in model.classes.values()if owner.node.name=='Number')
                    self.assertIn(owner.index,model.scalar_constructor_data.owners)
                    self.assertTrue('class_build_'+str(owner.index)+'('in result.rust_source)
                    self.assertTrue('->ClassResult<ClassData_'+str(owner.index)+'>'in result.rust_source)

    def test_unproved_partial_and_published_receivers_keep_existing_storage(self):
        for name in ('partly_initialized_escape','missing_branch'):
            result,model=convert(SOURCES[name])
            self.assertTrue(result.success,result.diagnostics)
            self.assertFalse(model.scalar_constructor_data.owners)

    def test_original_execution_and_errors_in_all_widths_and_build_modes(self):
        with patch.dict(state_tests.SOURCES,SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    inputs=('4\n','0\n')if name=='effects_and_failure'else('',)
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,inputs)


if __name__=='__main__':
    unittest.main()
