"""Comparison key factories preserve captured callbacks and Python sorting."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'basic_integer': 'from functools import cmp_to_key\n'
                  'def compare(a,b):return a-b\n'
                  'print(sorted([7,2,4,2],key=cmp_to_key(compare)))\n',
 'sort_in_place': 'import functools\n'
                  'values=[7,2,4,2]\n'
                  'values.sort(key=functools.cmp_to_key(lambda a,b:b-a))\n'
                  'print(values)\n',
 'factory_alias': 'from functools import cmp_to_key as make\n'
                  'def compare(a,b):return a-b\n'
                  'key=make(compare)\n'
                  'print(sorted([7,2,4,2],key=key))\n',
 'keyword_constructor': 'from functools import cmp_to_key\n'
                        'def compare(a,b):return a-b\n'
                        'print(sorted([7,2,4],key=cmp_to_key(mycmp=compare)))\n',
 'stable_ties': 'from functools import cmp_to_key\n'
                'values=[(2,0),(1,1),(2,2),(1,3)]\n'
                'print(sorted(values,key=cmp_to_key(lambda a,b:a[0]-b[0])))\n',
 'stable_reverse': 'from functools import cmp_to_key\n'
                   'values=[(2,0),(1,1),(2,2),(1,3)]\n'
                   'print(sorted(values,key=cmp_to_key(lambda '
                   'a,b:a[0]-b[0]),reverse=True))\n',
 'boolean_result_only_less': 'from functools import cmp_to_key\n'
                             'print(sorted([3,1,4,2],key=cmp_to_key(lambda '
                             'a,b:a>b)))\n',
 'float_result': 'from functools import cmp_to_key\n'
                 'def compare(a,b):return -0.5 if a<b else 0.5 if a>b else '
                 '0.0\n'
                 'print(sorted([3,1,4,2],key=cmp_to_key(compare)))\n',
 'nan_result': 'from functools import cmp_to_key\n'
               'def compare(a,b):return float("nan")\n'
               'print(sorted([3,1,4,2],key=cmp_to_key(compare)))\n',
 'empty_noncallable': 'from functools import cmp_to_key\n'
                      'print(sorted([],key=cmp_to_key(None)))\n',
 'single_noncallable': 'from functools import cmp_to_key\n'
                       'print(sorted([7],key=cmp_to_key(None)))\n',
 'noncallable_comparison': 'from functools import cmp_to_key\n'
                           'print(sorted([7,2],key=cmp_to_key(None)))\n',
 'invalid_return_type': 'from functools import cmp_to_key\n'
                        'print(sorted([7,2],key=cmp_to_key(lambda '
                        'a,b:"invalid")))\n',
 'callback_error': 'from functools import cmp_to_key\n'
                   'def compare(a,b):\n'
                   ' print("compare",a,b)\n'
                   ' return 1//(a-b)\n'
                   'print(sorted([2,1,1],key=cmp_to_key(compare)))\n',
 'callback_stopiteration': 'from functools import cmp_to_key\n'
                           'def compare(a,b):\n'
                           ' print("compare",a,b)\n'
                           ' return next(iter([]))\n'
                           'print(sorted([3,1,2],key=cmp_to_key(compare)))\n',
 'constructor_missing': 'from functools import cmp_to_key\n'
                        'key=cmp_to_key()\n'
                        'print("unreachable")\n',
 'constructor_extra_effects': 'from functools import cmp_to_key\n'
                              'def mark(label,v):\n'
                              ' print(label)\n'
                              ' return v\n'
                              'key=cmp_to_key(mark("first",None),mark("second",None))\n'
                              'print("unreachable")\n',
 'constructor_wrong_keyword': 'from functools import cmp_to_key\n'
                              'key=cmp_to_key(func=None)\n'
                              'print("unreachable")\n',
 'closure_capture': 'from functools import cmp_to_key\n'
                    'def order(direction):\n'
                    ' def compare(a,b):return direction*(a-b)\n'
                    ' return sorted([3,1,4,2],key=cmp_to_key(compare))\n'
                    'print(order(1),order(-1))\n',
 'mutable_item_identity': 'from functools import cmp_to_key\n'
                          'a=[3]\n'
                          'b=[1]\n'
                          'values=sorted([a,b],key=cmp_to_key(lambda '
                          'a,b:a[0]-b[0]))\n'
                          'values[1].append(7)\n'
                          'print(values,a,b,values[1] is a)\n',
 'callback_mutates_fields': 'from functools import cmp_to_key\n'
                            'class Compare:\n'
                            ' def __init__(self):self.calls=0\n'
                            ' def run(self,a,b):\n'
                            '  self.calls+=1\n'
                            '  return a-b\n'
                            'c=Compare()\n'
                            'print(sorted([7,2,4,2],key=cmp_to_key(c.run)),c.calls)\n',
 'argument_capture_order': 'from functools import cmp_to_key\n'
                           'def source():\n'
                           ' print("source")\n'
                           ' return [3,1,2]\n'
                           'def comparator():\n'
                           ' print("comparator")\n'
                           ' return lambda a,b:a-b\n'
                           'def reverse():\n'
                           ' print("reverse")\n'
                           ' return True\n'
                           'print(sorted(source(),key=cmp_to_key(comparator()),reverse=reverse()))\n',
 'non_total_negative': 'from functools import cmp_to_key\n'
                       'print(sorted([3,1,4,2],key=cmp_to_key(lambda '
                       'a,b:-1)))\n',
 'shadow_module_object': 'import functools\n'
                         'class Fake:\n'
                         ' def cmp_to_key(self,callback):return callback\n'
                         'functools=Fake()\n'
                         'print(sorted([-3,1,-2],key=functools.cmp_to_key(abs)))\n',
 'comparison_schedule_7': 'from functools import cmp_to_key\n'
                          'events=[]\n'
                          'def compare(a,b):\n'
                          ' events.append((a,b))\n'
                          ' return a-b\n'
                          'values=[(i*37)%61 for i in range(7)]\n'
                          'print(sorted(values,key=cmp_to_key(compare),reverse=False))\n'
                          'print(len(events),sum((i+1)*(a*1000+b) for i,(a,b) '
                          'in enumerate(events)))\n',
 'comparison_schedule_31': 'from functools import cmp_to_key\n'
                           'events=[]\n'
                           'def compare(a,b):\n'
                           ' events.append((a,b))\n'
                           ' return a-b\n'
                           'values=[(i*37)%61 for i in range(31)]\n'
                           'print(sorted(values,key=cmp_to_key(compare),reverse=False))\n'
                           'print(len(events),sum((i+1)*(a*1000+b) for i,(a,b) '
                           'in enumerate(events)))\n',
 'comparison_schedule_63': 'from functools import cmp_to_key\n'
                           'events=[]\n'
                           'def compare(a,b):\n'
                           ' events.append((a,b))\n'
                           ' return a-b\n'
                           'values=[(i*37)%61 for i in range(63)]\n'
                           'print(sorted(values,key=cmp_to_key(compare),reverse=False))\n'
                           'print(len(events),sum((i+1)*(a*1000+b) for i,(a,b) '
                           'in enumerate(events)))\n',
 'comparison_schedule_64': 'from functools import cmp_to_key\n'
                           'events=[]\n'
                           'def compare(a,b):\n'
                           ' events.append((a,b))\n'
                           ' return a-b\n'
                           'values=[(i*37)%61 for i in range(64)]\n'
                           'print(sorted(values,key=cmp_to_key(compare),reverse=True))\n'
                           'print(len(events),sum((i+1)*(a*1000+b) for i,(a,b) '
                           'in enumerate(events)))\n',
 'comparison_schedule_65': 'from functools import cmp_to_key\n'
                           'events=[]\n'
                           'def compare(a,b):\n'
                           ' events.append((a,b))\n'
                           ' return a-b\n'
                           'values=[(i*37)%61 for i in range(65)]\n'
                           'print(sorted(values,key=cmp_to_key(compare),reverse=False))\n'
                           'print(len(events),sum((i+1)*(a*1000+b) for i,(a,b) '
                           'in enumerate(events)))\n',
 'comparison_schedule_127': 'from functools import cmp_to_key\n'
                            'events=[]\n'
                            'def compare(a,b):\n'
                            ' events.append((a,b))\n'
                            ' return a-b\n'
                            'values=[(i*37)%61 for i in range(127)]\n'
                            'print(sorted(values,key=cmp_to_key(compare),reverse=False))\n'
                            'print(len(events),sum((i+1)*(a*1000+b) for '
                            'i,(a,b) in enumerate(events)))\n',
 'comparison_schedule_128': 'from functools import cmp_to_key\n'
                            'events=[]\n'
                            'def compare(a,b):\n'
                            ' events.append((a,b))\n'
                            ' return a-b\n'
                            'values=[(i*37)%61 for i in range(128)]\n'
                            'print(sorted(values,key=cmp_to_key(compare),reverse=True))\n'
                            'print(len(events),sum((i+1)*(a*1000+b) for '
                            'i,(a,b) in enumerate(events)))\n',
 'comparison_schedule_129': 'from functools import cmp_to_key\n'
                            'events=[]\n'
                            'def compare(a,b):\n'
                            ' events.append((a,b))\n'
                            ' return a-b\n'
                            'values=[(i*37)%61 for i in range(129)]\n'
                            'print(sorted(values,key=cmp_to_key(compare),reverse=False))\n'
                            'print(len(events),sum((i+1)*(a*1000+b) for '
                            'i,(a,b) in enumerate(events)))\n',
 'comparison_schedule_200': 'from functools import cmp_to_key\n'
                            'events=[]\n'
                            'def compare(a,b):\n'
                            ' events.append((a,b))\n'
                            ' return a-b\n'
                            'values=[(i*37)%61 for i in range(200)]\n'
                            'print(sorted(values,key=cmp_to_key(compare),reverse=True))\n'
                            'print(len(events),sum((i+1)*(a*1000+b) for '
                            'i,(a,b) in enumerate(events)))\n'}

@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class ComparisonKeys(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_basic_integer(self):
        self.check('basic_integer')

    def test_sort_in_place(self):
        self.check('sort_in_place')

    def test_factory_alias(self):
        self.check('factory_alias')

    def test_keyword_constructor(self):
        self.check('keyword_constructor')

    def test_stable_ties(self):
        self.check('stable_ties')

    def test_stable_reverse(self):
        self.check('stable_reverse')

    def test_boolean_result_only_less(self):
        self.check('boolean_result_only_less')

    def test_float_result(self):
        self.check('float_result')

    def test_nan_result(self):
        self.check('nan_result')

    def test_empty_noncallable(self):
        self.check('empty_noncallable')

    def test_single_noncallable(self):
        self.check('single_noncallable')

    def test_noncallable_comparison(self):
        self.check('noncallable_comparison')

    def test_invalid_return_type(self):
        self.check('invalid_return_type')

    def test_callback_error(self):
        self.check('callback_error')

    def test_callback_stopiteration(self):
        self.check('callback_stopiteration')

    def test_constructor_missing(self):
        self.check('constructor_missing')

    def test_constructor_extra_effects(self):
        self.check('constructor_extra_effects')

    def test_constructor_wrong_keyword(self):
        self.check('constructor_wrong_keyword')

    def test_closure_capture(self):
        self.check('closure_capture')

    def test_mutable_item_identity(self):
        self.check('mutable_item_identity')

    def test_callback_mutates_fields(self):
        self.check('callback_mutates_fields')

    def test_argument_capture_order(self):
        self.check('argument_capture_order')

    def test_non_total_negative(self):
        self.check('non_total_negative')

    def test_shadow_module_object(self):
        self.check('shadow_module_object')

    def test_comparison_schedule_7(self):
        self.check('comparison_schedule_7')

    def test_comparison_schedule_31(self):
        self.check('comparison_schedule_31')

    def test_comparison_schedule_63(self):
        self.check('comparison_schedule_63')

    def test_comparison_schedule_64(self):
        self.check('comparison_schedule_64')

    def test_comparison_schedule_65(self):
        self.check('comparison_schedule_65')

    def test_comparison_schedule_127(self):
        self.check('comparison_schedule_127')

    def test_comparison_schedule_128(self):
        self.check('comparison_schedule_128')

    def test_comparison_schedule_129(self):
        self.check('comparison_schedule_129')

    def test_comparison_schedule_200(self):
        self.check('comparison_schedule_200')
