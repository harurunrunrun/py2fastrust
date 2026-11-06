"""Definition creation is distinct from invocation and captured-parent ABI."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.frontend import parse_source
from py2fastrust import native_source_definition_effects as effects
from py2fastrust.native_source_state import Registry, StateMode


def fixture(source):
    original = parse_source(source)
    caller = SimpleNamespace(node=original.tree, index=0, class_body=None)
    targets = {}
    for index, node in enumerate((n for n in ast.walk(original.tree)
                                  if isinstance(n, ast.FunctionDef)), 1):
        targets[id(node)] = SimpleNamespace(
            node=node, index=index,
            definition_key=(original.name, original.ordinal(node)))
    unit = SimpleNamespace(node_ordinals=original.node_ordinals,
                           scopes=original.scopes,
                           original_unit=lambda node: original)
    lexical = SimpleNamespace(
        scope=lambda plan: (0 if isinstance(plan.node, ast.Module)
                            else original.scope_for(plan.node).ordinal),
        definition=lambda plan: original.ordinal(plan.node),
        repeated_definitions=set(), environments={},
        parent_scope=lambda plan: None)
    model = SimpleNamespace(
        unit=unit, lexical=lexical, integer='i64',
        callable_cells=SimpleNamespace(definition=lambda plan: original.ordinal(plan.node)),
        global_callable_metadata_observed=frozenset(),
        namespace=SimpleNamespace(defined_plans=lambda plan, node: (targets[id(node)],)))
    trace = []
    def expression(plan, node, available, mode):
        label = ast.unparse(node)
        trace.append((label, frozenset(available)))
        return set() if label.startswith('erase(') else set(available)
    registry = SimpleNamespace(model=model, rows=original.bindings, excluded_owned={},
                               slots={'state': object(), 'target': object()},
                               expression=expression,
                               after_truth=lambda plan, node, available: available)
    return original, caller, targets, registry, trace


class DefinitionEvents(unittest.TestCase):
    def test_only_defaults_execute_and_binding_publication_invalidates_its_slot(self):
        unit, caller, _, registry, trace = fixture(
            'def target(first=left(), *, second=right()):\n'
            ' erase()\n return state[-1]\n')
        node = unit.tree.body[0]
        result = effects.transfer(registry, caller, node, {'state', 'target'}, StateMode())
        self.assertEqual(result, {'state'})
        self.assertEqual([value for value, _ in trace], ['left()', 'right()'])

    def test_default_effect_precedes_the_later_default(self):
        unit, caller, _, registry, trace = fixture(
            'def target(first=erase(), second=state[-1]):\n return first\n')
        self.assertEqual(effects.transfer(registry, caller, unit.tree.body[0],
                                         {'state'}, StateMode()), set())
        self.assertEqual(trace, [('erase()', frozenset({'state'})),
                                 ('state[-1]', frozenset())])

    def test_decorator_expressions_precede_defaults_but_application_is_opaque(self):
        unit, caller, _, registry, trace = fixture(
            '@outer()\n@inner()\ndef target(value=seed()):\n return value\n')
        self.assertEqual(effects.transfer(registry, caller, unit.tree.body[0],
                                         {'state'}, StateMode()), set())
        self.assertEqual([value for value, _ in trace], ['outer()', 'inner()', 'seed()'])

    def test_unobserved_deferred_annotations_do_not_execute_or_kill_state(self):
        unit, caller, _, registry, trace = fixture(
            'def target(value: erase()=seed()) -> erase():\n return value\n')
        self.assertEqual(effects.transfer(registry, caller, unit.tree.body[0],
                                         {'state'}, StateMode()), {'state'})
        self.assertEqual([value for value, _ in trace], ['seed()'])

    def test_observed_or_unregistered_annotation_metadata_keeps_no_witness(self):
        unit, caller, _, registry, _ = fixture(
            'def target(value: erase()) -> erase():\n return value\n')
        node = unit.tree.body[0]
        registry.model.global_callable_metadata_observed = {unit.ordinal(node)}
        self.assertEqual(effects.binding_effect(registry, caller, node), {'state', 'target'})
        registry.model.global_callable_metadata_observed = frozenset()
        del registry.model.callable_cells
        self.assertEqual(effects.binding_effect(registry, caller, node), {'state', 'target'})

    def test_actual_metadata_consumers_reject_all_native_callable_alternatives(self):
        from py2fastrust.native import _Unsupported
        from py2fastrust.native_annotations import metadata_access
        from py2fastrust.native_aot_callables import AotFunctionType
        from py2fastrust.native_types import union_type
        kinds = (AotFunctionType((7,)), union_type('int', AotFunctionType((7, 11))))
        for name in ('__annotations__', '__annotate__', '__type_params__'):
            node = ast.parse('saved.' + name, mode='eval').body
            for kind in kinds:
                with self.subTest(name=name, kind=kind):
                    with self.assertRaises(_Unsupported) as rejected:
                        metadata_access(node, kind)
                    self.assertIn('lazy annotation', str(rejected.exception))

    def test_type_parameter_creation_keeps_no_unproved_witness(self):
        unit, caller, _, registry, trace = fixture(
            'def target[T: erase()](value=seed()):\n return value\n')
        self.assertEqual(effects.transfer(registry, caller, unit.tree.body[0],
                                         {'state'}, StateMode()), set())
        self.assertEqual(trace, [])

    def test_exact_original_definition_key_and_binding_row_are_required(self):
        unit, caller, targets, registry, _ = fixture('def target():\n return 7\n')
        node = unit.tree.body[0]
        target = targets[id(node)]
        self.assertEqual(effects.binding_effect(registry, caller, node), {'target'})
        target.definition_key = ('different_generation', unit.ordinal(node))
        self.assertEqual(effects.binding_effect(registry, caller, node), {'state', 'target'})
        target.definition_key = (unit.name, unit.ordinal(node))
        registry.rows = ()
        self.assertEqual(effects.binding_effect(registry, caller, node), {'state', 'target'})

    def test_repeated_instance_creation_is_a_retained_boundary(self):
        unit, caller, targets, registry, _ = fixture('def target():\n return 7\n')
        node = unit.tree.body[0]
        registry.model.lexical.repeated_definitions.add(unit.ordinal(node))
        self.assertEqual(effects.binding_effect(registry, caller, node), {'state', 'target'})

    def test_nested_lexical_binding_uses_the_original_owner(self):
        unit, caller, targets, registry, _ = fixture(
            'def outer():\n def target():\n  return 7\n return target()\n')
        outer = unit.tree.body[0]
        nested = outer.body[0]
        owner = targets[id(outer)]
        owner.class_body = None
        self.assertIsNotNone(effects.publication(registry, owner, nested))
        self.assertIsNone(effects.publication(registry, caller, nested))

    def test_global_effect_summary_uses_the_same_definition_publication(self):
        unit, caller, _, registry, _ = fixture('def target():\n return 7\n')
        self.assertEqual(Registry.local_effect(registry, caller, unit.tree.body[0]), {'target'})

    def test_block_dispatches_the_original_definition_event(self):
        unit, caller, _, registry, trace = fixture('def target(value=seed()):\n return value\n')
        self.assertEqual(Registry.block(registry, caller, unit.tree.body,
                                        {'state', 'target'}, StateMode()), {'state'})
        self.assertEqual([value for value, _ in trace], ['seed()'])


class IncomingParentAbi(unittest.TestCase):
    def test_unused_parent_does_not_require_the_parent_environment_to_be_absent(self):
        original = SimpleNamespace(index=3)
        specialized = SimpleNamespace(specialization_source=original)
        lexical = SimpleNamespace(scope=lambda plan: 8,
                                  parent_scope=lambda plan: 4,
                                  environments={4: object()})
        model = SimpleNamespace(lexical=lexical)
        with patch('py2fastrust.native_call_context_effects.unused_parent', return_value=True) as proof:
            self.assertTrue(effects.argument_parent_closed(model, specialized))
            proof.assert_called_once_with(model, original)
        with patch('py2fastrust.native_call_context_effects.unused_parent', return_value=False):
            self.assertFalse(effects.argument_parent_closed(model, specialized))

    def test_own_environment_and_missing_source_keep_the_original_parent_abi(self):
        plan = SimpleNamespace(index=3)
        lexical = SimpleNamespace(scope=lambda plan: 8,
                                  parent_scope=lambda plan: 4,
                                  environments={8: object()})
        model = SimpleNamespace(lexical=lexical)
        with patch('py2fastrust.native_call_context_effects.unused_parent', return_value=True):
            self.assertFalse(effects.argument_parent_closed(model, plan))
        cycle = SimpleNamespace()
        cycle.specialization_source = cycle
        self.assertFalse(effects.argument_parent_closed(model, cycle))


class AssertionNormalEdges(unittest.TestCase):
    def test_normal_assertion_keeps_only_post_test_success_state(self):
        unit, caller, _, registry, trace = fixture('assert flag\n')
        self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                   {'state'}, StateMode()), {'state'})
        self.assertEqual(trace, [('flag', frozenset({'state'}))])
        self.assertEqual(Registry.block(registry, caller, unit.tree.body,
                                       {'state'}, StateMode()), {'state'})

    def test_literal_true_never_visits_an_unmodeled_message(self):
        unit, caller, _, registry, trace = fixture('assert True, never_defined()\n')
        def expression(plan, node, available, mode):
            self.assertIs(node, unit.tree.body[0].test)
            return set(available)
        registry.expression = expression
        self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                   {'state'}, StateMode()), {'state'})

    def test_failure_message_uses_a_separate_mode_and_has_no_normal_effect(self):
        unit, caller, _, registry, trace = fixture('assert flag, erase()\n')
        original = registry.expression
        mode = StateMode()
        observed_modes = []
        def expression(plan, node, available, active):
            observed_modes.append(active)
            active.calls[id(node)] = frozenset({7})
            return original(plan, node, available, active)
        registry.expression = expression
        self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                   {'state'}, mode), {'state'})
        self.assertIs(observed_modes[0], mode)
        self.assertIsNot(observed_modes[1], mode)
        self.assertNotIn(id(unit.tree.body[0].msg), mode.calls)
        self.assertEqual(trace, [('flag', frozenset({'state'})),
                                 ('erase()', frozenset({'state'}))])

    def test_false_assertion_has_no_normal_state_after_message(self):
        unit, caller, _, registry, trace = fixture('assert False, erase()\n')
        self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                   {'state'}, StateMode()), set())
        self.assertEqual([value for value, _ in trace], ['False', 'erase()'])

    def test_test_mutations_and_unknown_source_truth_lose_witnesses(self):
        unit, caller, _, registry, trace = fixture('assert erase()\n')
        self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                   {'state'}, StateMode()), set())
        unit, caller, _, registry, trace = fixture('assert condition\n')
        registry.after_truth = lambda plan, node, available: set()
        self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                   {'state'}, StateMode()), set())

    def test_literal_profile_truth_uses_the_same_integer_normalization_as_lower(self):
        unit, caller, _, registry, trace = fixture('assert 18446744073709551616, erase()\n')
        for integer, expected, expressions in [('i64', set(), 2),
                                                ('i128', {'state'}, 1),
                                                ('bigint', {'state'}, 1)]:
            with self.subTest(integer=integer):
                trace.clear()
                registry.model.integer = integer
                self.assertEqual(effects.assertion_transfer(registry, caller, unit.tree.body[0],
                                                           {'state'}, StateMode()), expected)
                self.assertEqual(len(trace), expressions)


if __name__ == '__main__':
    unittest.main()
