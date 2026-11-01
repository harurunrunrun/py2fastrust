"""The ordinary and frame emitters share finite primitive operation plans."""
import unittest
import test_native_aot_callables as helpers

CASES={'optional_integer_0': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value+3)\n',
                        ('0\n', '1\n')),
 'optional_integer_1': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value-3)\n',
                        ('0\n', '1\n')),
 'optional_integer_2': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value*3)\n',
                        ('0\n', '1\n')),
 'optional_integer_3': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value//3)\n',
                        ('0\n', '1\n')),
 'optional_integer_4': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value%3)\n',
                        ('0\n', '1\n')),
 'optional_integer_5': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value**3)\n',
                        ('0\n', '1\n')),
 'optional_integer_6': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value<<3)\n',
                        ('0\n', '1\n')),
 'optional_integer_7': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value>>3)\n',
                        ('0\n', '1\n')),
 'optional_integer_8': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value&3)\n',
                        ('0\n', '1\n')),
 'optional_integer_9': ('def choose(flag):\n'
                        ' if flag:return 7\n'
                        ' return None\n'
                        'value=choose(int(input()))\n'
                        'print(value|3)\n',
                        ('0\n', '1\n')),
 'optional_integer_10': ('def choose(flag):\n'
                         ' if flag:return 7\n'
                         ' return None\n'
                         'value=choose(int(input()))\n'
                         'print(value^3)\n',
                         ('0\n', '1\n')),
 'text_add': ('def choose(flag):\n'
              ' if flag:return "x"\n'
              ' return 7\n'
              'value=choose(int(input()))\n'
              'print(value+3)\n',
              ('0\n', '1\n')),
 'text_repeat': ('def choose(flag):\n'
                 ' if flag:return "x"\n'
                 ' return 7\n'
                 'value=choose(int(input()))\n'
                 'print(value*3)\n',
                 ('0\n', '1\n')),
 'text_power': ('def choose(flag):\n'
                ' if flag:return "x"\n'
                ' return 7\n'
                'value=choose(int(input()))\n'
                'print(value**3)\n',
                ('0\n', '1\n')),
 'bytes_concat': ('def choose(flag):\n'
                  ' if flag:return b"x"\n'
                  ' return None\n'
                  'value=choose(int(input()))\n'
                  'print(value+3)\n',
                  ('0\n', '1\n')),
 'builtin_operand': ('def choose(flag):\n'
                     ' if flag:return len\n'
                     ' return 7\n'
                     'value=choose(int(input()))\n'
                     'print(value+3)\n',
                     ('0\n', '1\n')),
 'optional_boolean': ('def choose(flag):\n'
                      ' if flag:return True\n'
                      ' return None\n'
                      'value=choose(int(input()))\n'
                      'print(value&True)\n',
                      ('0\n', '1\n'))}


CASES.update({'list_operator_errors': ('class Context:pass\n'
                          'choice=int(input())\n'
                          'if choice==0:print([1]+3)\n'
                          'elif choice==1:print(3+[1])\n'
                          'elif choice==2:print([1]*"x")\n'
                          'elif choice==3:print("x"*[1])\n'
                          'elif choice==4:print([1]*[2])\n'
                          'elif choice==5:print([1]+(2,))\n'
                          'elif choice==6:print([1]&2)\n'
                          'elif choice==7:print([1]<<2)\n'
                          'elif choice==8:print(2<<[1])\n'
                          'elif choice==9:print([1]/2)\n'
                          'elif choice==10:print([1]**2)\n'
                          'elif choice==11:print([1]+[2])\n'
                          'elif choice==12:print([1]*2)\n'
                          'elif choice==13:print(2*[1])\n'
                          'else:\n'
                          ' def left():\n'
                          '  print("left")\n'
                          '  return [1]\n'
                          ' def right():\n'
                          '  print("right")\n'
                          '  return 3\n'
                          ' print(left()+right())\n',
                          ('0\n',
                           '1\n',
                           '2\n',
                           '3\n',
                           '4\n',
                           '5\n',
                           '6\n',
                           '7\n',
                           '8\n',
                           '9\n',
                           '10\n',
                           '11\n',
                           '12\n',
                           '13\n',
                           '14\n'))})


CASES.update({'list_operator_effect_order': ('class Context:pass\n'
                                'def left():\n'
                                ' print("left")\n'
                                ' return [1]\n'
                                'def right():\n'
                                ' print("right")\n'
                                ' return 3\n'
                                'print(left()+right())\n',
                                ('',)),
 'list_operator_matrix': ('class Context:pass\n'
                          'choice=int(input())\n'
                          'if choice==0:print([1]+3)\n'
                          'elif choice==1:print(3+[1])\n'
                          'elif choice==2:print([1]*"x")\n'
                          'elif choice==3:print("x"*[1])\n'
                          'elif choice==4:print([1]*[2])\n'
                          'elif choice==5:print([1]+(2,))\n'
                          'elif choice==6:print([1]&2)\n'
                          'elif choice==7:print([1]<<2)\n'
                          'elif choice==8:print(2<<[1])\n'
                          'elif choice==9:print([1]/2)\n'
                          'elif choice==10:print([1]**2)\n'
                          'elif choice==11:print([1]+[2])\n'
                          'elif choice==12:print([1]*2)\n'
                          'elif choice==13:print(2*[1])\n',
                          ('0\n',
                           '1\n',
                           '2\n',
                           '3\n',
                           '4\n',
                           '5\n',
                           '6\n',
                           '7\n',
                           '8\n',
                           '9\n',
                           '10\n',
                           '11\n',
                           '12\n',
                           '13\n'))})

class NativePrimitiveUnionTests(unittest.TestCase):
    cases=CASES
    filename="<input>"
    setUpClass=classmethod(helpers.NativeCallableCellTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeCallableCellTests.tearDownClass.__func__)
    exercise=helpers.NativeCallableCellTests.exercise

    def test_optional_integer_operators_preserve_type_errors(self):
        for index in range(11):self.exercise("optional_integer_"+str(index))

    def test_sequence_and_numeric_result_alternatives(self):
        for name in ("text_add","text_repeat","text_power","bytes_concat"):
            self.exercise(name)

    def test_builtin_operand_type_error_names_the_runtime_type(self):
        self.exercise("builtin_operand")

    def test_boolean_bitwise_result_type(self):
        self.exercise("optional_boolean")

    def test_sealed_sequence_operand_errors_keep_effect_order(self):
        for name in ("list_operator_matrix","list_operator_effect_order"):
            self.exercise(name)

    def test_conditional_module_function_definition_remains_explicit(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ("i64","i128","bigint"):
            result=transpile(CASES["list_operator_errors"][0],TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertIn("canonical lexical callable ownership",result.diagnostics[0].message)
