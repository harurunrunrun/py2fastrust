"""Canonical metadata aliases retain real mutable module namespace bindings."""
import unittest,shutil
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests
CASES={'module_alias_saved': 'import typing\n'
                       'Saved=typing.Tuple\n'
                       'typing.Tuple=typing.List\n'
                       'print(typing.cast(Saved[int,str],7),typing.cast(typing.Tuple[int],8))\n',
 'module_alias_validation_error': 'import typing\n'
                                  'typing.Tuple=typing.Dict\n'
                                  'print(typing.cast(typing.Tuple[int],7))\n',
 'module_alias_deleted': 'import typing\n'
                         'Saved=typing.Tuple\n'
                         'del typing.Tuple\n'
                         'print(typing.cast(Saved[int],7))\n'
                         'print(typing.cast(typing.Tuple[int],8))\n',
 'constructed_alias_survives_deleted_export': 'import typing\n'
                                              'Alias=typing.Tuple[int,str]\n'
                                              'del typing.Tuple\n'
                                              'print(typing.cast(Alias,7))\n',
 'module_receiver_captured_before_index': 'import typing\n'
                                          'def change():\n'
                                          ' typing.Tuple=typing.List\n'
                                          ' print("change")\n'
                                          ' return int\n'
                                          'print(typing.cast(typing.Tuple[change(),str],7))\n'
                                          'print(typing.cast(typing.Tuple[int],8))\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class ModuleAliasMetadata(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_module_alias_saved(self):self.check('module_alias_saved')
    def test_module_alias_validation_error(self):self.check('module_alias_validation_error')
    def test_module_receiver_captured_before_index(self):self.check('module_receiver_captured_before_index')

class ExistingModuleDeletionBoundaries(unittest.TestCase):
    def test_metadata_does_not_erase_unimplemented_module_deletion(self):
        for name in ('constructed_alias_survives_deleted_export','module_alias_deleted'):
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(CASES[name],TranspileOptions(integer=mode,filename="metadata_module_deletion.py",license="none"))
                    self.assertFalse(result.success)
                    self.assertIn('attribute-deletion protocol',result.diagnostics[0].message)
                    self.assertIn('typing.Tuple',result.diagnostics[0].message)
