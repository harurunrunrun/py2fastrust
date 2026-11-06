"""Private source entry variants retain the original parameter borrow proof."""
import unittest
from unittest.mock import patch
import test_native_source_state as state_tests

SOURCES = {'captured_value_formal': 'class Stack:\n'
                          '    items = []\n'
                          '    def __init__(self, value):\n'
                          '        self.value = value\n'
                          '    def __enter__(self):\n'
                          '        self.items.append(self.value)\n'
                          '    def __exit__(self, kind, error, trace):\n'
                          '        self.items.pop()\n'
                          '    @classmethod\n'
                          '    def current(cls):\n'
                          '        return cls.items[-1]\n'
                          'class Number:\n'
                          '    def __init__(self, value):\n'
                          '        self.value = value % Stack.current()\n'
                          'def combine(value):\n'
                          '    def captured():\n'
                          '        return value.value\n'
                          '    return Number(captured() + Stack.current())\n'
                          'with Stack(107):\n'
                          '    print(combine(Number(23)).value)\n',
 'mutable_value_formal': 'class Stack:\n'
                         '    items = []\n'
                         '    def __init__(self, value):\n'
                         '        self.value = value\n'
                         '    def __enter__(self):\n'
                         '        self.items.append(self.value)\n'
                         '    def __exit__(self, kind, error, trace):\n'
                         '        self.items.pop()\n'
                         '    @classmethod\n'
                         '    def current(cls):\n'
                         '        return cls.items[-1]\n'
                         'class Number:\n'
                         '    def __init__(self, value):\n'
                         '        self.value = value % Stack.current()\n'
                         '    def add(self, other):\n'
                         '        other.value += 1\n'
                         '        return Number(self.value + other.value)\n'
                         'with Stack(103):\n'
                         '    first = Number(71)\n'
                         '    second = Number(59)\n'
                         '    print(first.add(second).value, second.value, Stack.current())\n',
 'readonly_value_formals': 'class Stack:\n'
                           '    items = []\n'
                           '    def __init__(self, value):\n'
                           '        self.value = value\n'
                           '    def __enter__(self):\n'
                           '        self.items.append(self.value)\n'
                           '    def __exit__(self, kind, error, trace):\n'
                           '        self.items.pop()\n'
                           '    @classmethod\n'
                           '    def current(cls):\n'
                           '        return cls.items[-1]\n'
                           'class Number:\n'
                           '    def __init__(self, value):\n'
                           '        self.value = value % Stack.current()\n'
                           '    def __add__(self, other):\n'
                           '        return Number(self.value + other.value)\n'
                           'with Stack(101):\n'
                           '    first = Number(73)\n'
                           '    second = Number(61)\n'
                           '    print((first + second).value, Stack.current())\n'}

class SourceSymbolBorrowProofs(unittest.TestCase):
    def test_readonly_private_value_parameters_keep_the_borrowed_carrier(self):
        result, model, reads, exports = state_tests.convert(SOURCES['readonly_value_formals'])
        self.assertTrue(result.success, result.diagnostics)
        plan = next(p for p in model.plans if p.scope == '__add__' and p.reachable)
        symbol = 'class_state_function_' + str(plan.index)
        self.assertIn(symbol, model.value_parameter_borrows.applied)
        self.assertEqual(set(model.value_parameter_borrows.applied[symbol]),
                         {'class_argument_0', 'class_argument_1'})
        self.assertIn(symbol + '(', result.rust_source)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_mutation_and_capture_keep_the_existing_parameter_certificate(self):
        for name in ('mutable_value_formal', 'captured_value_formal'):
            result, model, _, _ = state_tests.convert(SOURCES[name])
            baseline, _, _, _ = state_tests.convert(SOURCES[name], enabled=False)
            self.assertEqual(result.success, baseline.success)
            if not result.success:
                self.assertEqual([str(d) for d in result.diagnostics],
                                 [str(d) for d in baseline.diagnostics])
                continue
            scope = 'add' if name == 'mutable_value_formal' else 'combine'
            plan = next(p for p in model.plans if p.scope == scope and p.reachable)
            protected = 1 if name == 'mutable_value_formal' else 0
            self.assertNotIn((plan.index, protected), model.value_parameter_borrows.parameters)

@unittest.skipUnless(state_tests.shutil.which('rustc'), 'rustc is required')
class SourceSymbolBorrowExecution(unittest.TestCase):
    def test_source_programs(self):
        for name in SOURCES:
            with self.subTest(name=name):
                result, _, _, _ = state_tests.convert(SOURCES[name])
                baseline, _, _, _ = state_tests.convert(SOURCES[name], enabled=False)
                self.assertEqual(result.success, baseline.success)
                if not result.success:
                    self.assertTrue(result.diagnostics)
                    self.assertEqual([str(d) for d in result.diagnostics],
                                     [str(d) for d in baseline.diagnostics])
                    continue
                with patch.dict(state_tests.SOURCES, SOURCES):
                    state_tests.NativeSourceStateExecutionTests.exercise(self, name, ('',))
