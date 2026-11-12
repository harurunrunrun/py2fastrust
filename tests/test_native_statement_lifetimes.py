"""Early physical drops preserve loop-carried values, aliases and captures."""
import re
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
import test_native_source_state as state_tests


PREFIX='''class Box:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
seed = Box(0)
seed.increase()
'''
SOURCES={
    'dead_each_iteration': PREFIX+'''def calculate(n):
    total = 0
    for i in range(n):
        left = Box(i)
        right = Box(i + 3)
        total += left.value * right.value
    return total
print(calculate(int(input())))
''',
    'loop_carried_exit': PREFIX+'''def calculate(n):
    right = Box(50)
    total = 0
    for i in range(n):
        left = Box(i)
        right = Box(i + 3)
        total += left.value * right.value
    return total, right.value
print(calculate(int(input())))
''',
    'break_continue': PREFIX+'''def calculate(n):
    right = Box(50)
    total = 0
    for i in range(n):
        if i == 4:
            break
        if i % 2 == 0:
            continue
        total += right.value
        right = Box(i)
    return total, right.value
print(calculate(int(input())))
''',
    'retained_list_alias': PREFIX+'''def calculate(n):
    values = []
    for i in range(n):
        right = Box(i)
        values.append(right)
    for value in values:
        value.increase()
    return [value.value for value in values]
print(calculate(int(input())))
''',
    'captured_late_binding': PREFIX+'''def calculate():
    right = Box(7)
    read = lambda: right.value
    right = Box(9)
    return read()
print(calculate())
''',
    'zero_iteration_unbound': PREFIX+'''def calculate(n):
    for _ in range(n):
        right = Box(9)
    return right.value
print(calculate(int(input())))
''',
    'saved_representation': PREFIX+'''def calculate():
    old = Box(1)
    shown = str(old)
    newer = Box(2)
    return shown == str(newer)
print(calculate())
''',
    'dictionary_values': PREFIX+'''def calculate(n):
    cache = {}
    for i in range(n):
        if i not in cache:
            item = Box(i)
            cache[i] = [item]
    return [cache[i][0].value for i in range(n)]
print(calculate(int(input())))
''',
}


class NativeStatementLifetimeTests(unittest.TestCase):
    def test_dead_shared_handles_are_cleared_inside_the_iteration(self):
        for mode in ('i64','i128'):
            result=transpile(SOURCES['dead_each_iteration'],TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertTrue(re.search(r'class_local_\d+=None;',result.rust_source))

    def test_saved_representations_keep_source_binding_lifetimes(self):
        result=transpile(SOURCES['saved_representation'],TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertFalse(re.search(r'class_local_\d+=None;',result.rust_source))

    def test_dictionary_membership_does_not_observe_value_addresses(self):
        result=transpile(SOURCES['dictionary_values'],TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(re.search(r'class_local_\d+=None;',result.rust_source))

    def test_source_execution_and_exception_frames_in_all_build_modes(self):
        with patch.dict(state_tests.SOURCES,SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    inputs=('',)if name in {'captured_late_binding','saved_representation'}else('0\n','1\n','6\n')
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,inputs)


if __name__=='__main__':
    unittest.main()
