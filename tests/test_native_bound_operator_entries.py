"""Numeric operator demands belong to the actually bound specialization."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_class_value_demands as demands
from py2fastrust.native_call_context_effects import source_plan
import test_native_private_module_demands as contexts
import test_native_finite_depth_calls as projects
import test_native_lambda_callbacks as helpers

LIBRARY = contexts.BASE.replace('def __mul__(self, factor): return Quantity(self.value * factor)', '''def __mul__(self, factor):
  if isinstance(factor, Quantity): return Quantity(self.value * factor.value)
  return Quantity(self.value * factor)''')
MAIN = '''from arithmetic import Context, Quantity
with Context(7):
 value = Quantity(2)
 print((value * Quantity(4)).value, (value * 3).value)
'''


class BoundOperatorEntryEvidence(unittest.TestCase):
    def test_unselected_generic_signature_does_not_force_an_owner_value(self):
        observed = []
        original = demands.direct_operator
        def direct(emitter, node, phase, arguments, wanted):
            result = original(emitter, node, phase, arguments, wanted)
            active = getattr(emitter, 'source_state_active', None)
            if active is not None and phase.member.name == '__mul__':
                state = emitter.model.source_state
                targets = [state.abis[index].plan for index in active[0].calls.get(id(node), ())
                    if index in state.abis and source_plan(state.abis[index].plan) is source_plan(phase.member.plan)]
                observed.append((result is not None, any(target.index not in emitter.model.erased_class_contexts
                    for target in targets)))
            return result
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'arithmetic.py').write_text(LIBRARY)
            with patch.object(demands, 'direct_operator', direct):
                result = transpile(MAIN, TranspileOptions(filename=str(root/'main.py'), license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn((True, True), observed)


@unittest.skipUnless(helpers.shutil.which('rustc'), 'rustc is required')
class BoundOperatorEntryExecution(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise_project = projects.NativeFiniteDepthTests.exercise_project

    def test_both_typed_operands_keep_the_original_numeric_method(self):
        self.exercise_project(MAIN, files={'arithmetic.py': LIBRARY})


if __name__ == '__main__':
    unittest.main()
