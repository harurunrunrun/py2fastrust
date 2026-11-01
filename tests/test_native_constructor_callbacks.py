"""Captured source classes use their real initializer binding and ownership."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
CASES={'map_source_class_constructor': 'class Item:\n'
                                 ' def __init__(self,value):self.value=value\n'
                                 'items=list(map(Item,[2,4]))\n'
                                 'print([item.value for item in items])\n',
 'saved_constructor': 'class Item:\n'
                      ' def __init__(self,value):self.value=value\n'
                      'build=Item\n'
                      'items=list(map(build,[1,3]))\n'
                      'print([item.value for item in items])\n',
 'captured_class_rebinding': 'class Item:\n'
                             ' def __init__(self,value):self.value=value\n'
                             'build=Item\n'
                             'Item=7\n'
                             'items=list(map(build,[1,3]))\n'
                             'print([item.value for item in items],Item)\n',
 'constructor_in_parameter': 'class Item:\n'
                             ' def __init__(self,value):self.value=value\n'
                             'def apply(build,value):return build(value)\n'
                             'print(apply(Item,9).value)\n',
 'returned_constructor': 'class Item:\n'
                         ' def __init__(self,value):self.value=value\n'
                         'def builder():return Item\n'
                         'print(builder()(7).value)\n',
 'constructor_map_is_lazy': 'class Item:\n'
                            ' def __init__(self,value):\n'
                            '  print("build",value)\n'
                            '  self.value=value\n'
                            'it=map(Item,[2,4,6])\n'
                            'print("ready")\n'
                            'print(next(it).value)\n'
                            'print([item.value for item in it])\n',
 'empty_source_no_init_call': 'class Item:\n'
                              ' def __init__(self,value):\n'
                              '  print("unreachable")\n'
                              '  self.value=value\n'
                              'print(list(map(Item,[])))\n',
 'empty_source_invalid_constructor_binding': 'class Item:\n'
                                             ' def '
                                             '__init__(self,a,b):self.value=a+b\n'
                                             'print(list(map(Item,[])))\n',
 'missing_constructor_argument': 'class Item:\n'
                                 ' def __init__(self,a,b):self.value=a+b\n'
                                 'print(list(map(Item,[1])))\n',
 'excess_constructor_argument': 'class Item:\n'
                                ' def __init__(self,value):self.value=value\n'
                                'print(list(map(Item,[1],[2])))\n',
 'constructor_defaults': 'class Item:\n'
                         ' def '
                         '__init__(self,value,scale=3):self.value=value*scale\n'
                         'print([item.value for item in map(Item,[2,4])])\n',
 'constructor_keyword_only_default': 'class Item:\n'
                                     ' def '
                                     '__init__(self,value,*,scale=3):self.value=value*scale\n'
                                     'print([item.value for item in '
                                     'map(Item,[2,4])])\n',
 'captured_constructor_keywords': 'class Item:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'def apply(build):return build(value=8)\n'
                                  'print(apply(Item).value)\n',
 'constructor_bad_keyword': 'class Item:\n'
                            ' def __init__(self,value):self.value=value\n'
                            'def apply(build):return build(wrong=8)\n'
                            'print(apply(Item))\n',
 'constructor_variadic': 'class Item:\n'
                         ' def __init__(self,*values):self.value=sum(values)\n'
                         'print([item.value for item in '
                         'map(Item,[2,4],[3,5])])\n',
 'constructor_tuple_field': 'class Item:\n'
                            ' def __init__(self,pair):self.a,self.b=pair\n'
                            'print([(item.a,item.b)for item in '
                            'map(Item,[(1,2),(3,4)])])\n',
 'constructor_shared_mutable_item': 'class Item:\n'
                                    ' def '
                                    '__init__(self,value):self.value=value\n'
                                    'values=[1]\n'
                                    'items=list(map(Item,[values,values]))\n'
                                    'items[0].value.append(2)\n'
                                    'print(items[1].value,items[0].value is '
                                    'items[1].value)\n',
 'constructor_live_source': 'values=[1]\n'
                            'class Item:\n'
                            ' def __init__(self,value):\n'
                            '  if value==1:values.append(2)\n'
                            '  self.value=value\n'
                            'print([item.value for item in '
                            'map(Item,values)])\n',
 'constructor_error_after_partial': 'class Item:\n'
                                    ' def __init__(self,value):\n'
                                    '  print("build",value)\n'
                                    '  self.value=10//value\n'
                                    'print([item.value for item in '
                                    'map(Item,[2,0,5])])\n',
 'constructor_multiple_source_calls': 'class Item:\n'
                                      ' def __init__(self,a,b):self.value=a+b\n'
                                      'print([item.value for item in '
                                      'map(Item,[1,2],[10,20])])\n',
 'class_without_init_rejects_arguments': 'class Item:pass\n'
                                         'print(list(map(Item,[1])))\n',
 'captured_zero_arg_class': 'class Item:pass\n'
                            'def build(factory):return factory()\n'
                            'print(isinstance(build(Item),Item))\n',
 'finite_constructor_choice': 'class A:\n'
                              ' def __init__(self,value):self.value=value+1\n'
                              'class B:\n'
                              ' def __init__(self,value):self.value=value*2\n'
                              'def apply(build):return build(3).value\n'
                              'print(apply(A),apply(B))\n',
 'finite_class_or_function': 'class Item:\n'
                             ' def __init__(self,value):self.value=value\n'
                             'def make(value):return Item(value+10)\n'
                             'def apply(build):return build(3).value\n'
                             'print(apply(Item),apply(make))\n',
 'constructor_callback_capture_before_source': 'class Item:\n'
                                               ' def '
                                               '__init__(self,value):self.value=value\n'
                                               'def source():\n'
                                               ' global Item\n'
                                               ' Item=7\n'
                                               ' print("source")\n'
                                               ' return [2,4]\n'
                                               'items=list(map(Item,source()))\n'
                                               'print([item.value for item in '
                                               'items],Item)\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class ConstructorCallbacks(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_map_source_class_constructor(self):self.check('map_source_class_constructor')
    def test_saved_constructor(self):self.check('saved_constructor')
    def test_captured_class_rebinding(self):self.check('captured_class_rebinding')
    def test_constructor_in_parameter(self):self.check('constructor_in_parameter')
    def test_returned_constructor(self):self.check('returned_constructor')
    def test_constructor_map_is_lazy(self):self.check('constructor_map_is_lazy')
    def test_empty_source_no_init_call(self):self.check('empty_source_no_init_call')
    def test_empty_source_invalid_constructor_binding(self):self.check('empty_source_invalid_constructor_binding')
    def test_missing_constructor_argument(self):self.check('missing_constructor_argument')
    def test_excess_constructor_argument(self):self.check('excess_constructor_argument')
    def test_constructor_defaults(self):self.check('constructor_defaults')
    def test_constructor_keyword_only_default(self):self.check('constructor_keyword_only_default')
    def test_captured_constructor_keywords(self):self.check('captured_constructor_keywords')
    def test_constructor_bad_keyword(self):self.check('constructor_bad_keyword')
    def test_constructor_variadic(self):self.check('constructor_variadic')
    def test_constructor_tuple_field(self):self.check('constructor_tuple_field')
    def test_constructor_shared_mutable_item(self):self.check('constructor_shared_mutable_item')
    def test_constructor_live_source(self):self.check('constructor_live_source')
    def test_constructor_error_after_partial(self):self.check('constructor_error_after_partial')
    def test_constructor_multiple_source_calls(self):self.check('constructor_multiple_source_calls')
    def test_class_without_init_rejects_arguments(self):self.check('class_without_init_rejects_arguments')
    def test_captured_zero_arg_class(self):self.check('captured_zero_arg_class')
    def test_finite_constructor_choice(self):self.check('finite_constructor_choice')
    def test_finite_class_or_function(self):self.check('finite_class_or_function')
    def test_constructor_callback_capture_before_source(self):self.check('constructor_callback_capture_before_source')
