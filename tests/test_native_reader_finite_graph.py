"""Saved native readers retain finite-graph and observer prerequisites."""
import ast
from types import SimpleNamespace
import unittest as testing

from py2fastrust.native_aot_callables import AotFunctionType
from py2fastrust.native_classes import Cell, StreamType
from py2fastrust.native_finite_depth_calls import (
    Unproved, _model_proof, _native_reader_call, _weighted_bounds)
from py2fastrust.native_module_calls import BuiltinRef


def fixture(tag='reader_bytes', expression='captured()', result='bytes'):
    tree = ast.parse(expression)
    node = tree.body[0].value
    plan = SimpleNamespace(index=0, reachable=True)
    output = Cell(result)
    model = SimpleNamespace(
        plans=[plan], classes={}, gc_classes=(), generators=SimpleNamespace(records=[]),
        native_call_heights={0: 1}, synchronous_calls={0},
        records={(0, id(node)): output, (0, id(node.func)): Cell(tag)},
        callable_cells=SimpleNamespace(sites={}, member_used=set()),
        call_edges_by_site={}, call_edges={0: set()},
        iter_nodes=lambda: ast.walk(tree), builtin_identity=lambda *args: None,
        value_classes=SimpleNamespace(constructor=lambda *args: False))
    return model, plan, node, output


class ReaderFiniteGraph(testing.TestCase):
    def test_all_four_exact_native_tags_close_their_zero_argument_call(self):
        for tag, result in (('reader_text', 'str'), ('read_text', 'str'),
                            ('reader_bytes', 'bytes'), ('read_bytes', 'bytes')):
            with self.subTest(tag=tag):
                model, plan, node, output = fixture(tag, result=result)
                self.assertTrue(_native_reader_call(model, plan, node, output))
                self.assertEqual(_model_proof(model)['source_plans'], 1)
        # The source alias spelling has no role in the native certificate.
        model, plan, node, output = fixture(expression='unrelated_alias()')
        self.assertTrue(_native_reader_call(model, plan, node, output))

    def test_source_callable_or_same_domain_spelling_is_not_a_native_reader(self):
        for tag in (AotFunctionType((12,)), StreamType('reader_bytes'),
                    'bytes', 'unknown_reader'):
            with self.subTest(tag=tag):
                model, plan, node, output = fixture(tag, expression='reader_bytes()')
                self.assertFalse(_native_reader_call(model, plan, node, output))
                with self.assertRaisesRegex(Unproved, 'closed source or sealed builtin'):
                    _model_proof(model)
        model, plan, node, output = fixture()
        model.records[0, id(node.func)] = Cell('reader_bytes', (Cell('int'),))
        self.assertFalse(_native_reader_call(model, plan, node, output))

    def test_expansion_keywords_attribute_calls_and_mismatched_results_decline(self):
        for expression in ('captured(1)', 'captured(size=1)', 'captured(*())',
                           'captured(**{})', 'holder.captured()'):
            with self.subTest(expression=expression):
                model, plan, node, output = fixture(expression=expression)
                self.assertFalse(_native_reader_call(model, plan, node, output))
        model, plan, node, output = fixture(result='str')
        self.assertFalse(_native_reader_call(model, plan, node, output))
        with self.assertRaises(Unproved):
            _model_proof(model)
        del model.records[0, id(node.func)]
        self.assertFalse(_native_reader_call(model, plan, node, output))

    def test_mixed_reader_and_source_family_is_never_reclassified(self):
        model, plan, node, output = fixture()
        model.records[0, id(node.func)] = Cell('union',
            (Cell('reader_bytes'), Cell(AotFunctionType((12,)))))
        self.assertFalse(_native_reader_call(model, plan, node, output))
        with self.assertRaises(Unproved):
            _model_proof(model)

    def test_saved_limit_observers_and_lifetime_barriers_still_reject(self):
        model, _, _, _ = fixture()
        setter = BuiltinRef('sys', 'setrecursionlimit')
        model.callable_cells.member_used.add(setter)
        with self.assertRaisesRegex(Unproved, 'recursion-limit'):
            _model_proof(model)
        model.callable_cells.member_used.clear()
        model.records[0, -1] = Cell(AotFunctionType((), (), (setter,)))
        with self.assertRaisesRegex(Unproved, 'recursion-limit'):
            _model_proof(model)
        del model.records[0, -1]
        model.gc_classes = ('observed',)
        with self.assertRaisesRegex(Unproved, 'finalizer'):
            _model_proof(model)
        model.gc_classes = ()
        model.generators.records.append(object())
        with self.assertRaisesRegex(Unproved, 'generator'):
            _model_proof(model)

    def test_finite_source_and_physical_positive_depth_cycles_remain_required(self):
        model, _, _, _ = fixture()
        model.native_call_heights = {}
        with self.assertRaisesRegex(Unproved, 'finite acyclic height'):
            _model_proof(model)
        model.native_call_heights = {0: 1}
        model.synchronous_calls = set()
        with self.assertRaisesRegex(Unproved, 'synchronous chain'):
            _model_proof(model)
        with self.assertRaisesRegex(Unproved, 'physical recursion'):
            _weighted_bounds({0: {1}, 1: {0}}, {0: 1, 1: 0})
        bounds, _ = _weighted_bounds({0: {0}, 1: {0}}, {0: 0, 1: 2})
        self.assertEqual(bounds[1], 2)


if __name__ == '__main__':
    testing.main()
