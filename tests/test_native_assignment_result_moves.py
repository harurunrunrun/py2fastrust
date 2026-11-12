"""Consume the final captured RHS without changing assignment order or aliases."""
import unittest
from unittest.mock import patch
import test_native_source_state as state_tests


PREFIX='''events = []
class Box:
    def __init__(self, value):
        self.value = value
def make():
    events.append("rhs")
    return Box(7)
def index():
    events.append("index")
    return 0
targets = [Box(0)]
'''
SOURCES={
    'last_name': PREFIX+'''targets[index()] = alias = make()
alias.value += 2
print(targets[0].value, alias is targets[0], events)
''',
    'last_subscript': PREFIX+'''alias = targets[index()] = make()
alias.value += 2
print(targets[0].value, alias is targets[0], events)
''',
    'unpack': PREFIX+'''whole = first, second = [make(), Box(3)]
first.value += 2
print(whole[0].value, whole[1].value, first is whole[0], events)
''',
}


class NativeAssignmentResultMoveTests(unittest.TestCase):
    def test_order_and_shared_instance_identity_in_all_integer_modes(self):
        with patch.dict(state_tests.SOURCES,SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,('',))


if __name__=='__main__':
    unittest.main()
