"""Native literal-format fields preserve eager arguments and error stages."""
import shutil
import unittest
import test_native_class_iterators as helpers

from py2fastrust import transpile


CASES={
 'roots_and_extra':'print("{1} {first} {0}".format(3,"x",7,first=[1,2],unused=9))\n',
 'automatic_escaping':'print("{{start}} {} / {} {{end}}".format(3,"x"))\n',
 'conversion_fields':'print("{0!s}|{0!r}|{0!a}".format("a\\nb"))\n',
 'unicode_conversions':'print("{0!s}|{0!r}|{0!a}".format("β😊"))\n',
 'unicode_numeric_fields':'print("{٠}|{١}".format(3,4))\n',
 'numeric_specs':'print("{0:+#x}|{1:08b}|{2:.3f}".format(17,-3,1.25))\n',
 'nested_auto_spec':'print("{:{}}".format(7,4))\n',
 'nested_manual_spec':'print("{0:0{1}d}|{who!r}".format(7,4,who="x"))\n',
 'none_bytes_containers':'print("{}|{}|{}|{}".format(None,b"x",(1,2),{"a":3}))\n',
 'eager_unused_arguments':'def note(tag):\n print(tag,end="|")\n return 7\nprint("literal".format(note("first"),note("second"),extra=note("third")))\n',
 'eager_before_missing':'def note(tag):\n print(tag,end="|")\n return 7\nprint("{3}".format(note("first"),unused=note("keyword")))\n',
 'positional_missing':'print("{2}".format(3))\n',
 'keyword_missing':'print("{missing}".format(3))\n',
 'keyword_before_bad_conversion':'print("{missing!q}".format(3))\n',
 'bad_conversion':'print("{0!q}".format(3))\n',
 'manual_to_auto':'print("{0} {}".format(3,4))\n',
 'auto_to_manual':'print("{} {1}".format(3,4))\n',
 'malformed_after_field':'print("{0} {".format(3))\n',
 'unclosed_field':'print("{0".format(3))\n',
 'huge_field_index':'print("{999999999999999999999999999999}".format(3))\n',
 'depth_limit':'print("{0:{1:{2}}}".format(1,2))\n',
 'string_spec_error':'print("{:d}".format("x"))\n',
 'bytes_spec_error':'print("{:d}".format(b"x"))\n',
 'constructor_field_fixed_point':'class Values:\n def __init__(self,n):self.n=n\n def describe(self,p):return "p={0}, n={1}".format(p,self.n)\nprint(Values(9).describe(3))\n',
}


class TextFormatProtocolTests(unittest.TestCase):
    def test_unimplemented_template_protocols_are_explicit(self):
        for source,detail in (
            ('template="{}"\nprint(template.format(3))\n','nonliteral template'),
            ('print("{0.real}".format(3))\n','attribute or subscript traversal'),
            ('print("{0[0]}".format([3]))\n','attribute or subscript traversal')):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn(detail,str(result.diagnostics[0]))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TextFormatExecutionTests(unittest.TestCase):
    cases=CASES
    check=helpers.IteratorExecutionTests.check

    def test_roots_conversions_and_specs(self):
        for name in ('roots_and_extra','automatic_escaping','conversion_fields','numeric_specs',
                     'nested_auto_spec','nested_manual_spec','none_bytes_containers','constructor_field_fixed_point'):
            with self.subTest(name=name):self.check(name)

    def test_unicode(self):
        for name in ('unicode_conversions','unicode_numeric_fields'):
            with self.subTest(name=name):self.check(name)

    def test_arguments_precede_field_processing(self):
        for name in ('eager_unused_arguments','eager_before_missing'):
            with self.subTest(name=name):self.check(name)

    def test_field_lookup_and_conversion_errors(self):
        for name in ('positional_missing','keyword_missing','keyword_before_bad_conversion','bad_conversion',
                     'manual_to_auto','auto_to_manual'):
            with self.subTest(name=name):self.check(name)

    def test_parse_and_specification_errors(self):
        for name in ('malformed_after_field','unclosed_field','huge_field_index','depth_limit','string_spec_error','bytes_spec_error'):
            with self.subTest(name=name):self.check(name)
