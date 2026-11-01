"""Canonical classmethod descriptors retain their actual cls and function."""
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_module_linking as support

CASES = {'basic_cls_and_instance_binding': {'main.py': 'class Counter:\n'
                                               ' values=[]\n'
                                               ' @classmethod\n'
                                               ' def add(cls,value):\n'
                                               '  cls.values.append(value)\n'
                                               '  return cls\n'
                                               'saved=Counter.add\n'
                                               'instance=Counter()\n'
                                               'print(saved(3) is Counter,instance.add(4) is '
                                               'Counter,Counter.values)\n'},
 'saved_method_after_class_name_rebind': {'main.py': 'class First:\n'
                                                     ' value=3\n'
                                                     ' @classmethod\n'
                                                     ' def get(cls):return cls.value\n'
                                                     'saved=First.get\n'
                                                     'class Second:\n'
                                                     ' value=8\n'
                                                     'First=Second\n'
                                                     'print(saved(),First.value)\n'},
 'canonical_decorator_alias': {'main.py': 'cm=classmethod\n'
                                          'class Counter:\n'
                                          ' value=7\n'
                                          ' @cm\n'
                                          ' def get(cls):return cls.value\n'
                                          'print(Counter.get(),Counter().get())\n'},
 'instance_and_class_reference_equality': {'main.py': 'class Box:\n'
                                                      ' @classmethod\n'
                                                      ' def get(cls,value):return value+1\n'
                                                      'box=Box()\n'
                                                      'a=Box.get\n'
                                                      'b=box.get\n'
                                                      'same=a\n'
                                                      'print(a==b,a is b,a is same,Box.get is '
                                                      'Box.get,a(4),b(7))\n'},
 'fixed_positional_keyword_default_capture': {'main.py': 'def mark(value):\n'
                                                         " print('default',value)\n"
                                                         ' return value\n'
                                                         'class Box:\n'
                                                         ' factor=3\n'
                                                         ' @classmethod\n'
                                                         ' def apply(cls,x=mark(4),/,y=5,*,z=7):return '
                                                         'cls.factor*x+y+z\n'
                                                         'print(Box.apply(),Box().apply(2,z=1),Box.apply(2,8,z=9))\n'},
 'variadic_method_and_expansion': {'main.py': 'class Box:\n'
                                              ' value=10\n'
                                              ' @classmethod\n'
                                              ' def total(cls,*items,scale=2):return '
                                              'cls.value+sum(items)*scale\n'
                                              'print(Box.total(),Box.total(1,3),Box().total(*[2,5],scale=3))\n'},
 'stored_method_argument_and_callback': {'main.py': 'class Box:\n'
                                                    ' bias=4\n'
                                                    ' @classmethod\n'
                                                    ' def score(cls,value):return value+cls.bias\n'
                                                    'def run(function,items):return [function(x)for x '
                                                    'in items]\n'
                                                    'print(run(Box.score,[1,3]),list(map(Box().score,[2,5])))\n'},
 'nested_class_and_private_name': {'main.py': 'class Outer:\n'
                                              ' class Inner:\n'
                                              '  __value=9\n'
                                              '  @classmethod\n'
                                              '  def __get(cls):return cls.__value\n'
                                              '  @classmethod\n'
                                              '  def run(cls):return cls.__get()\n'
                                              'print(Outer.Inner.run(),Outer.Inner().run(),Outer.Inner._Inner__get())\n'},
 'imported_captured_class_and_function': {'main.py': 'from records import Box\n'
                                                     'saved=Box.get\n'
                                                     'print(saved(3),Box().get(4))\n',
                                          'records.py': 'offset=8\n'
                                                        'class Box:\n'
                                                        ' factor=3\n'
                                                        ' @classmethod\n'
                                                        ' def get(cls,value=2):return '
                                                        'offset+cls.factor*value\n'},
 'canonical_builtin_module_alias': {'main.py': 'import builtins\n'
                                               'cm=builtins.classmethod\n'
                                               'class Box:\n'
                                               ' value=5\n'
                                               ' @cm\n'
                                               ' def get(cls):return cls.value\n'
                                               'print(Box.get())\n'},
 'decorator_expression_before_defaults': {'main.py': 'events=[]\n'
                                                     'def decorator():\n'
                                                     " events.append('decorator')\n"
                                                     ' return classmethod\n'
                                                     'def default():\n'
                                                     " events.append('default')\n"
                                                     ' return 3\n'
                                                     'class Box:\n'
                                                     ' @decorator()\n'
                                                     ' def get(cls,value=default()):return value+1\n'
                                                     'print(events,Box.get())\n'},
 'callee_captured_before_argument_effect': {'main.py': 'class Box:\n'
                                                       ' value=1\n'
                                                       ' @classmethod\n'
                                                       ' def get(cls,x):return cls.value+x\n'
                                                       'class Other:\n'
                                                       ' value=7\n'
                                                       'saved=Box.get\n'
                                                       'def argument():\n'
                                                       ' global Box\n'
                                                       ' Box=Other\n'
                                                       ' return 4\n'
                                                       'print(saved(argument()))\n'},
 'missing_argument_after_explicit_evaluation': {'main.py': 'class Box:\n'
                                                           ' @classmethod\n'
                                                           ' def f(cls,a,b):return a+b\n'
                                                           'def mark():\n'
                                                           " print('argument')\n"
                                                           ' return 3\n'
                                                           'print(Box.f(mark()))\n'},
 'duplicate_argument_error_after_keyword_effect': {'main.py': 'class Box:\n'
                                                              ' @classmethod\n'
                                                              ' def f(cls,x):return x\n'
                                                              'def mark():\n'
                                                              " print('keyword')\n"
                                                              ' return 7\n'
                                                              'Box().f(3,x=mark())\n'},
 'body_error_original_frames': {'main.py': 'class Box:\n'
                                           ' @classmethod\n'
                                           ' def divide(cls,x):return 7//x\n'
                                           'saved=Box.divide\n'
                                           "print('before')\n"
                                           'saved(0)\n'},
 'finite_methods_same_spelling': {'main.py': 'class Left:\n'
                                             ' value=2\n'
                                             ' @classmethod\n'
                                             ' def get(cls,x):return cls.value+x\n'
                                             'class Right:\n'
                                             ' value=9\n'
                                             ' @classmethod\n'
                                             ' def get(cls,x):return cls.value*x\n'
                                             'def apply(function):return function(3)\n'
                                             'print(apply(Left.get),apply(Right().get))\n'},
 'classmethod_builtin_metadata': {'main.py': 'print(classmethod)\n'
                                             'print(isinstance(3,classmethod),isinstance(classmethod,classmethod))\n'},
 'captured_decorator_survives_global_rebind': {'main.py': 'cm=classmethod\n'
                                                          'def replacement(function):return function\n'
                                                          'classmethod=replacement\n'
                                                          'class Box:\n'
                                                          ' value=7\n'
                                                          ' @cm\n'
                                                          ' def get(cls):return cls.value\n'
                                                          'print(Box.get(),Box().get())\n'},
 'default_raises_after_decorator': {'main.py': 'def decorator():\n'
                                               " print('decorator')\n"
                                               ' return classmethod\n'
                                               'def default():\n'
                                               " print('default')\n"
                                               ' return 1//0\n'
                                               'class Box:\n'
                                               ' @decorator()\n'
                                               ' def get(cls,value=default()):return value\n'},
 'expanded_missing_argument_preserves_effects': {'main.py': 'class Box:\n'
                                                            ' @classmethod\n'
                                                            ' def get(cls,x,y):return x+y\n'
                                                            'def source():\n'
                                                            " print('source')\n"
                                                            ' return [2]\n'
                                                            'Box.get(*source())\n'},
 'expanded_duplicate_argument_preserves_effects': {'main.py': 'class Box:\n'
                                                              ' @classmethod\n'
                                                              ' def get(cls,x):return x\n'
                                                              'def keyword():\n'
                                                              " print('keyword')\n"
                                                              ' return 9\n'
                                                              'Box().get(*[2],x=keyword())\n'},
 'class_body_mutation_is_visible_to_cls': {'main.py': 'class Box:\n'
                                                      ' value=1\n'
                                                      ' @classmethod\n'
                                                      ' def increase(cls,amount=1):\n'
                                                      '  cls.value+=amount\n'
                                                      '  return cls.value\n'
                                                      'print(Box.increase(),Box().increase(3),Box.value)\n'}}

UNSUPPORTED = {'class_body_raw_descriptor_guard': 'class Box:\n'
                                    ' @classmethod\n'
                                    ' def get(cls):return 3\n'
                                    ' raw=get\n'
                                    'print(Box.raw is Box.get)\n',
 'shadowed_decorator_guard': 'def classmethod(function):return function\n'
                             'class Box:\n'
                             ' @classmethod\n'
                             ' def get(cls):return 3\n'
                             'print(Box.get(Box))\n',
 'decorator_call_raises_before_default': 'def decorator():\n'
                                         " print('decorator')\n"
                                         ' return 1//0\n'
                                         'def default():\n'
                                         " print('wrong default')\n"
                                         ' return 3\n'
                                         'class Box:\n'
                                         ' @decorator()\n'
                                         ' def get(cls,value=default()):return value\n',
 'classmethod_constructor_protocol': 'class Box:\n'
                                     ' value=0\n'
                                     ' @classmethod\n'
                                     ' def __init__(cls,value):cls.value=value\n'
                                     'box=Box(8)\n'
                                     'print(Box.value,box.value)\n'}

class ClassMethodBoundaries(unittest.TestCase):
    def test_unproved_decorators_and_raw_descriptor_protocol_are_positioned(self):
        for name,source in UNSUPPORTED.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename='main.py',integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn('descriptor' if name in {'class_body_raw_descriptor_guard','classmethod_constructor_protocol'} else 'decorator',result.diagnostics[0].message)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassMethodExecutionTests(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise


def _execution(files):
    def test(self):self.exercise(files)
    return test


for _name,_files in CASES.items():
    setattr(ClassMethodExecutionTests,'test_'+_name,_execution(_files))
