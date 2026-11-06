"""State effects use explicit original control and generation certificates."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.native_annotations import executable_nodes
from py2fastrust.native_aot_callables import AotFunctionType, CallSite
from py2fastrust.native_classes import Cell, InstanceType
from py2fastrust.native_module_linking import ClassReferenceType
from py2fastrust.native_source_execution_points import (
    control_closed, excluded_binding, owned_points)
from py2fastrust.native_source_state import Registry, StateMode
from py2fastrust.native_value_classes import Registry as ValueRegistry
from py2fastrust.references import BuiltinIdentity


def fixture(text, *, index=0):
    tree = ast.parse(text)
    plan = SimpleNamespace(index=index, node=tree)
    raw = tuple(ValueRegistry.own_nodes(None, plan))
    model = SimpleNamespace(records={}, unit=None, reached_statements=None,
                            type_guard_branches={}, iter_nodes=lambda: executable_nodes(tree),
                            class_namespaces=SimpleNamespace(owners={}), classes={},
                            callable_cells=SimpleNamespace(sites={}))
    return tree, plan, raw, model


def guard(model, plan, node, masks, kind=None):
    model.type_guard_branches[plan.index, id(node.test)] = masks
    if kind is None:
        kind = AotFunctionType((), (BuiltinIdentity('int'),))
    model.records[plan.index, id(node.test.args[1])] = Cell(kind)
    model.records[plan.index, id(node.test.args[0])] = Cell('int')
    model.callable_cells.sites[plan.index, id(node.test)] = CallSite(
        Cell(AotFunctionType((), (BuiltinIdentity('isinstance'),))), Cell('bool'))


class ExecutionPoints(unittest.TestCase):
    def test_missing_records_are_not_absent_effects(self):
        tree, plan, raw, model = fixture('unknown(); output = unknown()')
        self.assertEqual(tuple(owned_points(model, plan, raw)), raw)
        self.assertEqual(model.records, {})
        self.assertIn(tree.body[1].value, tuple(owned_points(model, plan, raw)))

    def test_explicit_reached_statement_certificate_excludes_whole_subtree(self):
        tree, plan, raw, model = fixture('first(); return_value = last(); dead()')
        model.reached_statements = {(0, id(node)) for node in tree.body[:2]}
        points = tuple(owned_points(model, plan, raw))
        self.assertIn(tree.body[1].value, points)
        self.assertNotIn(tree.body[2], points)
        self.assertNotIn(tree.body[2].value, points)

    def test_primitive_branch_masks_keep_test_and_follow_actual_plan_index(self):
        tree, plan, raw, model = fixture('if isinstance(value, int):\n    keep()\nelse:\n    erase()')
        branch = tree.body[0]
        guard(model, plan, branch, (True, False))
        selected = tuple(owned_points(model, plan, raw))
        self.assertIn(branch.test, selected)
        self.assertIn(branch.body[0].value, selected)
        self.assertNotIn(branch.orelse[0].value, selected)
        other = SimpleNamespace(index=1, node=tree)
        guard(model, other, branch, (False, True))
        selected = tuple(owned_points(model, other, raw))
        self.assertNotIn(branch.body[0].value, selected)
        self.assertIn(branch.orelse[0].value, selected)

    def test_both_possible_and_unknown_branch_certificates_remain_conservative(self):
        tree, plan, raw, model = fixture('if isinstance(value, int):\n    first()\nelse:\n    second()')
        branch = tree.body[0]
        guard(model, plan, branch, (True, True))
        self.assertEqual(tuple(owned_points(model, plan, raw)), raw)
        guard(model, plan, branch, ('unknown', False))
        model.reached_statements = {(0, id(branch)), (0, id(branch.body[0]))}
        self.assertFalse(control_closed(model, plan, raw))
        self.assertEqual(tuple(owned_points(model, plan, raw)), raw)

    def test_source_class_generation_seal_also_controls_reached_statements(self):
        tree, plan, raw, model = fixture('if isinstance(value, Expected):\n    first()\nelse:\n    mutate()')
        branch = tree.body[0]
        owner = object()
        model.class_namespaces.owners[9] = owner
        guard(model, plan, branch, (True, False), ClassReferenceType(9))
        model.reached_statements = {(0, id(branch)), (0, id(branch.body[0]))}
        # A semantic class index alone cannot exclude another actual generation.
        self.assertEqual(tuple(owned_points(model, plan, raw, class_root=lambda value: False)), raw)
        selected = tuple(owned_points(model, plan, raw, class_root=lambda value: value is owner))
        self.assertIn(branch.body[0].value, selected)
        self.assertNotIn(branch.orelse[0].value, selected)

    def test_cached_masks_do_not_certify_source_or_mixed_predicate_values(self):
        tree, plan, raw, model = fixture('if isinstance(value, int):\n    first()\nelse:\n    mutate()')
        branch = tree.body[0]
        guard(model, plan, branch, (True, False))
        model.reached_statements = {(0, id(branch)), (0, id(branch.body[0]))}
        for kind in (AotFunctionType((17,)), AotFunctionType((17,), (BuiltinIdentity('isinstance'),))):
            model.callable_cells.sites[0, id(branch.test)].callee = Cell(kind)
            self.assertFalse(control_closed(model, plan, raw))
            self.assertEqual(tuple(owned_points(model, plan, raw)), raw)

    def test_source_class_lookup_protocol_does_not_become_a_primitive_test(self):
        tree, plan, raw, model = fixture('if isinstance(value, int):\n    first()\nelse:\n    mutate()')
        branch = tree.body[0]
        guard(model, plan, branch, (True, False))
        for name in ('__getattribute__', '__getattr__', '__class__'):
            owner = SimpleNamespace(node=ast.parse('class Proxy: pass').body[0], methods={name: object()})
            model.classes['Proxy'] = owner
            model.records[0, id(branch.test.args[0])] = Cell(InstanceType('Proxy'))
            model.reached_statements = {(0, id(branch)), (0, id(branch.body[0]))}
            self.assertFalse(control_closed(model, plan, raw))
            self.assertEqual(tuple(owned_points(model, plan, raw)), raw)

    def test_missing_class_info_does_not_close_a_guard(self):
        tree, plan, raw, model = fixture('if isinstance(value, Expected):\n    first()\nelse:\n    mutate()')
        branch = tree.body[0]
        model.type_guard_branches[0, id(branch.test)] = (True, False)
        model.reached_statements = {(0, id(branch)), (0, id(branch.body[0]))}
        self.assertFalse(control_closed(model, plan, raw))
        self.assertEqual(tuple(owned_points(model, plan, raw)), raw)

    def test_partial_model_does_not_run_class_publication_proof_before_decline(self):
        tree, plan, raw, model = fixture('if isinstance(value, Expected):\n    first()\nelse:\n    mutate()')
        plan.reachable = True
        owner = SimpleNamespace(index=9, node=ast.parse('class Expected: pass').body[0])
        model.class_namespaces.owners[9] = owner
        guard(model, plan, tree.body[0], (True, False), ClassReferenceType(9))
        model.reached_statements = {(0, id(tree.body[0])), (0, id(tree.body[0].body[0]))}
        model.plans = [plan]
        model.iter_bindings = lambda: ()
        model.value_classes = SimpleNamespace(own_nodes=lambda plan: iter(raw))
        # The real prepare() retains its earlier missing-SourceUnit decline;
        # initialization must not dereference unit before that boundary.
        with patch.object(Registry, 'prepare', return_value=None):
            state = Registry(model)
        self.assertEqual(state.own[0], raw)

    def test_official_unlinked_source_unit_retains_raw_points_before_generation_decline(self):
        from py2fastrust.frontend import parse_source
        unit = parse_source('class Expected: pass\ndef choose(value):\n    if isinstance(value, Expected):\n        return 1\n    return 0\n', filename='ordinary_source_unit_contract.py')
        plan = SimpleNamespace(index=1, node=unit.tree.body[1], reachable=True)
        raw = tuple(ValueRegistry.own_nodes(None, plan))
        branch = plan.node.body[0]
        owner = SimpleNamespace(index=9, node=unit.tree.body[0], module_name=unit.name)
        model = SimpleNamespace(unit=unit, plans=[plan], records={}, classes={},
            class_namespaces=SimpleNamespace(owners={9: owner}),
            callable_cells=SimpleNamespace(sites={}),
            reached_statements={(1, id(branch)), (1, id(plan.node.body[1]))},
            type_guard_branches={}, iter_nodes=lambda: executable_nodes(unit.tree),
            iter_bindings=lambda: unit.bindings,
            value_classes=SimpleNamespace(own_nodes=lambda plan: iter(raw)))
        guard(model, plan, branch, (False, True), ClassReferenceType(9))
        self.assertFalse(hasattr(unit, 'original_unit'))
        for linker in (None, SimpleNamespace(modules={})):
            model.module_linker = linker
            with patch.object(Registry, 'prepare', return_value=None):
                state = Registry(model)
            self.assertEqual(state.own[1], raw)

    def test_creation_operands_keep_owner_and_lazy_annotation_boundaries(self):
        tree, plan, raw, model = fixture('@decorate()\ndef inner(value: lazy() = eager(), *, other=keyword()) -> later():\n    body()')
        points = tuple(owned_points(model, plan, raw))
        calls = {node.func.id for node in points if isinstance(node, ast.Call)}
        self.assertEqual(calls, {'decorate', 'eager', 'keyword'})
        tree, plan, raw, model = fixture('value: annotation() = initial()')
        calls = {node.func.id for node in owned_points(model, plan, raw) if isinstance(node, ast.Call)}
        self.assertEqual(calls, {'initial'})

    def test_only_known_raw_binding_producers_can_be_proven_excluded(self):
        self.assertTrue(excluded_binding(3, {2: object(), 3: object()}, {2: object()}))
        self.assertFalse(excluded_binding(99, {2: object()}, {2: object()}))
        self.assertFalse(excluded_binding(2, {2: object()}, {2: object()}))

    def test_repeated_effects_and_block_use_the_same_point_inventory(self):
        tree, plan, raw, model = fixture('dead(); live()')
        dead, live = tree.body
        model.reached_statements = {(0, id(live))}
        points = tuple(owned_points(model, plan, raw))
        visited = []
        state = SimpleNamespace(own={0: points}, slots={'slot': object()}, effects={},
            model=SimpleNamespace(call_edges_by_site={}),
            local_effect=lambda plan, node: visited.append(node) or {'slot'})
        self.assertEqual(Registry.repeated_effects(state, plan, tree.body), {'slot'})
        self.assertNotIn(dead.value, visited)
        self.assertIn(live.value, visited)
        calls = []
        state.excluded_owned = {0: {id(node) for node in raw} - {id(node) for node in points}}
        state.discard_annotations = Registry.discard_annotations
        state.expression = lambda plan, node, available, mode: calls.append(node) or set(available)
        mode = StateMode(reads={id(dead.value): object()}, calls={id(dead.value): {17}})
        Registry.block(state, plan, tree.body, {'slot'}, mode)
        self.assertEqual(calls, [live.value])
        self.assertNotIn(id(dead.value), mode.reads)
        self.assertNotIn(id(dead.value), mode.calls)


if __name__ == '__main__':
    unittest.main()
