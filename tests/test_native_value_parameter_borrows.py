"""Borrowed closed value parameters preserve calls, frames and argument effects."""
import re
import shutil
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_lambda_callbacks as helpers


CASES = {'free_scalar_reader_0': ('class Token:\n'
                          '    def __init__(self, value):\n'
                          '        self.value=value\n'
                          '    def read(self):\n'
                          '        return self.value\n'
                          '\n'
                          'def read(item):return item.value\n'
                          'print(read(Token(17)))\n',
                          ('',)),
 'method_receiver_reader_0': ('class Token:\n'
                              '    def __init__(self, value):\n'
                              '        self.value=value\n'
                              '    def read(self):\n'
                              '        return self.value\n'
                              '\n'
                              'a=Token(7)\n'
                              'print(a.read(),a.value)\n',
                              ('',)),
 'two_readonly_same_alias_0': ('class Token:\n'
                               '    def __init__(self, value):\n'
                               '        self.value=value\n'
                               '    def read(self):\n'
                               '        return self.value\n'
                               '\n'
                               'def read(a,b):return a.value+b.value\n'
                               'x=Token(13)\n'
                               'print(read(x,x),x.value)\n',
                               ('',)),
 'keyword_only_mixed_positions_0': ('class Token:\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value=value\n'
                                    '    def read(self):\n'
                                    '        return self.value\n'
                                    '\n'
                                    'def read(first,item,*,second=5):return '
                                    'first+item.value+second\n'
                                    'a=Token(11)\n'
                                    'print(read(2,a,second=7),read(item=a,first=3))\n',
                                    ('',)),
 'default_instance_argument_0': ('class Token:\n'
                                 '    def __init__(self, value):\n'
                                 '        self.value=value\n'
                                 '    def read(self):\n'
                                 '        return self.value\n'
                                 '\n'
                                 'def read(item=Token(4)):return item.value\n'
                                 'print(read(),read(Token(9)),read())\n',
                                 ('',)),
 'later_scalar_effect_0': ('class Token:\n'
                           '    def __init__(self, value):\n'
                           '        self.value=value\n'
                           '    def read(self):\n'
                           '        return self.value\n'
                           '\n'
                           'def mark(label,value):\n'
                           ' print(label,value)\n'
                           ' return value\n'
                           'def read(item,extra):return item.value+extra\n'
                           'a=Token(6)\n'
                           'print(read(a,mark("later",a.value)),a.value)\n',
                           ('',)),
 'later_argument_mutates_alias_0': ('class Token:\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value=value\n'
                                    '    def read(self):\n'
                                    '        return self.value\n'
                                    '\n'
                                    'def change(item):\n'
                                    ' item.value=19\n'
                                    ' return 3\n'
                                    'def read(item,extra):return item.value+extra\n'
                                    'a=Token(6)\n'
                                    'print(read(a,change(a)),a.value)\n',
                                    ('',)),
 'later_argument_rebinds_global_0': ('class Token:\n'
                                     '    def __init__(self, value):\n'
                                     '        self.value=value\n'
                                     '    def read(self):\n'
                                     '        return self.value\n'
                                     '\n'
                                     'a=Token(3)\n'
                                     'def replace():\n'
                                     ' global a\n'
                                     ' a=Token(29)\n'
                                     ' return 1\n'
                                     'def read(item,extra):return item.value+extra\n'
                                     'print(read(a,replace()),a.value)\n',
                                     ('',)),
 'captured_value_before_later_error_0': ('class Token:\n'
                                         '    def __init__(self, value):\n'
                                         '        self.value=value\n'
                                         '    def read(self):\n'
                                         '        return self.value\n'
                                         '\n'
                                         'def bad():\n'
                                         ' print("later")\n'
                                         ' return 1//0\n'
                                         'def read(item,extra):return item.value+extra\n'
                                         'print(read(Token(11),bad()))\n',
                                         ('',)),
 'argument_index_error_first_0': ('class Token:\n'
                                  '    def __init__(self, value):\n'
                                  '        self.value=value\n'
                                  '    def read(self):\n'
                                  '        return self.value\n'
                                  '\n'
                                  'def mark():\n'
                                  ' print("second")\n'
                                  ' return 1\n'
                                  'def read(item,extra):return item.value+extra\n'
                                  'items=[Token(3),Token(7)]\n'
                                  'print(read(items[int(input())],mark()))\n',
                                  ('0\n', '-1\n', '2\n')),
 'parameter_rebinding_0': ('class Token:\n'
                           '    def __init__(self, value):\n'
                           '        self.value=value\n'
                           '    def read(self):\n'
                           '        return self.value\n'
                           '\n'
                           'def read(item,change):\n'
                           ' if change:item=Token(31)\n'
                           ' return item.value\n'
                           'a=Token(3)\n'
                           'print(read(a,int(input())),a.value)\n',
                           ('0\n', '1\n')),
 'parameter_returned_as_value_0': ('class Token:\n'
                                   '    def __init__(self, value):\n'
                                   '        self.value=value\n'
                                   '    def read(self):\n'
                                   '        return self.value\n'
                                   '\n'
                                   'def echo(item):return item\n'
                                   'a=Token(17)\n'
                                   'b=echo(a)\n'
                                   'print(a.value,b.value)\n',
                                   ('',)),
 'parameter_forwarded_to_reader_0': ('class Token:\n'
                                     '    def __init__(self, value):\n'
                                     '        self.value=value\n'
                                     '    def read(self):\n'
                                     '        return self.value\n'
                                     '\n'
                                     'def leaf(item):return item.value\n'
                                     'def read(item):return leaf(item)+1\n'
                                     'print(read(Token(17)))\n',
                                     ('',)),
 'parameter_captured_lambda_0': ('class Token:\n'
                                 '    def __init__(self, value):\n'
                                 '        self.value=value\n'
                                 '    def read(self):\n'
                                 '        return self.value\n'
                                 '\n'
                                 'def read(item):\n'
                                 ' query=lambda:item.value\n'
                                 ' return query()\n'
                                 'print(read(Token(17)))\n',
                                 ('',)),
 'parameter_identity_observer_0': ('class Token:\n'
                                   '    def __init__(self, value):\n'
                                   '        self.value=value\n'
                                   '    def read(self):\n'
                                   '        return self.value\n'
                                   '\n'
                                   'def read(item):return item is item\n'
                                   'print(read(Token(17)))\n',
                                   ('',)),
 'parameter_field_mutation_0': ('class Token:\n'
                                '    def __init__(self, value):\n'
                                '        self.value=value\n'
                                '    def read(self):\n'
                                '        return self.value\n'
                                '\n'
                                'def read(item):\n'
                                ' item.value+=3\n'
                                ' return item.value\n'
                                'a=Token(17)\n'
                                'print(read(a),a.value)\n',
                                ('',)),
 'higher_order_reader_callback_0': ('class Token:\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value=value\n'
                                    '    def read(self):\n'
                                    '        return self.value\n'
                                    '\n'
                                    'def leaf(item):return item.value\n'
                                    'def invoke(reader,item):return reader(item)\n'
                                    'print(invoke(leaf,Token(17)))\n',
                                    ('',)),
 'list_comprehension_calls_0': ('class Token:\n'
                                '    def __init__(self, value):\n'
                                '        self.value=value\n'
                                '    def read(self):\n'
                                '        return self.value\n'
                                '\n'
                                'def leaf(item):return item.value\n'
                                'items=[Token(i)for i in range(5)]\n'
                                'print([leaf(item)for item in items])\n',
                                ('',)),
 'recursive_owned_argument_0': ('class Token:\n'
                                '    def __init__(self, value):\n'
                                '        self.value=value\n'
                                '    def read(self):\n'
                                '        return self.value\n'
                                '\n'
                                'def descend(item,depth):\n'
                                ' if depth:return descend(item,depth-1)+1\n'
                                ' return item.value\n'
                                'print(descend(Token(3),4))\n',
                                ('',)),
 'field_error_position_0': ('class Partial:\n'
                            ' def __init__(self,enabled):\n'
                            '  if enabled:self.value=7\n'
                            'def read(item):return item.value\n'
                            'print(read(Partial(int(input()))))\n',
                            ('0\n', '1\n')),
 'field_then_scalar_failure_0': ('class Token:\n'
                                 '    def __init__(self, value):\n'
                                 '        self.value=value\n'
                                 '    def read(self):\n'
                                 '        return self.value\n'
                                 '\n'
                                 'def read(item):return item.value//int(input())\n'
                                 'print(read(Token(9)))\n',
                                 ('0\n', '2\n')),
 'literal_dead_branch': ('class Token:\n'
                         ' def __init__(self,value):self.value=value\n'
                         'def read(item):\n'
                         ' if True:return item.value\n'
                         ' else:return item.value+1\n'
                         'print(read(Token(7)))\n',
                         ('',)),
 'type_refined_other_parameter': ('class Token:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'def read(item,other):\n'
                                  ' if isinstance(other,Token):return item.value+other.value\n'
                                  ' else:return item.value+other\n'
                                  'print(read(Token(7),Token(3)))\n',
                                  ('',))}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeValueParameterBorrowTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise

    def test_scalar_only_reader_has_reference_abi(self):
        for mode in ("i64", "i128"):
            result = transpile(CASES["free_scalar_reader_0"][0], TranspileOptions(integer=mode))
            self.assertTrue(result.success, result.diagnostics)
            self.assertRegex(result.rust_source,
                r"fn class_function_\d+\(class_scope:&?ClassScope ,class_argument_0:&ClassHandle_0\)->ClassResult<NativeInt>")

    def test_forwarded_parameter_retains_owned_abi(self):
        for mode in ("i64", "i128"):
            result = transpile(CASES["parameter_forwarded_to_reader_0"][0], TranspileOptions(integer=mode))
            self.assertTrue(result.success, result.diagnostics)
            self.assertRegex(result.rust_source,
                r"fn class_function_\d+\(class_scope:&?ClassScope ,class_argument_0:ClassHandle_0\)->ClassResult<NativeInt>")

    def test_free_scalar_reader_0(self):
        self.exercise(*CASES['free_scalar_reader_0'])

    def test_method_receiver_reader_0(self):
        self.exercise(*CASES['method_receiver_reader_0'])

    def test_two_readonly_same_alias_0(self):
        self.exercise(*CASES['two_readonly_same_alias_0'])

    def test_keyword_only_mixed_positions_0(self):
        self.exercise(*CASES['keyword_only_mixed_positions_0'])

    def test_default_instance_argument_0(self):
        self.exercise(*CASES['default_instance_argument_0'])

    def test_later_scalar_effect_0(self):
        self.exercise(*CASES['later_scalar_effect_0'])

    def test_later_argument_mutates_alias_0(self):
        self.exercise(*CASES['later_argument_mutates_alias_0'])

    def test_later_argument_rebinds_global_0(self):
        self.exercise(*CASES['later_argument_rebinds_global_0'])

    def test_captured_value_before_later_error_0(self):
        self.exercise(*CASES['captured_value_before_later_error_0'])

    def test_argument_index_error_first_0(self):
        self.exercise(*CASES['argument_index_error_first_0'])

    def test_parameter_rebinding_0(self):
        self.exercise(*CASES['parameter_rebinding_0'])

    def test_parameter_returned_as_value_0(self):
        self.exercise(*CASES['parameter_returned_as_value_0'])

    def test_parameter_forwarded_to_reader_0(self):
        self.exercise(*CASES['parameter_forwarded_to_reader_0'])

    def test_parameter_captured_lambda_0(self):
        self.exercise(*CASES['parameter_captured_lambda_0'])

    def test_parameter_identity_observer_0(self):
        self.exercise(*CASES['parameter_identity_observer_0'])

    def test_parameter_field_mutation_0(self):
        self.exercise(*CASES['parameter_field_mutation_0'])

    def test_higher_order_reader_callback_0(self):
        self.exercise(*CASES['higher_order_reader_callback_0'])

    def test_list_comprehension_calls_0(self):
        self.exercise(*CASES['list_comprehension_calls_0'])

    def test_recursive_owned_argument_0(self):
        self.exercise(*CASES['recursive_owned_argument_0'])

    def test_field_error_position_0(self):
        self.exercise(*CASES['field_error_position_0'])

    def test_field_then_scalar_failure_0(self):
        self.exercise(*CASES['field_then_scalar_failure_0'])

    def test_literal_dead_branch(self):
        self.exercise(*CASES['literal_dead_branch'])

    def test_type_refined_other_parameter(self):
        self.exercise(*CASES['type_refined_other_parameter'])


if __name__ == "__main__":
    unittest.main()
