"""Builtin numeric count cursors retain constructor and pull semantics."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'argument_order': 'from itertools import count\n'
                   'def mark(label,value):\n'
                   ' print(label)\n'
                   ' return value\n'
                   'stream=count(step=mark("step",3),start=mark("start",2))\n'
                   'print(next(stream),next(stream))\n',
 'boolean_fast_count': 'from itertools import count,islice\n'
                       'for start,step in '
                       '[(True,1),(True,True),(False,1),(True,2),(True,False),(True,1.0)]:\n'
                       ' values=list(islice(count(start,step),3))\n'
                       ' print(values,[isinstance(x,bool) for x in values])\n',
 'captured_constructor': 'import itertools\n'
                         'make=itertools.count\n'
                         'itertools.count=lambda start,step:[start+step]\n'
                         'stream=make(5,2)\n'
                         'print(next(stream),next(stream),itertools.count(3,4))\n'
                         'print(isinstance(stream,make))\n',
 'class_field_and_return': 'from itertools import count,islice\n'
                           'class Labels:\n'
                           ' def __init__(self,start):self.values=count(start,2)\n'
                           ' def take(self):return next(self.values)\n'
                           'def make(start):return count(start,-1)\n'
                           'labels=Labels(4)\n'
                           'alias=labels.values\n'
                           'print(labels.take(),next(alias),labels.take())\n'
                           'print(list(islice(make(5),4)))\n',
 'consumer_break_and_resume': 'from itertools import count,islice\n'
                              'stream=count(2,3)\n'
                              'for value in stream:\n'
                              ' print(value)\n'
                              ' if value>6:break\n'
                              'print(next(stream),sum(islice(stream,4)))\n',
 'defaults': 'from itertools import count,islice\nprint(list(islice(count(),6)))\n',
 'display_captured_alias': 'from itertools import count\n'
                           'make=count\n'
                           'stream=make(8,-3)\n'
                           'alias=stream\n'
                           'print(stream,alias)\n'
                           'next(alias)\n'
                           'print({"stream":stream},(stream,))\n'
                           'next(stream)\n'
                           'print(repr(alias))\n',
 'display_current_state': 'from itertools import count\n'
                          'for start,step in '
                          '[(True,2),(False,True),(3,1),(4,-2),(1.25,0.25),(1,1.0),(-0.0,0.0),(float("nan"),0)]:\n'
                          ' stream=count(start,step)\n'
                          ' print(repr(stream))\n'
                          ' next(stream)\n'
                          ' print(str(stream))\n'
                          ' print([stream])\n',
 'duplicate_argument': 'from itertools import count\ncount(1,start=2)\n',
 'dynamic_numeric_alternatives': 'from itertools import count,islice\n'
                                 'def take(start,step):return list(islice(count(start,step),4))\n'
                                 'print(take(3,2),take(1.5,0.25),take(True,False))\n',
 'float_transition': 'from itertools import count,islice\n'
                     'values=list(islice(count(1,0.5),4))\n'
                     'print(values,[isinstance(x,int) for x in values])\n'
                     'print(list(islice(count(1.25,-0.5),5)))\n',
 'invalid_arity': 'from itertools import count\n'
                  'def mark(v):\n'
                  ' print(v)\n'
                  ' return v\n'
                  'count(mark(1),mark(2),mark(3))\n',
 'invalid_nonnumeric': 'from itertools import count\n'
                       'def mark(label,value):\n'
                       ' print(label)\n'
                       ' return value\n'
                       'count(mark("start","bad"),mark("step",2))\n',
 'invalid_step': 'from itertools import count\ncount(3,None)\n',
 'keyword_binding': 'from itertools import count,islice\n'
                    'print(list(islice(count(step=-2,start=7),4)))\n'
                    'print(list(islice(count(step=3),3)))\n',
 'nan_original_identity': 'from itertools import count\n'
                          'marker=float("nan")\n'
                          'stream=count(marker,0)\n'
                          'first=next(stream)\n'
                          'second=next(stream)\n'
                          'print([first]==[marker],[second]==[marker],[first]==[first])\n',
 'negative_and_zero': 'from itertools import count,islice\n'
                      'print(list(islice(count(4,-3),5)))\n'
                      'print(list(islice(count(-2,0),4)))\n',
 'nested_callback_consumers': 'from itertools import count,islice\n'
                              'stream=count(-3,2)\n'
                              'print(list(islice(filter(lambda x:x>0,stream),4)))\n'
                              'print(next(stream),list(islice(map(lambda x:x*x,stream),3)))\n',
 'noncanonical_source_function': 'def count(start=0,step=1):return [start,step]\n'
                                 'print(count(7,3))\n',
 'nonfinite_without_math': 'from itertools import count,islice\n'
                           'stream=count(float("inf"),float("-inf"))\n'
                           'first,second,third=next(stream),next(stream),next(stream)\n'
                           'print(first==float("inf"),second!=second,third!=third)\n'
                           'print([str(x) for x in islice(count(-0.0,-0.0),3)])\n',
 'shared_cursor': 'from itertools import count,islice\n'
                  'stream=count(3,4)\n'
                  'alias=stream\n'
                  'print(stream is alias,iter(stream) is stream)\n'
                  'print(next(alias),list(islice(stream,2)),next(alias))\n'
                  'print(list(zip(range(3),stream)),next(stream))\n',
 'start_with_invalid_alternative': 'from itertools import count\n'
                                   'def take(start):\n'
                                   ' stream=count(start,2)\n'
                                   ' print(next(stream))\n'
                                   'take(3)\n'
                                   'take("invalid")\n',
 'step_with_invalid_alternative': 'from itertools import count\n'
                                  'def take(step):\n'
                                  ' stream=count(3,step)\n'
                                  ' print(next(stream),next(stream))\n'
                                  'take(2)\n'
                                  'take(None)\n',
 'too_many_mixed_arguments': 'from itertools import count\ncount(1,2,step=3)\n',
 'unknown_keyword': 'from itertools import count\ncount(other=1)\n',
 'nonfinite_float': 'from itertools import count,islice\n'
                    'from math import isnan,isinf\n'
                    'stream=count(float("inf"),float("-inf"))\n'
                    'print(isinf(next(stream)),isnan(next(stream)),isnan(next(stream)))\n'
                    'stream=count(-0.0,-0.0)\n'
                    'print([str(x) for x in islice(stream,3)])\n'}

BOUNDARIES={'complex_numeric_boundary': 'from itertools import count,islice\n'
                             'print(list(islice(count(1j,2j),3)))\n',
 'custom_numeric_boundary': 'from itertools import count\n'
                            'class Number:\n'
                            ' def __add__(self,other):\n'
                            '  print("add",other)\n'
                            '  return 7\n'
                            'stream=count(Number(),2)\n'
                            'next(stream)\n'
                            'print(next(stream))\n'}

class CountExecutionTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_argument_order(self):
        self.check('argument_order')

    def test_boolean_fast_count(self):
        self.check('boolean_fast_count')

    def test_captured_constructor(self):
        self.check('captured_constructor')

    def test_class_field_and_return(self):
        self.check('class_field_and_return')

    def test_consumer_break_and_resume(self):
        self.check('consumer_break_and_resume')

    def test_defaults(self):
        self.check('defaults')

    def test_display_captured_alias(self):
        self.check('display_captured_alias')

    def test_display_current_state(self):
        self.check('display_current_state')

    def test_duplicate_argument(self):
        self.check('duplicate_argument')

    def test_dynamic_numeric_alternatives(self):
        self.check('dynamic_numeric_alternatives')

    def test_float_transition(self):
        self.check('float_transition')

    def test_invalid_arity(self):
        self.check('invalid_arity')

    def test_invalid_nonnumeric(self):
        self.check('invalid_nonnumeric')

    def test_invalid_step(self):
        self.check('invalid_step')

    def test_keyword_binding(self):
        self.check('keyword_binding')

    def test_nan_original_identity(self):
        self.check('nan_original_identity')

    def test_negative_and_zero(self):
        self.check('negative_and_zero')

    def test_nested_callback_consumers(self):
        self.check('nested_callback_consumers')

    def test_noncanonical_source_function(self):
        self.check('noncanonical_source_function')

    def test_nonfinite_without_math(self):
        self.check('nonfinite_without_math')

    def test_nonfinite_float(self):
        self.check('nonfinite_float')

    def test_shared_cursor(self):
        self.check('shared_cursor')

    def test_start_with_invalid_alternative(self):
        self.check('start_with_invalid_alternative')

    def test_step_with_invalid_alternative(self):
        self.check('step_with_invalid_alternative')

    def test_too_many_mixed_arguments(self):
        self.check('too_many_mixed_arguments')

    def test_unknown_keyword(self):
        self.check('unknown_keyword')

    def test_preserved_positioned_boundaries(self):
        for name,source in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none',filename='iterator_case.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(result.diagnostics)
                    self.assertIn('E006',str(result.diagnostics[0]))
                    self.assertIsNone(result.rust_source)
                    self.assertIn('itertools.count',str(result.diagnostics[0]))
