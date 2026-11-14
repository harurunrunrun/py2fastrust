"""Original tuple/list rows bind directly to compiled captured callbacks."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'arity_argument_effects': 'from itertools import starmap\n'
                           'def mark(label,value):\n'
                           ' print(label)\n'
                           ' return value\n'
                           'starmap(mark("first",None),mark("second",[]),mark("third",[]))\n',
 'bound_method_rows': 'from itertools import starmap\n'
                      'class Sum:\n'
                      ' def __init__(self):self.total=0\n'
                      ' def add(self,a,b):\n'
                      '  self.total+=a+b\n'
                      '  return self.total\n'
                      'owner=Sum()\n'
                      'print(list(starmap(owner.add,[[1,2],[3,4]])),owner.total)\n',
 'callback_mutates_original_row': 'from itertools import starmap\n'
                                  'rows=[[1,2],[3,4]]\n'
                                  'def use(a,b):\n'
                                  ' print("call",a,b)\n'
                                  ' rows[0].clear()\n'
                                  ' rows[1].append(8)\n'
                                  ' return a+b\n'
                                  'stream=starmap(use,rows)\n'
                                  'print(next(stream),rows)\n'
                                  'print(next(stream))\n',
 'callback_reentrant_next': 'from itertools import starmap\n'
                            'def emit(a,b):\n'
                            ' print("call",a,b)\n'
                            ' if a==1:print("inside",next(stream))\n'
                            ' return a+b\n'
                            'stream=starmap(emit,[(1,2),(3,4),(5,6)])\n'
                            'print(list(stream))\n',
 'callback_stop_and_resume': 'from itertools import starmap\n'
                             'def emit(a,b):\n'
                             ' if a==1:return next(iter(()))\n'
                             ' return a+b\n'
                             'stream=starmap(emit,[(0,2),(1,3),(2,4)])\n'
                             'print(list(stream),list(stream),next(stream,99))\n',
 'canonical_member_callback': 'from itertools import starmap\n'
                              'from math import gcd\n'
                              'print(list(starmap(gcd,[(12,18),(15,25)])))\n',
 'captured_constructor_rebinding': 'import itertools\n'
                                   'make=itertools.starmap\n'
                                   'itertools.starmap=lambda f,rows:[9]\n'
                                   'def add(a,b):return a+b\n'
                                   'stream=make(add,[(2,3)])\n'
                                   'print(list(stream),itertools.starmap(add,[(5,6)]),isinstance(stream,make))\n',
 'class_frame_map_isfinite': 'from math import isfinite\n'
                             'class Box:\n'
                             ' def evaluate(self,values):return list(map(isfinite,values))\n'
                             'print(Box().evaluate([0.0,float("inf")]))\n',
 'closed_callable_alternatives': 'from itertools import starmap\n'
                                 'def add(a,b):return a+b\n'
                                 'def multiply(a,b):return a*b\n'
                                 'callback=add if int(input()) else multiply\n'
                                 'print(list(starmap(callback,[[2,3],[4,5]])))\n',
 'default_argument_rows': 'from itertools import starmap\n'
                          'def combine(a=2,b=3):return a*10+b\n'
                          'print(list(starmap(combine,[(),(5,),(7,8)])))\n',
 'dynamic_fixed_arity_0': 'from itertools import starmap\n'
                          'n=int(input())\n'
                          'def add(a,b):return a+b\n'
                          'stream=starmap(add,[list(range(n))])\n'
                          'print("created")\n'
                          'print(next(stream))\n',
 'dynamic_fixed_arity_1': 'from itertools import starmap\n'
                          'n=int(input())\n'
                          'def add(a,b):return a+b\n'
                          'stream=starmap(add,[list(range(n))])\n'
                          'print("created")\n'
                          'print(next(stream))\n',
 'dynamic_fixed_arity_2': 'from itertools import starmap\n'
                          'n=int(input())\n'
                          'def add(a,b):return a+b\n'
                          'stream=starmap(add,[list(range(n))])\n'
                          'print("created")\n'
                          'print(next(stream))\n',
 'dynamic_fixed_arity_3': 'from itertools import starmap\n'
                          'n=int(input())\n'
                          'def add(a,b):return a+b\n'
                          'stream=starmap(add,[list(range(n))])\n'
                          'print("created")\n'
                          'print(next(stream))\n',
 'dynamic_variadic_rows': 'from itertools import starmap\n'
                          'n=int(input())\n'
                          'def total(*values):return sum(values)\n'
                          'rows=[list(range(n)),list(range(n+1))]\n'
                          'print(list(starmap(total,rows)))\n',
 'independent_map_gcd': 'from math import gcd\nprint(list(map(gcd,[6,9])))\n',
 'independent_map_isfinite': 'from math import isfinite\n'
                             'print(list(map(isfinite,[0.0,float("inf")])))\n',
 'keyword_argument_effects': 'from itertools import starmap\n'
                             'def mark(label,value):\n'
                             ' print(label)\n'
                             ' return value\n'
                             'starmap(function=mark("function",None),iterable=mark("iterable",[]))\n',
 'noncallable_empty': 'from itertools import starmap\n'
                      'stream=starmap(None,[])\n'
                      'print("created",list(stream),next(stream,9))\n',
 'noncallable_nonempty': 'from itertools import starmap\n'
                         'stream=starmap(None,[()])\n'
                         'print("created")\n'
                         'print(next(stream))\n',
 'noniterable_row_before_noncallable': 'from itertools import starmap\n'
                                       'stream=starmap(None,[3])\n'
                                       'print("created")\n'
                                       'print(next(stream))\n',
 'noniterable_source': 'from itertools import starmap\n'
                       'stream=starmap(None,3)\n'
                       'print("unreachable")\n',
 'ordinary_math_control': 'from math import gcd,isfinite\nprint(gcd(12,18),isfinite(0.0))\n',
 'shared_mutable_tuple_elements': 'from itertools import starmap\n'
                                  'payload=[1]\n'
                                  'def visit(a,b):\n'
                                  ' a.append(9)\n'
                                  ' return a is b,len(b)\n'
                                  'print(list(starmap(visit,[(payload,payload),(payload,payload)])))\n'
                                  'print(payload)\n',
 'source_acquisition_effects': 'from itertools import starmap\n'
                               'def add(a,b):return a+b\n'
                               'def mark(label,value):\n'
                               ' print(label)\n'
                               ' return value\n'
                               'class Rows:\n'
                               ' def __iter__(self):\n'
                               '  print("iter source")\n'
                               '  return iter([(1,2),(3,4)])\n'
                               'stream=starmap(mark("function",add),mark("source",Rows()))\n'
                               'print("created")\n'
                               'print(list(stream))\n',
 'starmap_function_and_builtin': 'from itertools import starmap\n'
                                 'def area(width,height):return width*height\n'
                                 'pairs=[(3,4),(5,7),(2,9)]\n'
                                 'print(list(starmap(area,pairs)))\n'
                                 'print(list(starmap(pow,[(2,5),(3,4)])))\n',
 'starmap_generator_source': 'from itertools import starmap\n'
                             'def rows():\n'
                             ' print("begin")\n'
                             ' yield (1,2)\n'
                             ' print("middle")\n'
                             ' yield (3,4)\n'
                             'def emit(left,right):\n'
                             ' print("call",left,right)\n'
                             ' return left+right\n'
                             'stream=starmap(emit,rows())\n'
                             'print("created")\n'
                             'print(next(stream))\n'
                             'print(list(stream))\n',
 'starmap_live_mutable_pairs': 'from itertools import starmap\n'
                               'events=[]\n'
                               'def add(left,right):\n'
                               ' events.append((left,right))\n'
                               ' return left+right\n'
                               'pairs=[[1,2],[3,4],[5,6]]\n'
                               'stream=starmap(add,pairs)\n'
                               'alias=stream\n'
                               'pairs[0][0]=8\n'
                               'print(events)\n'
                               'print(next(alias))\n'
                               'pairs.append([7,8])\n'
                               'print(list(stream),events,iter(alias) is alias)\n',
 'stored_map_gcd': 'from math import gcd\n'
                   'values=map(gcd,[6,9])\n'
                   'print(next(values),list(values))\n',
 'wrong_tuple_arity_after_one': 'from itertools import starmap\n'
                                'def add(a,b):return a+b\n'
                                'stream=starmap(add,[(1,2),(3,)])\n'
                                'print(next(stream))\n'
                                'print(next(stream))\n',
 'zero_argument_rows': 'from itertools import starmap\n'
                       'def ping():return 7\n'
                       'print(list(starmap(ping,[(),(),()])))\n'}

INPUTS={'arity_argument_effects': '',
 'bound_method_rows': '',
 'callback_mutates_original_row': '',
 'callback_reentrant_next': '',
 'callback_stop_and_resume': '',
 'canonical_member_callback': '',
 'captured_constructor_rebinding': '',
 'class_frame_map_isfinite': '',
 'closed_callable_alternatives': '0\n',
 'custom_inner_row_boundary': '',
 'default_argument_rows': '',
 'dynamic_builtin_expansion_boundary': '',
 'dynamic_fixed_arity_0': '0\n',
 'dynamic_fixed_arity_1': '1\n',
 'dynamic_fixed_arity_2': '2\n',
 'dynamic_fixed_arity_3': '3\n',
 'dynamic_variadic_rows': '3\n',
 'independent_map_gcd': '',
 'independent_map_isfinite': '',
 'keyword_argument_effects': '',
 'noncallable_empty': '',
 'noncallable_nonempty': '',
 'noniterable_row_before_noncallable': '',
 'noniterable_source': '',
 'ordinary_math_control': '',
 'shared_mutable_tuple_elements': '',
 'source_acquisition_effects': '',
 'starmap_function_and_builtin': '',
 'starmap_generator_source': '',
 'starmap_live_mutable_pairs': '',
 'stored_map_gcd': '',
 'wrong_tuple_arity_after_one': '',
 'zero_argument_rows': ''}

BOUNDARIES={'custom_inner_row_boundary': 'from itertools import starmap\n'
                              'class Row:\n'
                              ' def __iter__(self):\n'
                              '  print("iter row")\n'
                              '  return iter([1,2])\n'
                              ' def __len__(self):\n'
                              '  print("len row")\n'
                              '  return 2\n'
                              'def add(a,b):\n'
                              ' print("call",a,b)\n'
                              ' return a+b\n'
                              'stream=starmap(add,[Row()])\n'
                              'print("created")\n'
                              'print(next(stream))\n',
 'dynamic_builtin_expansion_boundary': 'from itertools import starmap\n'
                                       'rows=[[2,5]]\n'
                                       'print(list(starmap(pow,rows)))\n'}

class StarmapExecutionTests(unittest.TestCase):
    cases=CASES
    inputs=INPUTS
    check=iterator_tests.IteratorExecutionTests.check

    def test_arity_argument_effects(self):
        self.check('arity_argument_effects')

    def test_bound_method_rows(self):
        self.check('bound_method_rows')

    def test_callback_mutates_original_row(self):
        self.check('callback_mutates_original_row')

    def test_callback_reentrant_next(self):
        self.check('callback_reentrant_next')

    def test_callback_stop_and_resume(self):
        self.check('callback_stop_and_resume')

    def test_canonical_member_callback(self):
        self.check('canonical_member_callback')

    def test_captured_constructor_rebinding(self):
        self.check('captured_constructor_rebinding')

    def test_class_frame_map_isfinite(self):
        self.check('class_frame_map_isfinite')

    def test_closed_callable_alternatives(self):
        self.check('closed_callable_alternatives')

    def test_default_argument_rows(self):
        self.check('default_argument_rows')

    def test_dynamic_fixed_arity_0(self):
        self.check('dynamic_fixed_arity_0')

    def test_dynamic_fixed_arity_1(self):
        self.check('dynamic_fixed_arity_1')

    def test_dynamic_fixed_arity_2(self):
        self.check('dynamic_fixed_arity_2')

    def test_dynamic_fixed_arity_3(self):
        self.check('dynamic_fixed_arity_3')

    def test_dynamic_variadic_rows(self):
        self.check('dynamic_variadic_rows')

    def test_independent_map_gcd(self):
        self.check('independent_map_gcd')

    def test_independent_map_isfinite(self):
        self.check('independent_map_isfinite')

    def test_keyword_argument_effects(self):
        self.check('keyword_argument_effects')

    def test_noncallable_empty(self):
        self.check('noncallable_empty')

    def test_noncallable_nonempty(self):
        self.check('noncallable_nonempty')

    def test_noniterable_row_before_noncallable(self):
        self.check('noniterable_row_before_noncallable')

    def test_noniterable_source(self):
        self.check('noniterable_source')

    def test_ordinary_math_control(self):
        self.check('ordinary_math_control')

    def test_shared_mutable_tuple_elements(self):
        self.check('shared_mutable_tuple_elements')

    def test_source_acquisition_effects(self):
        self.check('source_acquisition_effects')

    def test_starmap_function_and_builtin(self):
        self.check('starmap_function_and_builtin')

    def test_starmap_generator_source(self):
        self.check('starmap_generator_source')

    def test_starmap_live_mutable_pairs(self):
        self.check('starmap_live_mutable_pairs')

    def test_stored_map_gcd(self):
        self.check('stored_map_gcd')

    def test_wrong_tuple_arity_after_one(self):
        self.check('wrong_tuple_arity_after_one')

    def test_zero_argument_rows(self):
        self.check('zero_argument_rows')

    def test_unproved_row_and_expanded_builtin_boundaries(self):
        for name,source in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none',filename='iterator_case.py'))
                    self.assertFalse(result.success)
                    self.assertIsNone(result.rust_source)
                    self.assertTrue(result.diagnostics)
                    self.assertIn('E006',str(result.diagnostics[0]))
                    self.assertIn('row' if name.startswith('custom') else 'expanded',str(result.diagnostics[0]))
