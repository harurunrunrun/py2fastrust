"""Module completion requires a real anchor and no early source publication."""
import ast
from types import SimpleNamespace
import unittest

import test_native_binding_places as places
import test_native_lambda_callbacks as helpers
import test_native_finite_depth_calls as projects

from py2fastrust.frontend import build_program
from py2fastrust.native_source_module_publication import declarations

LIBRARY = '''class Number:
 def __init__(self, value): self.value = value
 def combine(self, other):
  assert isinstance(other, Number)
  return pack(self.value + other.value)
def pack(value): return Number(value)
'''
MAIN = 'from library import Number\nprint(Number(8).combine(Number(13)).value)\n'


class ModulePublicationIntegration(unittest.TestCase):
    def test_actual_imported_class_seals_the_later_function_definition(self):
        result, observed = places.compile_project({'main.py':MAIN,'library.py':LIBRARY})
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(observed)
        self.assertTrue(any(row['key'][0]=='source_published' for row in observed))

    def test_an_early_module_call_keeps_original_binding_presence(self):
        early = LIBRARY.replace('def pack(value):',
            'print("before")\nNumber(1).combine(Number(2))\ndef pack(value):')
        result, observed = places.compile_project({'main.py':MAIN,'library.py':early})
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(observed)
        self.assertTrue(all(row['key'][0]=='check_presence' for row in observed))


@unittest.skipUnless(helpers.shutil.which('rustc'),'rustc is required')
class ModulePublicationExecution(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise_project = projects.NativeFiniteDepthTests.exercise_project

    def test_declarations_complete_before_external_method_entry(self):
        self.exercise_project(MAIN,files={'library.py':LIBRARY})

    def test_early_name_error_stays_before_later_definition(self):
        early = LIBRARY.replace('def pack(value):',
            'print("before")\nNumber(1).combine(Number(2))\ndef pack(value):')
        self.exercise_project(MAIN,files={'library.py':early})


class ModuleDeclarationContracts(unittest.TestCase):
    def examine(self, source):
        unit=build_program(source,'declarations.py').main
        owners={node.name:SimpleNamespace(node=node,body_plan=object())
                for node in unit.tree.body if isinstance(node,ast.ClassDef)}
        state=SimpleNamespace(model=SimpleNamespace(unit=unit,classes=owners),
                              class_root=lambda owner:True)
        return declarations(state,unit)

    def test_deferred_annotations_and_original_declarations_do_not_call_user_code(self):
        self.assertIsNotNone(self.examine('''import typing
count: missing_annotation() = 3
class Item:
 value = []
 def read(self, value=2): return value
def factory(value=1): return Item()
'''))

    def test_eager_source_calls_and_control_flow_keep_binding_checks(self):
        for source in ('notify()\n', 'with Guard():\n pass\n',
                       'if ready:\n notify()\n', 'for item in []:\n pass\n',
                       'seed = make()\n', 'def f(value=make()): pass\n',
                       '@decorate\ndef f(): pass\n', 'alias.value = 1\n'):
            with self.subTest(source=source):
                self.assertIsNone(self.examine(source))

    def test_class_descriptors_and_effectful_method_defaults_can_publish_early(self):
        for source in ('class Item:\n value = Descriptor()\n',
                       'class Item:\n value = existing_descriptor\n',
                       'class Item:\n def method(self, value=make()): pass\n'):
            with self.subTest(source=source):
                self.assertIsNone(self.examine(source))


if __name__=='__main__':
    unittest.main()
