"""Source-class predicates retain captured linked class-object identities."""
import shutil
import unittest
from tests import test_native_module_linking as helpers

CASES={'linked_class_arguments_and_saved_alias': {'main.py': 'import shapes\n'
                                                       'First=shapes.First\n'
                                                       'Other=shapes.Second\n'
                                                       'def check(value,cls):return '
                                                       'isinstance(value,cls)\n'
                                                       'a=First(3)\n'
                                                       'print(check(a,First),check(a,Other),check(7,First),check(Other(),First))\n'
                                                       "print(check(None,First),check('a',First),check(First,First))\n",
                                            'shapes.py': 'class First:\n'
                                                         '    def __init__(self, value=0):\n'
                                                         '        self.value = value\n'
                                                         '\n'
                                                         '\n'
                                                         'class Second:\n'
                                                         '    def __init__(self, value=0):\n'
                                                         '        self.value = value\n',
                                            'other.py': 'class First:\n'
                                                        '    def __init__(self, value=0):\n'
                                                        '        self.value = value\n'
                                                        '\n'
                                                        '\n'
                                                        'class Second:\n'
                                                        '    def __init__(self, value=0):\n'
                                                        '        self.value = value\n'},
 'classinfo_tuple_short_circuits_invalid_later_member': {'main.py': 'from shapes import '
                                                                    'First,Second\n'
                                                                    'value=First()\n'
                                                                    'print(isinstance(value,(Second,First,7)))\n'
                                                                    'print(isinstance(7,(First,int,7)))\n'
                                                                    'print(isinstance(value,(Second,7,First)))\n',
                                                         'shapes.py': 'class First:\n'
                                                                      '    def __init__(self, '
                                                                      'value=0):\n'
                                                                      '        self.value = value\n'
                                                                      '\n'
                                                                      '\n'
                                                                      'class Second:\n'
                                                                      '    def __init__(self, '
                                                                      'value=0):\n'
                                                                      '        self.value = '
                                                                      'value\n',
                                                         'other.py': 'class First:\n'
                                                                     '    def __init__(self, '
                                                                     'value=0):\n'
                                                                     '        self.value = value\n'
                                                                     '\n'
                                                                     '\n'
                                                                     'class Second:\n'
                                                                     '    def __init__(self, '
                                                                     'value=0):\n'
                                                                     '        self.value = '
                                                                     'value\n'},
 'classinfo_finite_source_builtin_and_invalid_alternatives': {'main.py': 'from shapes import '
                                                                         'First,Second\n'
                                                                         'def '
                                                                         'check(value,cls):return '
                                                                         'isinstance(value,cls)\n'
                                                                         'print(check(First(),First),check(3,int),check(Second(),First))\n'
                                                                         'print(check(First(),7))\n',
                                                              'shapes.py': 'class First:\n'
                                                                           '    def __init__(self, '
                                                                           'value=0):\n'
                                                                           '        self.value = '
                                                                           'value\n'
                                                                           '\n'
                                                                           '\n'
                                                                           'class Second:\n'
                                                                           '    def __init__(self, '
                                                                           'value=0):\n'
                                                                           '        self.value = '
                                                                           'value\n',
                                                              'other.py': 'class First:\n'
                                                                          '    def __init__(self, '
                                                                          'value=0):\n'
                                                                          '        self.value = '
                                                                          'value\n'
                                                                          '\n'
                                                                          '\n'
                                                                          'class Second:\n'
                                                                          '    def __init__(self, '
                                                                          'value=0):\n'
                                                                          '        self.value = '
                                                                          'value\n'},
 'same_named_classes_in_different_modules': {'main.py': 'from shapes import First as Left\n'
                                                        'from other import First as Right\n'
                                                        'left=Left()\n'
                                                        'print(isinstance(left,Left),isinstance(left,Right),isinstance(Right(),Left))\n',
                                             'shapes.py': 'class First:\n'
                                                          '    def __init__(self, value=0):\n'
                                                          '        self.value = value\n'
                                                          '\n'
                                                          '\n'
                                                          'class Second:\n'
                                                          '    def __init__(self, value=0):\n'
                                                          '        self.value = value\n',
                                             'other.py': 'class First:\n'
                                                         '    def __init__(self, value=0):\n'
                                                         '        self.value = value\n'
                                                         '\n'
                                                         '\n'
                                                         'class Second:\n'
                                                         '    def __init__(self, value=0):\n'
                                                         '        self.value = value\n'},
 'conditional_instance_class_and_primitive_values': {'main.py': 'from shapes import First,Second\n'
                                                                'def check(flag):\n'
                                                                ' value=First(4)if flag else 7\n'
                                                                ' return '
                                                                'isinstance(value,First),isinstance(value,Second),isinstance(value,int)\n'
                                                                'print(check(True),check(False))\n',
                                                     'shapes.py': 'class First:\n'
                                                                  '    def __init__(self, '
                                                                  'value=0):\n'
                                                                  '        self.value = value\n'
                                                                  '\n'
                                                                  '\n'
                                                                  'class Second:\n'
                                                                  '    def __init__(self, '
                                                                  'value=0):\n'
                                                                  '        self.value = value\n',
                                                     'other.py': 'class First:\n'
                                                                 '    def __init__(self, '
                                                                 'value=0):\n'
                                                                 '        self.value = value\n'
                                                                 '\n'
                                                                 '\n'
                                                                 'class Second:\n'
                                                                 '    def __init__(self, '
                                                                 'value=0):\n'
                                                                 '        self.value = value\n'},
 'captured_isinstance_builtin': {'main.py': 'from shapes import First,Second\n'
                                            'check=isinstance\n'
                                            'print(check(First(),First),check(Second(),First),check(7,First))\n',
                                 'shapes.py': 'class First:\n'
                                              '    def __init__(self, value=0):\n'
                                              '        self.value = value\n'
                                              '\n'
                                              '\n'
                                              'class Second:\n'
                                              '    def __init__(self, value=0):\n'
                                              '        self.value = value\n',
                                 'other.py': 'class First:\n'
                                             '    def __init__(self, value=0):\n'
                                             '        self.value = value\n'
                                             '\n'
                                             '\n'
                                             'class Second:\n'
                                             '    def __init__(self, value=0):\n'
                                             '        self.value = value\n'},
 'empty_and_nested_classinfo_tuples': {'main.py': 'from shapes import First,Second\n'
                                                  'value=First()\n'
                                                  'print(isinstance(value,()),isinstance(value,((),(Second,(First,)))))\n',
                                       'shapes.py': 'class First:\n'
                                                    '    def __init__(self, value=0):\n'
                                                    '        self.value = value\n'
                                                    '\n'
                                                    '\n'
                                                    'class Second:\n'
                                                    '    def __init__(self, value=0):\n'
                                                    '        self.value = value\n',
                                       'other.py': 'class First:\n'
                                                   '    def __init__(self, value=0):\n'
                                                   '        self.value = value\n'
                                                   '\n'
                                                   '\n'
                                                   'class Second:\n'
                                                   '    def __init__(self, value=0):\n'
                                                   '        self.value = value\n'}}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SourceClassIsinstanceTests(unittest.TestCase):
    exercise=helpers.NativeLinkedModuleTests.exercise

    def test_linked_class_arguments_and_saved_alias(self):
        self.exercise(CASES['linked_class_arguments_and_saved_alias'])

    def test_classinfo_tuple_short_circuits_invalid_later_member(self):
        self.exercise(CASES['classinfo_tuple_short_circuits_invalid_later_member'])

    def test_classinfo_finite_source_builtin_and_invalid_alternatives(self):
        self.exercise(CASES['classinfo_finite_source_builtin_and_invalid_alternatives'])

    def test_same_named_classes_in_different_modules(self):
        self.exercise(CASES['same_named_classes_in_different_modules'])

    def test_conditional_instance_class_and_primitive_values(self):
        self.exercise(CASES['conditional_instance_class_and_primitive_values'])

    def test_captured_isinstance_builtin(self):
        self.exercise(CASES['captured_isinstance_builtin'])

    def test_empty_and_nested_classinfo_tuples(self):
        self.exercise(CASES['empty_and_nested_classinfo_tuples'])

if __name__=='__main__':
    unittest.main()
