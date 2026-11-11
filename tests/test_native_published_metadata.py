"""Hoisted class metadata belongs to the actual original class publication."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_published_metadata as metadata
from test_native_single_execution_metadata import CASES
import test_native_lambda_callbacks as helpers
import test_native_finite_depth_calls as projects


class PublicationContracts(unittest.TestCase):
    def test_absent_or_rejected_generation_keeps_the_existing_layout(self):
        for state in (None, SimpleNamespace(barrier='can retry a module')):
            model = SimpleNamespace(source_state=state)
            metadata.prepare(model)
            self.assertEqual(model.published_metadata, set())
            self.assertIsNone(metadata.layout(model, SimpleNamespace(index=1)))
            self.assertEqual(metadata.publication(SimpleNamespace(model=model),
                                                SimpleNamespace(index=1), 'actual'), '')

    def test_original_owner_and_closed_publication_are_both_required(self):
        left = SimpleNamespace(index=1, used=True)
        right = SimpleNamespace(index=2, used=True)
        hidden = SimpleNamespace(index=3, used=False)
        model = SimpleNamespace(source_state=SimpleNamespace(barrier=None),
                                classes={'a': left, 'b': right, 'c': hidden})
        with patch('py2fastrust.native_value_classes.selected', return_value=True), \
             patch('py2fastrust.native_source_class_bindings.publication_closed',
                   side_effect=lambda state, owner: owner is left):
            metadata.prepare(model)
        self.assertEqual(model.published_metadata, {1})
        member, initialize, runtime = metadata.layout(model, left)
        self.assertEqual(member, 'class_definition:ClassValueMetadata_1')
        self.assertEqual(initialize, 'class_definition:ClassValueMetadata_1')
        self.assertIn('fn class_publish_metadata_1(value:&ClassClassRef)', runtime)
        self.assertNotIn('fn class_value_metadata_1(', runtime)
        self.assertEqual(metadata.publication(SimpleNamespace(model=model), left, 'actual'),
                         'class_publish_metadata_1(&actual);')


class PublicationLayouts(unittest.TestCase):
    def convert_project(self, key, mode):
        # Reuse the existing source files and converter, rather than matching
        # source spellings or editing generated programs in this test.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, source in CASES[key].items():
                (root / name).write_text(source)
            path = root / 'main.py'
            result = transpile(path.read_text(), TranspileOptions(filename=str(path), integer=mode))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, 'native')
        return result.rust_source

    def test_direct_import_initializes_each_class_at_publication(self):
        for mode in ('i64', 'i128', 'bigint'):
            with self.subTest(mode=mode):
                source = self.convert_project('plain_module_chain', mode)
                self.assertIn('class_publish_metadata_', source)
                self.assertNotIn('fn class_value_metadata_', source)

    def test_control_flow_and_failed_retry_keep_generation_capable_layout(self):
        for key in ('conditional_import', 'loop_import', 'map_stop_failed_retry',
                    'with_suppressed_failed_retry'):
            with self.subTest(key=key):
                source = self.convert_project(key, 'i64')
                self.assertNotIn('class_publish_metadata_', source)
                self.assertIn('(Option<ClassClassRef>)', source)


@unittest.skipUnless(helpers.shutil.which('rustc'), 'rustc is required')
class PublicationExecution(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise_project = projects.NativeFiniteDepthTests.exercise_project

    def test_failed_constructor_then_success_still_has_original_class(self):
        self.exercise_project('''class Guard:
 def __enter__(self): return None
 def __exit__(self, kind, error, trace): return True
class Token:
 def __init__(self, value): self.value = 10 // value
 def read(self): return self.value
with Guard():
 Token(0)
value = Token(2)
print(value.read(), isinstance(value, Token))
''', files={})

    def test_two_value_classes_keep_their_distinct_metadata(self):
        self.exercise_project('''class First:
 def __init__(self, value): self.value = value
class Second:
 def __init__(self, value): self.value = value
a = First(3)
b = Second(8)
print(a.value, b.value, isinstance(a, First), isinstance(a, Second), isinstance(b, Second))
''', files={})


if __name__ == '__main__':
    unittest.main()
