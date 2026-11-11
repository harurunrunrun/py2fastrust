"""Class-name elision requires closed publication and an actual state producer."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.native_source_class_bindings import builtin_value, publication_closed, certify
from py2fastrust.native_classes import Model
from py2fastrust import transpile, TranspileOptions
from test_native_immediate_operand_capture import SOURCES


def fixture(body):
    owner = SimpleNamespace(node=ast.parse('class Owner:\n' + body).body[0], body_plan=object())
    state = SimpleNamespace(model=object(), class_root=lambda actual: actual is owner,
                            kind=lambda plan, node: None)
    return state, owner


class ClosedPublicationTests(unittest.TestCase):
    def test_literal_values_are_closed_but_no_expressions_are_evaluated(self):
        for text in ('None', 'True', '-3', '+2.5', "b'x'", "'x'", '[]', '(1, False)', '{1, 2}', "{'a': [1, None]}"):
            with self.subTest(text=text):
                self.assertTrue(builtin_value(ast.parse(text, mode='eval').body))
        for text in ('Other', 'Descriptor()', 'module.value', '[f()]', '{**other}', '[x for x in []]'):
            with self.subTest(text=text):
                self.assertFalse(builtin_value(ast.parse(text, mode='eval').body))

    def test_plain_body_and_deferred_annotations_are_closed(self):
        state, owner = fixture(' "doc"\n values = []\n count: deferred() = 2\n flag: other()\n def read(self, x=1, *, y=None) -> annotation():\n  return self.count\n')
        self.assertTrue(publication_closed(state, owner))

    def test_class_creation_callbacks_and_effectful_defaults_are_not_closed(self):
        bodies = (' value = Descriptor()\n', ' value = saved_descriptor\n',
                  ' value = module.descriptor\n', ' class Nested: pass\n',
                  ' def read(self, value=effect()): pass\n',
                  ' def read(self, *, value=effect()): pass\n',
                  ' @decorate\n def read(self): pass\n',
                  ' @decorate()\n def read(self): pass\n',
                  ' def read[T](self): pass\n')
        for body in bodies:
            with self.subTest(body=body):
                state, owner = fixture(body)
                self.assertFalse(publication_closed(state, owner))

    def test_classmethod_requires_its_original_builtin_identity(self):
        from py2fastrust.references import BuiltinIdentity
        from py2fastrust.native_aot_callables import AotFunctionType
        state, owner = fixture(' @alias\n def read(cls): return cls.values[-1]\n')
        state.kind = lambda plan, node: AotFunctionType.from_targets((BuiltinIdentity('classmethod'),))
        self.assertTrue(publication_closed(state, owner))
        state.kind = lambda plan, node: AotFunctionType.from_targets((BuiltinIdentity('staticmethod'),))
        self.assertFalse(publication_closed(state, owner))

    def test_missing_original_root_or_class_body_plan_is_not_closed(self):
        state, owner = fixture(' pass\n')
        state.class_root = lambda actual: None
        self.assertFalse(publication_closed(state, owner))
        state.class_root = lambda actual: object()
        owner.body_plan = None
        self.assertFalse(publication_closed(state, owner))

    def test_missing_model_or_producer_does_not_supply_a_binding(self):
        self.assertIsNone(certify(SimpleNamespace(), SimpleNamespace(), 'Owner'))
        self.assertIsNone(certify(SimpleNamespace(model=object(), producers={}),
                                  SimpleNamespace(owner=object()), 'Owner'))


class ActualPublicationTests(unittest.TestCase):
    def convert(self, source, mode='i64'):
        models = []
        original = Model.run
        def observe(model):
            result = original(model)
            models.append(model)
            return result
        with patch.object(Model, 'run', observe):
            result = transpile(source, TranspileOptions(integer=mode, license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, 'native')
        self.assertTrue(models)
        return result, models[-1]

    def test_real_state_witnesses_remove_only_the_proved_name_presence_read(self):
        for mode in ('i64', 'i128', 'bigint'):
            with self.subTest(mode=mode):
                result, model = self.convert(SOURCES['manager_helper_constructor_boolean'], mode)
                accesses = model.operand_demands.accesses
                self.assertTrue(accesses)
                self.assertTrue(all(access.binding is not None for access in accesses))
                self.assertNotIn('class_operand_namespace', result.rust_source)
                for access in accesses:
                    proof = access.binding
                    self.assertIs(proof.state, model.source_state)
                    self.assertTrue(proof.producers)
                    self.assertIs(proof.owner, proof.slot.owner)
                    self.assertIs(proof.slot, proof.state.slots[proof.slot.key])

    def test_a_captured_alias_still_requires_actual_producer_evidence(self):
        source = SOURCES['manager_helper_constructor_boolean'].replace(
            'Switches.active.append(self.value)', 'Alias.active.append(self.value)')
        source = source.replace('class Reading:', 'Alias=Switches\nclass Reading:')
        _, model = self.convert(source)
        self.assertTrue(model.operand_demands.accesses)
        self.assertTrue(all(access.binding is not None for access in model.operand_demands.accesses))

    def test_missing_publication_evidence_preserves_original_presence_check(self):
        with patch('py2fastrust.native_source_class_bindings.certify', return_value=None):
            result, model = self.convert(SOURCES['manager_helper_constructor_boolean'])
        self.assertTrue(model.operand_demands.accesses)
        self.assertTrue(all(access.binding is None for access in model.operand_demands.accesses))
        self.assertIn('class_operand_namespace', result.rust_source)


if __name__ == '__main__':
    unittest.main()
