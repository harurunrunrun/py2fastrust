"""Operand data demand requires complete source use and call-point evidence."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.native_operand_demands import (
    Registry, PrivateProjection, call_projection, private_projection)
from test_native_source_total_places import fixture


def formal_fixture(body='return owner.items[-1]'):
    f = fixture(body)
    f.model = f.emitter.model
    f.model.value_classes = SimpleNamespace(
        parents={id(child): parent for parent in ast.walk(f.unit.tree)
                 for child in ast.iter_child_nodes(parent)})
    f.state.raw_own = {17: tuple(ast.walk(f.emitter.plan.node))}
    f.state.own = dict(f.state.raw_own)
    f.state.kind = lambda plan, node: f.kinds.get(id(node))
    registry = Registry.__new__(Registry)
    registry.model, registry.state = f.model, f.state
    return f, registry


class FormalDemandContracts(unittest.TestCase):
    def test_all_surviving_loads_are_exact_certified_receivers(self):
        f, registry = formal_fixture()
        self.assertEqual(registry.formal_reads(f.emitter.plan, f.mode, 'owner'),
                         (id(f.node),))

    def test_an_additional_value_use_retains_the_formal(self):
        for body in ('value = owner.items[-1]\nreturn owner',
                     'value = owner.items[-1]\nreturn owner.other',
                     'return owner.items[-1] + owner.items[-1]'):
            with self.subTest(body=body):
                f, registry = formal_fixture(body)
                self.assertIsNone(registry.formal_reads(f.emitter.plan, f.mode, 'owner'))

    def test_an_unknown_official_producer_or_missing_owned_load_is_not_erased(self):
        f, registry = formal_fixture()
        f.state.rows += (SimpleNamespace(owner=f.scope, scope=f.scope, name='owner',
                                         role='delete', node=-1),)
        self.assertIsNone(registry.formal_reads(f.emitter.plan, f.mode, 'owner'))
        f, registry = formal_fixture()
        f.state.raw_own[17] = ()
        self.assertIsNone(registry.formal_reads(f.emitter.plan, f.mode, 'owner'))

    def test_private_header_projection_requires_its_exact_mode_and_live_values(self):
        f, _ = formal_fixture()
        plan = f.emitter.plan
        projection = PrivateProjection(plan, f.mode, frozenset({'owner'}), (0,), ())
        f.model.operand_demands = SimpleNamespace(
            model=f.model, state=f.state, projections={17: projection})
        f.state.abis = {17: SimpleNamespace(plan=plan, slots=(f.slot,))}
        f.emitter.source_state_private = True
        self.assertIs(private_projection(f.emitter), projection)
        f.emitter.source_state_active = (f.mode, {})
        self.assertIsNone(private_projection(f.emitter))
        f.emitter.source_state_active = (object(), {f.slot.key: 'value'})
        self.assertIsNone(private_projection(f.emitter))

    def test_missing_post_argument_permission_or_witness_declines(self):
        f, _ = formal_fixture()
        plan = f.emitter.plan
        projection = PrivateProjection(plan, f.mode, frozenset({'owner'}), (0,), ())
        f.model.operand_demands = SimpleNamespace(
            model=f.model, state=f.state, projections={17: projection})
        f.state.abis = {17: SimpleNamespace(plan=plan, slots=(f.slot,))}
        with patch('py2fastrust.native_source_state.call_arguments', return_value=None):
            self.assertIsNone(call_projection(f.emitter, f.node, plan))
        f.emitter.source_state_active = (f.mode, {})
        with patch('py2fastrust.native_source_state.call_arguments') as permission:
            self.assertIsNone(call_projection(f.emitter, f.node, plan))
            permission.assert_not_called()
