"""Static class identity never follows an ordinal across generations."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.native_sealed_class_identity import match


class SealedClassIdentityContracts(unittest.TestCase):
    def fixture(self):
        actual,other = object(),object()
        model = SimpleNamespace()
        model.source_state = SimpleNamespace(model=model,barrier=None,class_root=lambda owner: True)
        return model,actual,other

    def test_only_the_actual_same_owner_is_equal(self):
        model,actual,other = self.fixture()
        with patch('py2fastrust.native_class_binding_contexts.owner',return_value=actual), \
             patch('py2fastrust.native_value_classes.selected',return_value=True):
            self.assertTrue(match(model,object(),actual))
            self.assertFalse(match(model,object(),other))

    def test_repeated_import_or_foreign_model_never_establishes_identity(self):
        model,actual,_ = self.fixture()
        model.source_state.barrier = 'module can execute again'
        self.assertIsNone(match(model,object(),actual))
        model.source_state.barrier = None
        model.source_state.model = object()
        self.assertIsNone(match(model,object(),actual))

    def test_missing_context_reference_layout_or_class_binding_keeps_dynamic_identity(self):
        model,actual,other = self.fixture()
        with patch('py2fastrust.native_class_binding_contexts.owner',return_value=None):
            self.assertIsNone(match(model,object(),actual))
        with patch('py2fastrust.native_class_binding_contexts.owner',return_value=actual), \
             patch('py2fastrust.native_value_classes.selected',return_value=False):
            self.assertIsNone(match(model,object(),actual))
        with patch('py2fastrust.native_class_binding_contexts.owner',return_value=actual), \
             patch('py2fastrust.native_value_classes.selected',return_value=True):
            model.source_state.class_root = lambda owner: owner is actual
            self.assertIsNone(match(model,object(),other))


if __name__=='__main__':
    unittest.main()
