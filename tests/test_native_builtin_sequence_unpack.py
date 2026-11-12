"""Builtin sequence alternatives unpack without allocating iterator states."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_finite_tuple_unpacking as finite
import test_native_source_state as state_tests


PREFIX = '''class Marker:
    def __init__(self):
        self.value = 0
    def increase(self):
        self.value += 1
marker = Marker()
marker.increase()
'''

TUPLE_CALLBACK = PREFIX + '''def combine(row):
    left, right = row
    return left * 10 + right
print(combine(tuple(map(int, input().split()))))
print(combine((3, 4)))
'''

LIST_TARGET_ALIAS = PREFIX + '''def assign(source, target):
    target[1], target[0] = source
values = [3, 8]
assign(values, values)
print(values)
assign((5, 9), values)
print(values)
'''

SHARED_PAYLOAD = PREFIX + '''def alter(row):
    left, right = row
    left.append(9)
    print(right)
shared = [1]
alter([shared, shared])
alter((shared, [2]))
print(shared)
'''

TARGET_ORDER = PREFIX + '''values = [7, 8]
def index():
    print("target")
    return 0
def assign(source):
    values[index()], values[index()] = source
    print(values)
assign(tuple(map(int, input().split())))
assign((3, 4))
'''

EMPTY_TARGET = PREFIX + '''def unpack(row):
    () = row
    print("empty")
unpack(tuple(map(int, input().split())))
unpack(())
'''

NONITERABLE = PREFIX + '''def unpack(row):
    left, right = row
    print(left, right)
choice = int(input())
unpack([2, 3] if choice == 1 else ((4, 5) if choice == 2 else None))
'''

STARRED = PREFIX + '''def unpack(row):
    first, *rest = row
    print(first, rest)
unpack(tuple(map(int, input().split())))
unpack((3, 4))
'''

SOURCES = {
    'finite_tuple_callback': TUPLE_CALLBACK,
    'finite_list_target_alias': LIST_TARGET_ALIAS,
    'finite_shared_payload': SHARED_PAYLOAD,
    'finite_target_order': TARGET_ORDER,
    'finite_empty_target': EMPTY_TARGET,
    'finite_noniterable': NONITERABLE,
    'finite_starred': STARRED,
}


class NativeBuiltinSequenceUnpackTests(unittest.TestCase):
    def test_callback_unpack_has_no_heap_iterator_state(self):
        original = finite.emit
        selected = []

        def inspect(emitter, target, value, record, **kwargs):
            result = original(emitter, target, value, record, **kwargs)
            if any(isinstance(part, finite.SequenceMembers) for part in record.variants.values()):
                selected.append(result)
            return result

        with patch.object(finite, 'emit', inspect):
            result = transpile(TUPLE_CALLBACK, TranspileOptions(license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(selected)
        for code in selected:
            self.assertNotIn('ClassIteratorState', code)
            self.assertNotIn('RefCell::new', code)
            self.assertIn('class_unpack_length(', code)

    def test_length_errors_target_order_aliases_and_integer_modes(self):
        inputs = {
            'finite_tuple_callback': ('5 6\n', '1\n', '1 2 3\n'),
            'finite_target_order': ('5 6\n', '1\n', '1 2 3\n'),
            'finite_empty_target': ('\n', '1\n'),
            'finite_noniterable': ('0\n', '1\n', '2\n'),
            'finite_starred': ('5 6 7\n', '\n'),
        }
        with patch.dict(state_tests.SOURCES, SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(
                        self, name, inputs.get(name, ('',)))


if __name__ == '__main__':
    unittest.main()
