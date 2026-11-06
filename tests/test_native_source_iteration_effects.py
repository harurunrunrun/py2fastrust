"""Pull effects are complete before any incoming witness is transported."""
import ast
from types import SimpleNamespace
import unittest as testing
from unittest.mock import patch

from py2fastrust import native_source_iteration_effects as effects
from py2fastrust.native_aot_callables import AotFunctionType, CallSite
from py2fastrust.native_class_iterators import IteratorRecord, Iterators
from py2fastrust.native_classes import Cell
from py2fastrust.native_source_state import Registry, StateAbi, StateMode


def fixture(source='left, right = pending'):
    tree = ast.parse(source)
    plan = SimpleNamespace(index=0, node=tree)
    model = SimpleNamespace(records={}, unpack_sites={}, comprehensions={},
                            call_edges_by_site={}, callable_cells=SimpleNamespace(plans={}),
                            value_classes=SimpleNamespace(parents={
                                id(child): parent for parent in ast.walk(tree)
                                for child in ast.iter_child_nodes(parent)}))
    model.iterators = Iterators(model)
    state = SimpleNamespace(model=model, slots={'stack': object(), 'other': object()},
                            plans={0: plan}, effects={}, abis={}, requirements={},
                            excluded_owned={},
                            hash_closed=lambda plan, node: True)
    return tree, plan, state


def mapper(state, plan, demand, *, writes=(), source=None):
    """Use the same registered record/CallSite classes as actual Model demand."""
    source = source if source is not None else Cell('list', (Cell('int'),))
    records = state.model.iterators.records
    cursor = IteratorRecord(len(records), 'source', demand, plan, source, Cell('int'))
    records.append(cursor)
    callback = SimpleNamespace(index=17)
    state.plans[callback.index] = callback
    state.model.callable_cells.plans[41] = callback
    callee = Cell(AotFunctionType((41,)))
    record = IteratorRecord(len(records), 'map', demand, plan, Cell(), Cell('int'),
                            callback=callee, input_types=(cursor.kind,))
    records.append(record)
    site = CallSite(callee, Cell('int'), targets={41: object()})
    record.demands[plan.index, id(demand)] = site
    state.model.call_edges_by_site[plan.index, id(demand)] = {callback.index}
    state.effects[callback.index] = set(writes)
    state.requirements[callback.index] = {'stack'}
    state.abis[callback.index] = StateAbi(callback, ())
    return Cell(record.kind), record, site


class PullPhases(testing.TestCase):
    def word_parser(self, source_kind='str'):
        tree, plan, state = fixture("[item for item in map(int, '2 3'.split())]")
        node = tree.body[0].value
        call = node.generators[0].iter
        value, record, _ = mapper(state, plan, call)
        from py2fastrust.native_integer_word_maps import IntegerWordMap
        from py2fastrust.references import BuiltinIdentity
        record.callback = Cell(AotFunctionType((), (BuiltinIdentity('int'),)))
        record.adapter = IntegerWordMap(call.args[1], source_kind)
        state.model.records[plan.index, id(call)] = value
        state.model.records[plan.index, id(call.args[1].func.value)] = Cell(source_kind)
        state.model.text_split_sites = {(plan.index, id(call.args[1])): object()}
        state.model.comprehensions[plan.index, id(node)] = SimpleNamespace(
            sources=(SimpleNamespace(node=call),))
        return plan, state, node, call, value, record

    def test_registered_owned_text_and_bytes_parser_has_no_pull_callback(self):
        for source_kind in ('str', 'bytes'):
            with self.subTest(source_kind=source_kind):
                plan, state, node, call, value, _ = self.word_parser(source_kind)
                # The optimized adapter does not demand/call the generic map
                # callback. Its exact owned parser protocol closes the phase.
                state.effects = {}
                effect = effects._pull(state, plan, call, value)
                self.assertTrue(effect.closed)
                self.assertEqual((effect.writes, effect.calls), (set(), []))
                del state.effects
                self.assertEqual(effects.comprehension_effects(state, plan, node,
                                                               include_source=False), set())

    def test_parser_output_or_may_call_flag_never_certifies_an_unknown_adapter(self):
        plan, state, _, call, value, record = self.word_parser()
        record.adapter = SimpleNamespace(may_call=lambda *args: False)
        self.assertFalse(effects._pull(state, plan, call, value).closed)
        plan, state, _, call, value, record = self.word_parser()
        record.callback = Cell(AotFunctionType((41,)))
        self.assertFalse(effects._pull(state, plan, call, value).closed)

    def test_parser_certificate_requires_the_actual_registered_source_producer(self):
        plan, state, _, call, value, record = self.word_parser()
        state.model.text_split_sites.clear()
        self.assertFalse(effects._pull(state, plan, call, value).closed)
        plan, state, _, call, value, record = self.word_parser()
        state.model.records[plan.index, id(call.args[1].func.value)] = Cell('bytes')
        self.assertFalse(effects._pull(state, plan, call, value).closed)
        plan, state, _, call, value, record = self.word_parser()
        from py2fastrust.native_integer_word_maps import IntegerWordMap
        other = ast.parse("'4'.split()", mode='eval').body
        record.adapter = IntegerWordMap(other, 'str')
        self.assertFalse(effects._pull(state, plan, call, value).closed)

    def test_fixed_and_eager_integer_unpack_keep_incoming_state(self):
        tree, plan, state = fixture()
        target = tree.body[0].targets[0]
        values = (Cell('tuple', (Cell('int'), Cell('int'))),
                  Cell('list', (Cell('int'),)),
                  Cell('map_int', (Cell('list', (Cell('str'),)),)))
        for value in values:
            with self.subTest(kind=value.tag):
                effect = effects.unpack_phase(state, plan, target, value)
                self.assertTrue(effect.closed)
                self.assertEqual(effect.writes, set())
        # An integer output ABI alone does not certify a user input protocol.
        effect = effects.unpack_phase(state, plan, target,
            Cell('map_int', (Cell('opaque_source'),)))
        self.assertFalse(effect.closed)
        self.assertEqual(effect.writes, set(state.slots))

    def test_actual_callback_effects_precede_permission(self):
        tree, plan, state = fixture()
        target = tree.body[0].targets[0]
        value, record, _ = mapper(state, plan, target)
        effect = effects.unpack_phase(state, plan, target, value)
        mode = StateMode()
        effects.annotate_pulls(state, effect, {'stack'}, mode)
        self.assertEqual(mode.calls[id(target)], {17})
        state.effects[17] = {'stack'}
        changed = effects.unpack_phase(state, plan, target, value)
        mode = StateMode()
        effects.annotate_pulls(state, changed, {'stack'}, mode)
        self.assertEqual(changed.writes, {'stack'})
        self.assertEqual(mode.calls, {})
        # A foreign descriptor with the same index is not the model's cursor.
        state.model.iterators.records[record.index] = object()
        self.assertFalse(effects.unpack_phase(state, plan, target, value).closed)

    def test_mixed_or_missing_native_role_never_uses_source_edges_as_proof(self):
        tree, plan, state = fixture()
        target = tree.body[0].targets[0]
        value, record, site = mapper(state, plan, target)
        site.errors['invalid alternative'] = object()
        effect = effects.unpack_phase(state, plan, target, value)
        self.assertFalse(effect.closed)
        self.assertEqual(effect.writes, set(state.slots))
        site.errors.clear()
        del record.demands[plan.index, id(target)]
        self.assertFalse(effects.unpack_phase(state, plan, target, value).closed)

    def test_native_only_comprehension_summary_never_reads_source_fixedpoint(self):
        tree, plan, state = fixture('[item for item in pending]')
        node = tree.body[0].value
        value, _, _ = mapper(state, plan, node.generators[0].iter, writes={'stack'})
        state.model.records[plan.index, id(node.generators[0].iter)] = value
        state.model.comprehensions[plan.index, id(node)] = SimpleNamespace(
            sources=(SimpleNamespace(node=node.generators[0].iter),))
        del state.effects
        self.assertEqual(effects.comprehension_effects(state, plan, node,
                                                       include_source=False), set())
        # Laziness is a distinct lifetime; no eager summary is reused for it.
        lazy = ast.parse('(item for item in pending)', mode='eval').body
        self.assertEqual(effects.comprehension_effects(state, plan, lazy,
                                                       include_source=False), set(state.slots))


class ForTransfers(testing.TestCase):
    def transfer(self, state, plan, node, available, mode, repeated=(), no_else=False):
        trace = []
        def expression(plan, value, incoming, mode):
            trace.append(('expression', ast.unparse(value), frozenset(incoming)))
            return set(incoming)
        def block(plan, statements, incoming, mode):
            trace.append(('body' if statements is node.body else 'else',
                          frozenset(incoming)))
            return None if no_else and statements is node.orelse else set(incoming)
        state.expression = expression
        state.block = block
        state.discard_annotations = Registry.discard_annotations
        state.repeated_effects = lambda plan, roots: set(repeated)
        def truth(*args):
            raise AssertionError('For must not truth-test its iterable')
        state.after_truth = truth
        result = Registry.block(state, plan, [node], available, mode)
        return result, trace

    def test_for_list_of_source_objects_never_truth_tests_the_list_or_elements(self):
        tree, plan, state = fixture('for value in pending:\n observe()')
        node = tree.body[0]
        state.model.records[plan.index, id(node.iter)] = Cell('list', (Cell('object', ('Piece',)),))
        result, trace = self.transfer(state, plan, node, {'stack'}, StateMode())
        self.assertEqual(result, {'stack'})
        self.assertEqual(trace[0], ('expression', 'pending', frozenset({'stack'})))
        self.assertIn(('body', frozenset({'stack'})), trace)

    def test_registered_reverse_and_enumerate_nested_unpack_have_closed_pulls(self):
        tree, plan, state = fixture('for index, (left, right) in pending:\n pass')
        node = tree.body[0]
        records = state.model.iterators.records
        cursor = IteratorRecord(0, 'source', node, plan,
            Cell('list', (Cell('tuple', (Cell('int'), Cell('int'))),)),
            Cell('tuple', (Cell('int'), Cell('int'))))
        reverse = IteratorRecord(1, 'reverse', node, plan, Cell('range'), Cell('int'))
        enumerated = IteratorRecord(2, 'enumerate', node, plan, Cell(),
            Cell('tuple', (Cell('int'), cursor.element)), input_type=cursor.kind)
        records.extend((cursor, reverse, enumerated))
        state.model.records[plan.index, id(node.iter)] = Cell(enumerated.kind)
        self.assertTrue(effects.for_phase(state, plan, node).closed)
        self.assertTrue(effects._pull(state, plan, node, Cell(reverse.kind)).closed)
        del state.effects
        self.assertEqual(effects.for_effects(state, plan, node, include_source=False), set())

    def test_for_pull_callbacks_receive_only_the_complete_loop_invariant(self):
        tree, plan, state = fixture('for value in pending:\n observe()')
        node = tree.body[0]
        value, _, _ = mapper(state, plan, node)
        state.model.records[plan.index, id(node.iter)] = value
        mode = StateMode()
        result, trace = self.transfer(state, plan, node, {'stack', 'other'}, mode)
        self.assertEqual(result, {'stack', 'other'})
        self.assertEqual(mode.calls[id(node)], {17})
        mode = StateMode(calls={id(node): frozenset({17})})
        result, trace = self.transfer(state, plan, node, {'stack', 'other'}, mode,
                                      repeated={'stack'})
        self.assertEqual(result, {'other'})
        self.assertNotIn(id(node), mode.calls)
        self.assertIn(('body', frozenset({'other'})), trace)

    def test_mutating_and_unknown_pulls_invalidate_before_target_and_body(self):
        tree, plan, state = fixture('for output[position()] in pending:\n observe()')
        node = tree.body[0]
        value, _, _ = mapper(state, plan, node, writes={'stack'})
        state.model.records[plan.index, id(node.iter)] = value
        result, trace = self.transfer(state, plan, node, {'stack', 'other'}, StateMode())
        self.assertEqual(result, {'other'})
        self.assertEqual(trace[1][2], {'other'})
        state.model.records[plan.index, id(node.iter)] = Cell('opaque_iterable')
        result, trace = self.transfer(state, plan, node, {'stack', 'other'}, StateMode())
        self.assertEqual(result, set())
        self.assertIn(('body', frozenset()), trace)

    def test_nested_native_pull_summary_uses_exact_executed_owned_points(self):
        tree, plan, state = fixture('for outer in pending:\n def deferred():\n  for inner in opaque:\n   pass\n for actual in opaque:\n  pass')
        node = tree.body[0]
        deferred, actual = node.body
        state.own = {plan.index: [deferred, *ast.walk(actual)]}
        state.local_effect = lambda plan, value: (
            effects.for_effects(state, plan, value, include_source=False)
            if isinstance(value, ast.For) else set())
        self.assertEqual(Registry.repeated_effects(state, plan, [deferred]), set())
        self.assertEqual(Registry.repeated_effects(state, plan, node.body), set(state.slots))

    def test_terminating_else_has_no_normal_state_to_intersect_with_break_path(self):
        tree, plan, state = fixture('for value in pending:\n break\nelse:\n return')
        node = tree.body[0]
        state.model.records[plan.index, id(node.iter)] = Cell('range')
        result, _ = self.transfer(state, plan, node, {'stack'}, StateMode(), no_else=True)
        self.assertEqual(result, {'stack'})


class OrderedTransfers(testing.TestCase):
    def test_nested_unpack_never_forwards_across_an_earlier_target_write(self):
        tree, plan, state = fixture('output[erase()], (left, right) = (7, pending)')
        target = tree.body[0].targets[0]
        inner = target.elts[1]
        pending, _, _ = mapper(state, plan, inner)
        value = Cell('tuple', (Cell('int'), pending))
        state.discard_annotations = Registry.discard_annotations
        state.target_effect = lambda plan, node: {'stack'}
        # The established expression visitor removes call facts at its node.
        def expression(plan, node, available, mode):
            for child in ast.walk(node):
                mode.calls.pop(id(child), None)
            return available - {'stack'}
        state.expression = expression
        mode = StateMode()
        result = Registry.assignment_target(state, plan, target, {'stack', 'other'},
                                             mode, value=value)
        self.assertEqual(result, {'other'})
        self.assertEqual(mode.calls, {})
        state.target_effect = lambda plan, node: set()
        state.expression = lambda plan, node, available, mode: set(available)
        mode = StateMode()
        Registry.assignment_target(state, plan, target, {'stack'}, mode, value=value)
        self.assertEqual(mode.calls[id(inner)], {17})

    def test_complete_repeated_effect_meet_precedes_every_body_annotation(self):
        tree, plan, state = fixture('[observe() for item in outer() if replace()]')
        node = tree.body[0].value
        trace = []
        def expression(plan, value, available, mode):
            trace.append((ast.unparse(value), frozenset(available)))
            mode.calls.pop(id(value), None)
            if value is node.generators[0].iter:
                mode.reads[id(value)] = 'one-shot outer expression'
            return set(available)
        state.expression = expression
        state.discard_annotations = Registry.discard_annotations
        state.repeated_effects = lambda plan, roots: {'stack'}
        state.assignment_target = lambda plan, target, available, mode, **kw: set(available)
        state.after_truth = lambda plan, test, available: set(available)
        phase = effects.PullEffect()
        with patch.object(effects, 'comprehension_phase', return_value=phase), \
                patch.object(effects, 'comprehension_item', return_value=Cell('int')):
            mode = StateMode(reads={id(node.elt): 'stale body observation'})
            result = Registry.comprehension(state, plan, node, {'stack', 'other'}, mode)
        self.assertEqual(trace[0], ('outer()', frozenset({'stack', 'other'})))
        self.assertTrue(all('stack' not in available for _, available in trace[1:]))
        self.assertNotIn(id(node.elt), mode.reads)
        self.assertIn(id(node.generators[0].iter), mode.reads)
        self.assertEqual(result, {'other'})

    def test_pull_callback_annotation_survives_the_ordered_expression_walk(self):
        tree, plan, state = fixture('[item for item in pending]')
        node = tree.body[0].value
        value, _, _ = mapper(state, plan, node.generators[0].iter)
        state.model.records[plan.index, id(node.generators[0].iter)] = value
        state.model.comprehensions[plan.index, id(node)] = SimpleNamespace(
            sources=(SimpleNamespace(node=node.generators[0].iter),))
        def expression(plan, value, available, mode):
            mode.calls.pop(id(value), None)
            return set(available)
        state.expression = expression
        state.discard_annotations = Registry.discard_annotations
        state.repeated_effects = lambda plan, roots: set()
        state.assignment_target = lambda plan, target, available, mode, **kw: set(available)
        state.after_truth = lambda plan, test, available: set(available)
        mode = StateMode()
        Registry.comprehension(state, plan, node, {'stack'}, mode)
        self.assertEqual(mode.calls[id(node.generators[0].iter)], {17})


if __name__ == '__main__':
    testing.main()
