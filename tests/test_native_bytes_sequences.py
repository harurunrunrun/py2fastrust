"""Immutable byte operators retain octets, effects and checked native lengths."""
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_constraints import Solver
import test_native_integer_digit_limits as digits

# CPython executes the original operations; the independent existing oracle
# only normalizes integer results to the selected fixed-width policy.
CASES = {'raw_octets_concat': ('print(b"a\\x00"+b"\\xff\\x85")\n', ('',)),
 'repeat_then_concat': ('value=b"9"*4+b"\\x00bad"\nprint(value,len(value))\n', ('',)),
 'concat_then_repeat': ('print((b"a"+b"\\xff")*3)\nprint(3*(b"\\x00"+b"z"))\n', ('',)),
 'boolean_and_negative_counts': ('for count in [False,True,-2,0,1,3]:\n'
                                 ' print(b"\\x00\\xff"*count)\n',
                                 ('',)),
 'empty_huge_count': ('print(b""*(1<<100))\n', ('',)),
 'nonempty_huge_count': ('print(b"x"*(1<<64))\n', ('',)),
 'immutable_alias_content': ('value=b"ab"\n'
                             'alias=value\n'
                             'value+=b"\\x00"\n'
                             'print(alias,value,alias==value)\n'
                             'value*=2\n'
                             'print(alias,value)\n',
                             ('',)),
 'bytearray_snapshot': ('source=bytearray(b"ab")\n'
                        'first=b"X"+source\n'
                        'second=source+b"Y"\n'
                        'source[0]=90\n'
                        'print(source,first,second)\n',
                        ('',)),
 'bytearray_inplace_alias': ('source=bytearray(b"ab")\n'
                             'alias=source\n'
                             'source+=b"\\xff"\n'
                             'source*=2\n'
                             'print(source,alias,source is alias)\n',
                             ('',)),
 'left_right_effects': ('def mark(label,value):\n'
                        ' print(label)\n'
                        ' return value\n'
                        'print(mark("left",b"a")+mark("right",b"\\x00"))\n'
                        'print(mark("source",b"b")*mark("count",3))\n'
                        'print(mark("count-first",2)*mark("source-second",b"\\xff"))\n',
                        ('',)),
 'concat_type_error_after_effects': ('def mark(label,value):\n'
                                     ' print(label)\n'
                                     ' return value\n'
                                     'print(mark("left",b"a")+mark("right","text"))\n',
                                     ('',)),
 'repeat_type_error_after_effects': ('def mark(label,value):\n'
                                     ' print(label)\n'
                                     ' return value\n'
                                     'print(mark("source",b"a")*mark("count",1.5))\n',
                                     ('',)),
 'reverse_repeat_type_error': ('print(1.5*b"a")\n', ('',)),
 'left_error_stops_right': ('def later():\n print("later")\n return b"a"\nprint((1//0)*later())\n',
                            ('',)),
 'right_error_after_source': ('def earlier():\n'
                              ' print("source")\n'
                              ' return b"a"\n'
                              'print(earlier()*(1//0))\n',
                              ('',)),
 'finite_bytes_or_none': ('value=b"a"if int(input())else None\nprint(value+b"b")\n',
                          ('0\n', '1\n')),
 'function_returned_payload': ('def repeat(value,count):return value*count\n'
                               'print(repeat(b"\\x00",3)+repeat(b"\\xff",2))\n',
                               ('',)),
 'class_field_payload': ('class Buffer:\n'
                         ' def __init__(self):self.data=b"A"\n'
                         ' def append(self,tail):self.data=self.data+tail\n'
                         ' def repeat(self,count):return self.data*count\n'
                         'value=Buffer()\n'
                         'value.append(b"\\x00")\n'
                         'value.append(b"\\xff")\n'
                         'print(value.data,value.repeat(2))\n',
                         ('',)),
 'empty_operands': ('print(b""+b"",b""+b"\\xff",b"\\0"+b"")\n', ('',)),
 'repeat_length_overflow': ('print(b"xx"*(1<<62))\n', ('',)),
 'negative_huge_repeat': ('print(b""*(-(1<<100)))\n', ('',)),
 'reverse_concat_error_effects': ('def mark(label,value):\n'
                                  ' print(label)\n'
                                  ' return value\n'
                                  'print(mark("text","a")+mark("bytes",b"b"))\n',
                                  ('',)),
 'mutable_field_alias': ('class Buffer:\n'
                         ' def __init__(self):self.data=bytearray(b"a")\n'
                         'value=Buffer()\n'
                         'alias=value.data\n'
                         'joined=b"\\0"+value.data\n'
                         'value.data+=b"\\xff"\n'
                         'print(joined,alias,value.data)\n',
                         ('',)),
 'evaluated_owner_before_rebind': ('source=b"a"\n'
                                   'def change():\n'
                                   ' global source\n'
                                   ' source=b"new"\n'
                                   ' print("change")\n'
                                   ' return b"b"\n'
                                   'print(source+change(),source)\n',
                                   ('',)),
 'finite_repetition_error': ('count=2 if int(input())else None\nprint(b"\\xff"*count)\n',
                             ('0\n', '1\n')),
 'bytes_constructor_payload': ('print((bytes(3)+b"\\xff")*2)\n', ('',)),
 'bytes_nul_over_limit': ('import sys\n'
                          'sys.set_int_max_str_digits(640)\n'
                          'print((int(b"9"*641+b"\\0bad")).bit_length())\n',
                          ('',)),
 'bytes_nonascii_space': ('import sys\n'
                          'sys.set_int_max_str_digits(640)\n'
                          'print((int(b"9"*641+b"\\x85")).bit_length())\n',
                          ('',))}

BOUNDARIES = {'bytes_identity_boundary': 'first=b"a"\nsecond=first\nprint(first is second)\n',
 'custom_index_boundary': 'class Count:\n'
                          ' def __index__(self):\n'
                          '  print("index")\n'
                          '  return 2\n'
                          'print(b"x"*Count())\n',
 'bytearray_finite_boundary': 'value=bytearray(b"a")if int(input())else b"a"\nprint(b"b"+value)\n'}

CASES['finite_builtin_nonbuffers'] = ('value={1:2}if int(input())else {1}\nprint(b"x"+value)\n', ('0\n', '1\n'))

BOUNDARIES['finite_array_buffer_boundary'] = 'from array import array\nvalue=array("B",[255])if int(input())else b"a"\nprint(b"x"+value)\n'


class BytesSequenceExecutionTests(unittest.TestCase):
    compare = digits.IntegerDigitLimitExecutionTests.compare


def _case(name):
    def test(self):
        source, inputs = CASES[name]
        self.compare(source, inputs, ('i64', 'i128', 'bigint'), 'ascii')
    return test


for _name in CASES:
    setattr(BytesSequenceExecutionTests, 'test_' + _name, _case(_name))


class BytesSequenceProofTests(unittest.TestCase):
    def test_graph_records_bytes_concatenation_without_decoding(self):
        self.assertEqual(Solver.computed('binary:Add', ('bytes', 'bytes')), 'bytes')

    def test_unrepresented_protocols_remain_positioned_boundaries(self):
        fragments = {'bytes_identity_boundary': "'is'",
                     'custom_index_boundary': '__index__',
                     'bytearray_finite_boundary': 'bytearray',
                     'finite_array_buffer_boundary': 'buffer'}
        for name, source in BOUNDARIES.items():
            for integer in ('i64', 'i128', 'bigint'):
                with self.subTest(name=name, integer=integer):
                    with patch('py2fastrust.codegen.generate', side_effect=AssertionError('VM used')):
                        result = transpile(source, TranspileOptions(integer=integer, license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(result.diagnostics)
                    self.assertEqual(result.diagnostics[0].code, 'E006')
                    self.assertIn(fragments[name], result.diagnostics[0].message)
                    self.assertGreater(result.diagnostics[0].line, 0)
