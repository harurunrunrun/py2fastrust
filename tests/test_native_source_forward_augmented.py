"""Source call order and augmented assignments retain proved state correctly."""
import unittest
from unittest.mock import patch
import test_native_source_state as state_tests

SOURCES = {'aliased_inplace_list_mutates_slot': 'class Stack:\n'
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
                                      'def change():\n'
                                      '    values = Stack.items\n'
                                      '    values += [23]\n'
                                      '    return Stack.current()\n'
                                      'with Stack(5):\n'
                                      '    print(Stack.current(), change(), Stack.current())\n',
 'augmented_target_precedes_rhs': 'class Stack:\n'
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
                                  'data = [1]\n'
                                  'def target():\n'
                                  '    Stack.items[0] = 29\n'
                                  '    return data\n'
                                  'def rhs():\n'
                                  '    print(Stack.current())\n'
                                  '    return 2\n'
                                  'with Stack(7):\n'
                                  '    target()[0] += rhs()\n'
                                  '    print(data[0], Stack.current())\n',
 'forward_definition_chain': 'class Stack:\n'
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
                             'def first(value):\n'
                             '    return second(value) + 1\n'
                             'def second(value):\n'
                             '    return third(value) + 2\n'
                             'def third(value):\n'
                             '    return Stack.current() + value\n'
                             'with Stack(17):\n'
                             '    print(first(4))\n',
 'scalar_augmented_normal_edge': 'class Stack:\n'
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
                                 '    value += 3\n'
                                 '    if value > 7:\n'
                                 '        value -= 2\n'
                                 '    return value + Stack.current()\n'
                                 'with Stack(19):\n'
                                 '    print(read(int(input())))\n',
 'source_inplace_protocol_keeps_effects': 'class Stack:\n'
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
                                          '    def __init__(self, value):\n'
                                          '        self.value = value\n'
                                          '    def __iadd__(self, value):\n'
                                          '        Stack.items[0] = 31\n'
                                          '        self.value += value\n'
                                          '        return self\n'
                                          'def change():\n'
                                          '    box = Box(2)\n'
                                          '    box += 3\n'
                                          '    return box.value + Stack.current()\n'
                                          'with Stack(11):\n'
                                          '    print(change(), Stack.current())\n'}
INPUTS = {'aliased_inplace_list_mutates_slot': ('',),
 'augmented_target_precedes_rhs': ('',),
 'forward_definition_chain': ('',),
 'scalar_augmented_normal_edge': ('0\n', '8\n'),
 'source_inplace_protocol_keeps_effects': ('',)}

class ForwardAugmentedProofs(unittest.TestCase):
    def test_forward_callees_are_available_before_any_body_is_annotated(self):
        result, model, reads, exports = state_tests.convert(SOURCES['forward_definition_chain'])
        self.assertTrue(result.success, result.diagnostics)
        state = model.source_state
        for scope in ('first', 'second', 'third'):
            plan = next(p for p in state.plans.values() if p.scope == scope)
            self.assertTrue(state.modes['function', plan.index].calls, scope)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_native_augmented_assignment_preserves_the_normal_witness(self):
        result, model, reads, exports = state_tests.convert(SOURCES['scalar_augmented_normal_edge'])
        self.assertTrue(result.success, result.diagnostics)
        state = model.source_state
        plan = next(p for p in state.plans.values() if p.scope == 'read')
        self.assertTrue(state.modes['function', plan.index].calls)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_source_and_alias_mutations_do_not_gain_a_stale_witness(self):
        for name in ('aliased_inplace_list_mutates_slot', 'augmented_target_precedes_rhs',
                     'source_inplace_protocol_keeps_effects'):
            result, _, _, _ = state_tests.convert(SOURCES[name])
            baseline, _, _, _ = state_tests.convert(SOURCES[name], enabled=False)
            self.assertEqual(result.success, baseline.success, name)
            if not result.success:
                self.assertEqual([str(d) for d in result.diagnostics],
                                 [str(d) for d in baseline.diagnostics])

@unittest.skipUnless(state_tests.shutil.which('rustc'), 'rustc is required')
class ForwardAugmentedExecution(unittest.TestCase):
    def test_original_programs(self):
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
                    state_tests.NativeSourceStateExecutionTests.exercise(self, name, INPUTS[name])
