"""Readonly cursor consumers never conceal source callback heap effects."""
from types import SimpleNamespace
import ast
import unittest
from unittest.mock import patch

from py2fastrust.native_source_native_effects import readonly_pull
from py2fastrust.native_class_iterators import IteratorRecord
from py2fastrust.native_aot_callables import AotFunctionType
from py2fastrust.native_classes import Cell, InstanceType
from py2fastrust.native_types import TupleType
from py2fastrust.references import BuiltinIdentity
import test_native_shared_scalar_fields as shared_tests
import test_native_source_state as state_tests


SOURCE = '''class Number:
    def __init__(self, value):
        self.modulus = 101
        self.value = value
    def __iadd__(self, other):
        self.value += other.value
        return self
items = list(map(Number, [32, 59]))
alias = items[0]
alias += items[1]
print(" ".join(map(str, [alias.value, items[0].value, items[1].value])))
print(alias.modulus, items[1].modulus)
'''

CALLBACK = '''class Stack:
    items = []
    def __init__(self, value):
        self.value = value
    def __enter__(self):
        self.items.append(self.value)
    def __exit__(self, kind, error, trace):
        self.items.pop()
    @classmethod
    def current(cls):
        return cls.items[-1]
def stringify(value):
    Stack.items.append(47)
    return str(value)
with Stack(31):
    print("|".join(map(stringify, [1, 2])), Stack.current())
'''

CONTEXT_PREFIX=CALLBACK.split('def stringify',1)[0]+'''class Number:
    def __init__(self, value):
        self.modulus = Stack.current()
        self.value = value
'''
CONTEXT_CACHE=CONTEXT_PREFIX+'''cache = {}
with Stack(101):
    cache[1] = [3, 5]
    cache[2] = [7]
    number = Number(11)
    print(" ".join(map(str, [number.modulus, number.value])))
'''
CONTEXT_ALIAS=CONTEXT_PREFIX+'''cache = {1: Stack.items}
with Stack(101):
    cache[1].append(103)
    number = Number(11)
    print(number.modulus, number.value)
'''


class NativeReadonlyPullConstantTests(unittest.TestCase):
    def test_tuple_container_cannot_hide_a_custom_len_element_protocol(self):
        # len(tuple) is native, but map(len, tuple) calls len on each element.
        callback=Cell(AotFunctionType((),(BuiltinIdentity('len'),)))
        record=IteratorRecord(0,'map',ast.parse('map(len, values)',mode='eval').body,
                              None,Cell(),Cell('int'),callback=callback,
                              input_types=(TupleType((InstanceType('Custom'), 'str')),))
        model=SimpleNamespace(iterators=SimpleNamespace(owns=lambda kind:kind.record is record))
        self.assertFalse(readonly_pull(model,record.kind))

    def test_mutating_operator_keeps_a_separately_proved_constant_field(self):
        for mode in ('i64','i128'):
            result,model=shared_tests.convert(SOURCE,mode)
            self.assertTrue(result.success,result.diagnostics)
            self.assertIsNone(model.scalar_heap_constants.reason)
            owner=next(owner for owner in model.classes.values()if owner.node.name=='Number')
            index=list(owner.fields).index('modulus')
            self.assertIn((owner.index,index),model.constant_field_projection.fields)

    def test_dictionary_rebinding_does_not_poison_a_disjoint_context_list(self):
        result,model=shared_tests.convert(CONTEXT_CACHE)
        self.assertTrue(result.success,result.diagnostics)
        self.assertIsNone(model.scalar_heap_constants.reason)
        owner=next(owner for owner in model.classes.values()if owner.node.name=='Number')
        index=list(owner.fields).index('modulus')
        self.assertIn((owner.index,index),model.constant_field_projection.fields)

    def test_a_retrieved_dictionary_list_alias_still_contributes_writes(self):
        result,model=shared_tests.convert(CONTEXT_ALIAS)
        self.assertTrue(result.success,result.diagnostics)
        owner=next(owner for owner in model.classes.values()if owner.node.name=='Number')
        index=list(owner.fields).index('modulus')
        self.assertNotIn((owner.index,index),model.constant_field_projection.fields)

    def test_alias_mutation_and_real_mapper_side_effects_match_python(self):
        sources={'constant_inplace':SOURCE,'effectful_join':CALLBACK,
                 'context_cache':CONTEXT_CACHE,'context_alias':CONTEXT_ALIAS}
        with patch.dict(state_tests.SOURCES,sources):
            for name in sources:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,('',))


if __name__=='__main__':
    unittest.main()
