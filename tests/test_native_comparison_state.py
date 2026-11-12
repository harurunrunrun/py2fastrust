"""Builtin key comparisons retain context facts; source callbacks invalidate them."""
import unittest
from unittest.mock import patch
import test_native_source_state as state_tests


PREFIX = '''class Stack:
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
'''

SOURCES = {
    'object_value_cache': PREFIX + '''class Payload:
    def __init__(self, value):
        self.value = value
cache = {1: Payload(9)}
def calculate():
    if 1 not in cache:
        cache[1] = Payload(7)
    return Stack.current() + cache[1].value
with Stack(37):
    print(calculate())
''',
    'builtin_sequence_comparison': PREFIX + '''with Stack(43):
    if [1, 2] == [1, 2] and "x" in ("x", "y"):
        print(Stack.current())
''',
    'effectful_query': PREFIX + '''cache = {1: 7}
def query():
    Stack.items.append(99)
    return 1
with Stack(31):
    print(query() in cache, Stack.current())
''',
    'source_comparison': PREFIX + '''class Query:
    def __eq__(self, other):
        Stack.items.append(89)
        return True
with Stack(29):
    print(Query() == 0, Stack.current())
''',
    'chained_query': PREFIX + '''def query():
    Stack.items.append(71)
    return 1
with Stack(23):
    print(0 < query() < 2, Stack.current())
''',
}


class NativeComparisonStateTests(unittest.TestCase):
    def test_builtin_comparisons_retain_successful_context_reads(self):
        for name in ('object_value_cache', 'builtin_sequence_comparison'):
            with self.subTest(name=name):
                result, model, reads, exports = state_tests.convert(SOURCES[name])
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(model.source_state.bridges)
                self.assertTrue(reads)
                self.assertTrue(exports)

    def test_mutating_operands_and_source_comparisons_invalidate_reads(self):
        for name in ('effectful_query', 'source_comparison', 'chained_query'):
            with self.subTest(name=name):
                result, _, reads, _ = state_tests.convert(SOURCES[name])
                self.assertTrue(result.success, result.diagnostics)
                self.assertFalse(reads)

    def test_native_execution_matches_python_for_all_widths_and_build_modes(self):
        with patch.dict(state_tests.SOURCES, SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(self, name, ('',))


if __name__ == '__main__':
    unittest.main()
