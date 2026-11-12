"""Concrete scalar returns preserve aliasing and RHS/target/error order."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
import test_native_source_state as state_tests


SOURCE='''events = []
class Number:
    def __init__(self, value):
        events.append(value)
        self.value = value
    def increase(self):
        self.value += 1
    def __add__(self, right):
        return raw(self.value + right.value)
def raw(value):
    result = Number(0)
    result.value = value
    return result
seed = Number(0)
seed.increase()
items = [Number(i) for i in range(4)]
held = items[1]
items[0] = items[0] + items[1]
items[1] = items[2] + items[3]
held.increase()
print([item.value for item in items], held.value, events)
'''

PUBLISHED='''saved = []
class Number:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
def publish(value):
    result = Number(value)
    saved.append(result)
    return result
items = [Number(0)]
items[0] = publish(3)
saved[0].increase()
print(items[0].value, saved[0].value)
'''

ERRORS='''events = []
class Number:
    def __init__(self, value):
        events.append(value)
        print("initialize", value)
        self.value = 20 // value
    def increase(self):
        self.value += 1
def make(value):
    return Number(value)
seed = Number(1)
seed.increase()
items = [Number(2)]
items[int(input())] = make(int(input()))
print(items[0].value, events)
'''

CONTEXT='''class Rules:
    values = []
    def __init__(self, value):
        self.value = value
    def __enter__(self):
        self.values.append(self.value)
    def __exit__(self, kind, value, trace):
        self.values.pop()
    @classmethod
    def current(cls):
        return cls.values[-1]
class Number:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
def build(value):
    Rules.values.append(value)
    return Number(Rules.current())
seed = Number(0)
seed.increase()
items = [Number(0) for _ in range(4)]
with Rules(7):
    for i in range(4):
        items[i] = build(i + 2)
    print([item.value for item in items], Rules.current())
print(Rules.current())
'''

OPERAND_ORDER='''class Number:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
    def __add__(self, right):
        return Number(self.value + right.value)
def change(value):
    value.increase()
    return Number(value.value)
def run(items):
    for i in range(len(items)):
        items[i] = items[i] + change(items[i])
items = [Number(2), Number(3)]
held = items[0]
run(items)
print([item.value for item in items], held.value)
'''


class NativeScalarDataResultTests(unittest.TestCase):
    def test_proved_fresh_results_have_concrete_data_return_entries(self):
        for mode in ('i64','i128'):
            result=transpile(SOURCE,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertTrue('fn class_data_function_'in result.rust_source)
            self.assertTrue('fn class_list_set_data_'in result.rust_source)
            self.assertRegex(result.rust_source,r'fn class_data_function_\d+\(class_scope:&ClassScope')

    def test_original_aliases_effects_and_frames_in_all_build_modes(self):
        sources={'data_aliases':SOURCE,'published_result':PUBLISHED,'data_errors':ERRORS,
                 'data_context':CONTEXT,'data_operand_order':OPERAND_ORDER}
        with patch.dict(state_tests.SOURCES,sources):
            for name in sources:
                with self.subTest(name=name):
                    inputs=('4\n0\n','0\n99\n','4\n99\n')if name=='data_errors'else('',)
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,inputs)


if __name__=='__main__':
    unittest.main()
