"""Depth bounds distinguish sequential source calls from simultaneous calls."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile
from py2fastrust.native_finite_depth_calls import _guard_weight
from py2fastrust.rust_pruning import _lex


def weight(body):
    tokens, _, pairs = _lex('{' + body + '}')
    return _guard_weight(tokens, pairs, 0, len(tokens) - 1,
                         {'class_function_1', 'class_function_2'})


class NativeSequentialGuardDepthTests(unittest.TestCase):
    def test_sequential_calls_need_one_simultaneous_guard(self):
        call = 'class_sync_call(&scope,||class_function_1(),1,location);'
        self.assertEqual(weight(call * 80), 1)

    def test_nested_argument_evaluation_is_conservatively_counted(self):
        self.assertEqual(weight('class_sync_call(&scope,||class_function_1('
                                'class_sync_call(&scope,||class_function_2(),2,location)),1,location);'), 2)

    def test_immediate_closure_cannot_escape(self):
        self.assertEqual(weight('(||{class_sync_call(&scope,||class_function_1(),1,location);})();'
                                'class_sync_call(&scope,||class_function_2(),2,location);'), 1)

    def test_unknown_callback_retains_the_sum(self):
        self.assertEqual(weight('let f=||class_sync_call(&scope,||class_function_1(),1,location);'
                                'class_sync_call(&scope,||class_function_2(f()),2,location);'), 2)
        self.assertEqual(weight('let it=items.map(|item|class_sync_call(&scope,||class_function_1(),1,location));'
                                'class_sync_call(&scope,||class_function_2(it),2,location);'), 2)

    def test_nonliteral_guard_callback_retains_the_sum(self):
        self.assertEqual(weight('class_sync_call(&scope,callback,1,location);'
                                'class_sync_call(&scope,||class_function_2(),2,location);'), 2)

    def test_many_sequential_calls_remove_the_counter_and_preserve_errors(self):
        source = ('class Token:\n'
                  ' def __init__(self, value):self.value=value\n'
                  ' def read(self):return self.value\n'
                  'def calculate(token):\n'
                  ' result=0\n' + ' result+=token.read()\n' * 80 +
                  ' return result//int(input())\n'
                  'print(calculate(Token(7)))\n')
        result = transpile(source)
        self.assertTrue(result.success, result.diagnostics)
        self.assertFalse('let _depth=ClassSyncDepth(scope)' in result.rust_source)
        # Reuse the real Python/native differential harness for all three
        # integer widths, both build modes and a failing arithmetic exit.
        import test_native_source_state as state_tests
        with patch.dict(state_tests.SOURCES, {'sequential_depth': source}):
            state_tests.NativeSourceStateExecutionTests.exercise(
                self, 'sequential_depth', ('4\n', '0\n'))


if __name__ == '__main__':
    unittest.main()
