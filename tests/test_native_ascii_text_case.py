"""Builtin case conversion, overriding methods, and eager error arguments."""
import shutil
import unittest

from py2fastrust import transpile,TranspileOptions
from tests import test_native_classes as _classes


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class AsciiTextCaseTests(unittest.TestCase):
    compile=_classes.NativeClassTests.compile
    compare=_classes.NativeClassTests.compare

    def test_ascii_strings_without_class_definitions(self):
        self.compare("s='Abc Z9!';print(s.upper(),s.lower(),s)\n")

    def test_finite_str_bytes_alternatives(self):
        self.compare("def show(flag):\n value='aB' if flag else b'cD'\n print(value.upper(),value.lower())\nshow(True)\nshow(False)\n")

    def test_non_ascii_bytes_are_not_case_mapped(self):
        self.compare("print(b'AbC \\xff'.upper(),b'AbC \\xff'.lower())\n")

    def test_receiver_and_argument_effects_precede_type_error(self):
        self.compare("def owner():\n print('owner')\n return 'Cat'\ndef argument():\n print('argument')\n return 1\nprint(owner().upper(argument()))\n")

    def test_same_named_class_method_keeps_normal_dispatch(self):
        self.compare("class Text:\n def upper(self, value):return value+19\nprint(Text().upper(2))\n")

    def test_unicode_mapping_gap_has_a_specific_diagnostic(self):
        result=transpile("print('Straße'.upper())\n",TranspileOptions(string_mode='unicode'))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('str.upper()',result.diagnostics[0].message)
        self.assertIn('case-mapping',result.diagnostics[0].message)


if __name__=='__main__':unittest.main()
