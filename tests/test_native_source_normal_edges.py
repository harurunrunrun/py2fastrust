"""Preserve source witnesses only along actual normal control-flow edges."""
import unittest
from unittest.mock import patch
import test_native_source_state as state_tests

SOURCES = {'early_raise_normal_edge': 'class Stack:\n'
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
                            'def read(flag):\n'
                            '    if flag:\n'
                            '        raise ValueError("stop")\n'
                            '    return Stack.current()\n'
                            'with Stack(61):\n'
                            '    try:\n'
                            '        print(read(int(input())))\n'
                            '    except ValueError as error:\n'
                            '        print(type(error).__name__, str(error))\n',
 'early_return_normal_edge': 'class Stack:\n'
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
                             'def read(flag):\n'
                             '    if flag:\n'
                             '        return Stack.current()\n'
                             '    print("continued")\n'
                             '    return Stack.current()\n'
                             'with Stack(47):\n'
                             '    print(read(int(input())))\n',
 'identity_assertion': 'class Stack:\n'
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
                       'def read(value):\n'
                       '    assert value is not None\n'
                       '    return Stack.current()\n'
                       'with Stack(43):\n'
                       '    print(read(5))\n',
 'identity_does_not_call_equality': 'class Stack:\n'
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
                                    'class Box:\n'
                                    '    def __eq__(self, other):\n'
                                    '        Stack.items[0] = 97\n'
                                    '        return True\n'
                                    'def read(value):\n'
                                    '    assert value is not None\n'
                                    '    return Stack.current()\n'
                                    'with Stack(53):\n'
                                    '    print(read(Box()), Stack.current())\n',
 'identity_operand_effect_is_retained': 'class Stack:\n'
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
                                        'def replace():\n'
                                        '    Stack.items[0] = 59\n'
                                        '    return None\n'
                                        'def read(value):\n'
                                        '    if value is not replace():\n'
                                        '        return Stack.current()\n'
                                        '    return 0\n'
                                        'with Stack(3):\n'
                                        '    print(read(1), Stack.current())\n'}
INPUTS = {'early_raise_normal_edge': ('0\n', '1\n'),
 'early_return_normal_edge': ('0\n', '1\n'),
 'identity_assertion': ('',),
 'identity_does_not_call_equality': ('',),
 'identity_operand_effect_is_retained': ('',)}

class NormalEdgeProofs(unittest.TestCase):
    def test_identity_assertion_has_no_implicit_source_protocol(self):
        result, model, reads, exports = state_tests.convert(SOURCES['identity_assertion'])
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(model.source_state.bridges)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_returned_branch_does_not_erase_the_other_normal_successor(self):
        result, model, reads, exports = state_tests.convert(SOURCES['early_return_normal_edge'])
        self.assertTrue(result.success, result.diagnostics)
        state = model.source_state
        plan = next(p for p in state.plans.values() if p.scope == 'read')
        mode = state.modes['function', plan.index]
        self.assertEqual(len(mode.calls), 2)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_identity_operands_keep_their_real_source_effects(self):
        result, model, reads, exports = state_tests.convert(SOURCES['identity_operand_effect_is_retained'])
        self.assertTrue(result.success, result.diagnostics)
        self.assertFalse(reads)
        self.assertFalse(exports)

@unittest.skipUnless(state_tests.shutil.which('rustc'), 'rustc is required')
class NormalEdgeExecution(unittest.TestCase):
    def exercise(self, name):
        with patch.dict(state_tests.SOURCES, SOURCES):
            state_tests.NativeSourceStateExecutionTests.exercise(self, name, INPUTS[name])

    def test_identity_and_operand_effects(self):
        for name in ('identity_assertion', 'identity_does_not_call_equality',
                     'identity_operand_effect_is_retained'):
            with self.subTest(name=name):
                self.exercise(name)

    def test_returning_branch(self):
        self.exercise('early_return_normal_edge')

    def test_raising_branch_preserves_native_admission(self):
        name = 'early_raise_normal_edge'
        for integer in ('i64', 'i128', 'bigint'):
            result, _, _, _ = state_tests.convert(SOURCES[name], integer)
            baseline, _, _, _ = state_tests.convert(SOURCES[name], integer, enabled=False)
            self.assertEqual(result.success, baseline.success)
            if not result.success:
                self.assertTrue(result.diagnostics)
                self.assertEqual([str(d) for d in result.diagnostics],
                                 [str(d) for d in baseline.diagnostics])
        if result.success:
            self.exercise(name)
