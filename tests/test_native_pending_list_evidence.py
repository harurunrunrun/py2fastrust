"""Pending mutable allocations keep real element evidence across binding views."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust.native_class_globals import Namespace
from py2fastrust.native_classes import Cell, Model, merge, shape
from py2fastrust.native_types import ListType


SOURCE = '''class Ledger:
    entries = []
    def __init__(self, value):
        self.value = value
    def __enter__(self):
        Ledger.entries.append(self.value)
        return self
    def __exit__(self, typ, error, trace):
        Ledger.entries.pop()
    @classmethod
    def latest(cls):
        return cls.entries[-1]
class Reading:
    def __init__(self):
        self.value = Ledger.latest()
    def read(self):
        return self.value
def measure():
    return Reading()
with Ledger(bool(int(input()))):
    print(measure().read())
'''


class PendingListEvidence(unittest.TestCase):
    def setUp(self):
        model = SimpleNamespace(unit=None, value_constraints=SimpleNamespace(variables={}))
        self.namespace = Namespace(model)
        self.node = ast.parse('items').body[0].value

    def test_element_evidence_reaches_all_aliases_without_merging_bindings(self):
        element = Cell()
        allocation = Cell('list', (element,), list_origins=frozenset({1}))
        first, second = Cell(), Cell()
        self.assertTrue(self.namespace.contribute(first, allocation, self.node, force=True))
        self.assertTrue(self.namespace.contribute(second, first, self.node, force=True))
        self.assertIsNone(shape(element))
        merge(second.args[0], Cell('bool'), self.node)
        for value in (allocation, first, second):
            self.assertEqual(shape(value), ListType('bool'))
            self.assertEqual(value.list_origins, frozenset({1}))
        self.assertIsNot(allocation.root(), first.root())
        self.assertIsNot(first.root(), second.root())

    def test_already_shared_elements_retain_all_allocation_origins(self):
        element = Cell()
        first = Cell('list', (element,), list_origins=frozenset({1}))
        second = Cell('list', (element,), list_origins=frozenset({2}))
        view = Cell()
        self.assertTrue(self.namespace.contribute(view, first, self.node, force=True))
        self.assertTrue(self.namespace.contribute(view, second, self.node, force=True))
        merge(element, Cell('str'), self.node)
        self.assertEqual(shape(view), ListType('str'))
        self.assertEqual(view.list_origins, frozenset({1, 2}))
        self.assertEqual(first.list_origins, frozenset({1}))
        self.assertEqual(second.list_origins, frozenset({2}))

    def test_rebinding_does_not_change_the_old_allocation(self):
        element = Cell()
        old = Cell('list', (element,), list_origins=frozenset({1}))
        view = Cell()
        self.assertTrue(self.namespace.contribute(view, old, self.node, force=True))
        merge(element, Cell('bool'), self.node)
        replacement = Cell('list', (Cell('str'),), list_origins=frozenset({2}))
        self.assertTrue(self.namespace.contribute(view, replacement, self.node, force=True))
        self.assertEqual(shape(old), ListType('bool'))
        self.assertEqual(shape(replacement), ListType('str'))
        self.assertIsNot(old.root(), replacement.root())
        self.assertNotEqual(shape(view), ListType('bool'))

    def test_unknown_scalars_and_unrelated_pending_elements_keep_the_existing_path(self):
        target = Cell()
        self.assertFalse(self.namespace.contribute(target, Cell(), self.node, force=True))
        first = Cell('list', (Cell(),), list_origins=frozenset({1}))
        second = Cell('list', (Cell(),), list_origins=frozenset({2}))
        self.assertTrue(self.namespace.contribute(target, first, self.node, force=True))
        self.assertFalse(self.namespace.contribute(target, second, self.node, force=True))
        self.assertIsNone(shape(first.args[0]))
        self.assertIsNone(shape(second.args[0]))
        self.assertIsNot(first.args[0].root(), second.args[0].root())


class PendingListFullModels(unittest.TestCase):
    def test_delayed_boolean_producer_stays_homogeneous_in_all_integer_modes(self):
        original = Model.run
        for mode in ('i64', 'i128', 'bigint'):
            with self.subTest(integer=mode):
                models = []
                def observe(model):
                    result = original(model)
                    models.append(model)
                    return result
                with patch.object(Model, 'run', observe):
                    result = transpile(SOURCE, TranspileOptions(integer=mode, license='none'))
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.backend, 'native')
                self.assertTrue(models)
                lists = [kind for model in models for _, kind in model.namespace.fields()
                         if isinstance(kind, ListType)]
                self.assertIn(ListType('bool'), lists)
                self.assertNotIn(ListType('int_bool'), lists)
                self.assertNotIn('NativeScalar', result.rust_source)
                self.assertTrue(any(model.source_state.producers for model in models))
                self.assertTrue(any(model.operand_demands.projections for model in models))
