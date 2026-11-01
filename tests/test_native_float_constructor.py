"""Float constructor calls retain numeric, parser and captured-value semantics."""
import shutil
import unittest
from py2fastrust import TranspileOptions,transpile
from tests import test_native_heapq as helpers

SOURCES={'input_float_original_witness': ('print(float(input()))\n', ' -1.25e+2 \n'),
 'frame_input_float_original_witness': ('class Reader:\n'
                                        ' def run(self):return float(input())\n'
                                        'print(Reader().run())\n',
                                        ' -1.25e+2 \n'),
 'rounding_integer_boundaries_within_every_width': ('for value in '
                                                    '[9007199254740991,9007199254740992,9007199254740993,9007199254740995,9223372036854775807]:\n'
                                                    ' print(float(value),float(-value))\n',
                                                    ''),
 'captured_constructor_survives_name_rebinding': ('convert=float\n'
                                                  'def replacement(value):return 99.0\n'
                                                  'float=replacement\n'
                                                  "print(convert('1.25'),float('1.25'),convert())\n",
                                                  ''),
 'finite_scalar_argument_alternatives': ('def convert(value):return float(value)\n'
                                         "print(convert(4),convert('2.5'),convert(b'3.75'),convert(-0.0),convert(True))\n",
                                         ''),
 'byte_reader_map_constructor': ('import sys\n'
                                 'convert=float\n'
                                 'values=list(map(convert,sys.stdin.buffer.readline().split()))\n'
                                 'print(values)\n',
                                 '1.25 -0 2e2\n'),
 'invalid_text_preserves_original_repr': ("print('before')\n"
                                          'print(float(\'bad\\\'"\\\\\\x00\'))\n',
                                          ''),
 'invalid_bytes_preserve_bytes_repr': ('print(\'before\')\nprint(float(b"bad\'\\"\\x00"))\n', ''),
 'keyword_binding_error_follows_effects': ('def value():\n'
                                           " print('argument')\n"
                                           " return '2.5'\n"
                                           'print(float(x=value()))\n',
                                           ''),
 'excess_arguments_follow_both_effects': ('def value(label):\n'
                                          ' print(label)\n'
                                          ' return 4\n'
                                          "print(float(value('first'),value('second')))\n",
                                          ''),
 'zero_bool_defaults_and_signed_zero': ('print(float(),float(False),float(True),float(7),float(-9),float(1.25))\n'
                                        "print(format(float(-0.0),'+g'),format(float(),'+g'))\n",
                                        '')}
BIGINT_SOURCES={'exact_bigint_rounding_9': ('number=int(input())\n'
                             'expected=float(input())\n'
                             'converted=float(number)\n'
                             "print(converted==expected,format(converted,'+g')==format(expected,'+g'))\n",
                             '179769313486231580793728971405303415079934132710037826936173778980444968292764750946649017977587207096330286416692887910946555547851940402630657488671505820681908902000708383676273854845817711531764475730270069855571366959622842914819860834936475292719074168444365510704342711559699508093042880177904174497791\n'
                             '1.7976931348623157e+308\n'),
 'bigint_overflow_0': ("print('before')\nnumber=int(input())\nprint(float(number))\n",
                       '179769313486231580793728971405303415079934132710037826936173778980444968292764750946649017977587207096330286416692887910946555547851940402630657488671505820681908902000708383676273854845817711531764475730270069855571366959622842914819860834936475292719074168444365510704342711559699508093042880177904174497792\n')}

class FloatConstructorProofTests(unittest.TestCase):
    def test_custom_numeric_conversion_methods_are_positioned_diagnostics(self):
        for method in ('__float__','__index__'):
            source='class Number:\n def '+method+'(self):return 1\nprint(float(Number()))\n'
            for mode in ('i64','i128','bigint'):
                with self.subTest(method=method,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertIn(method,result.diagnostics[0].message)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FloatConstructorExecutionTests(unittest.TestCase):
    def compare(self,name):
        source,data=SOURCES[name]
        helpers.HeapExecutionTests.compare(self,source,(data,))

    def test_input_float_original_witness(self):
        self.compare('input_float_original_witness')

    def test_frame_input_float_original_witness(self):
        self.compare('frame_input_float_original_witness')

    def test_rounding_integer_boundaries_within_every_width(self):
        self.compare('rounding_integer_boundaries_within_every_width')

    def test_captured_constructor_survives_name_rebinding(self):
        self.compare('captured_constructor_survives_name_rebinding')

    def test_finite_scalar_argument_alternatives(self):
        self.compare('finite_scalar_argument_alternatives')

    def test_byte_reader_map_constructor(self):
        self.compare('byte_reader_map_constructor')

    def test_invalid_text_preserves_original_repr(self):
        self.compare('invalid_text_preserves_original_repr')

    def test_invalid_bytes_preserve_bytes_repr(self):
        self.compare('invalid_bytes_preserve_bytes_repr')

    def test_keyword_binding_error_follows_effects(self):
        self.compare('keyword_binding_error_follows_effects')

    def test_excess_arguments_follow_both_effects(self):
        self.compare('excess_arguments_follow_both_effects')

    def test_zero_bool_defaults_and_signed_zero(self):
        self.compare('zero_bool_defaults_and_signed_zero')

    def test_bigint_rounding_limit_and_overflow(self):
        for source,data in BIGINT_SOURCES.values():
            helpers.HeapExecutionTests.compare(self,source,(data,),modes=("bigint",))

if __name__=='__main__':
    unittest.main()
