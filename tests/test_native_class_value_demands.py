"""Eliding an actual class argument requires a use and call-point proof."""
import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_class_value_demands as demands
import test_native_private_module_demands as context_tests
from test_native_private_module_demands import BASE, MAIN
import test_native_lambda_callbacks as helpers


class ClassValueDemandEvidence(unittest.TestCase):
    def convert(self, library):
        observed = []
        original = demands.prepare
        def prepare(model):
            original(model)
            observed.append(model)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'arithmetic.py').write_text(library)
            with patch.object(demands, 'prepare', prepare):
                result = transpile(MAIN, TranspileOptions(filename=str(root / 'main.py'), license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(observed)
        return result, observed[-1]

    def test_static_construction_omits_only_the_private_class_argument(self):
        result, model = self.convert(BASE)
        indices = [index for index, abi in model.source_state.abis.items()
                   if abi.plan.node.name == '__mul__']
        self.assertTrue(indices)
        for index in indices:
            self.assertIn(index, model.erased_class_contexts)
            private = re.search(r'fn class_state_function_'+str(index)+r'\(([^\n]*)\)->', result.rust_source)
            # Dead public entries can be pruned from the final single file.
            ordinary_source = model.emitter(model.source_state.abis[index].plan).generate()
            ordinary = re.search(r'fn class_function_'+str(index)+r'\(([^\n]*)\)->', ordinary_source)
            self.assertIsNotNone(private)
            self.assertIsNotNone(ordinary)
            self.assertNotIn('class_defining_class:', private.group(1))
            self.assertIn('class_defining_class:', ordinary.group(1))

    def test_a_real_class_value_use_keeps_the_private_argument(self):
        _, model = self.convert(BASE.replace('return Quantity(self.value * factor)',
            'assert Quantity is Quantity; return Quantity(self.value * factor)'))
        indices = [index for index, abi in model.source_state.abis.items()
                   if abi.plan.node.name == '__mul__']
        self.assertTrue(indices)
        self.assertTrue(all(index not in model.erased_class_contexts for index in indices))

    def test_a_constructor_needing_its_module_keeps_the_actual_class_context(self):
        _, model = self.convert('OFFSET = 11\n' + BASE.replace(
            'value + Context.current()', 'value + Context.current() + OFFSET'))
        quantity = next(owner for owner in model.classes.values() if owner.node.name == 'Quantity')
        self.assertFalse(demands.marker_constructor(model, quantity))
        self.assertTrue(all(index not in model.erased_class_contexts
            for index, abi in model.source_state.abis.items() if abi.plan.node.name == '__mul__'))


@unittest.skipUnless(helpers.shutil.which('rustc'), 'rustc is required')
class ClassValueDemandExecution(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = context_tests.PrivateDemandExecution.exercise

    def test_static_private_arguments_and_unelided_values_keep_python_results(self):
        for library in (BASE,
                BASE.replace('return Quantity(self.value * factor)',
                    'assert Quantity is Quantity; return Quantity(self.value * factor)'),
                'OFFSET = 11\n' + BASE.replace('value + Context.current()',
                    'value + Context.current() + OFFSET')):
            with self.subTest(library=library):
                self.exercise(library, ('7\n', '-2\n', 'bad\n'))


if __name__ == '__main__':
    unittest.main()
