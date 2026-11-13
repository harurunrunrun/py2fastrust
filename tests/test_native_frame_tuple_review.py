"""Independent tuple-order review: original error direction and bottom storage."""
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_frame_splits as support

CASES = {'fixed_left_lt': 'class Scope:pass\na=("x",)\nb=tuple([1])\nprint("before")\nprint(a < b)\n',
 'fixed_left_le': 'class Scope:pass\na=("x",)\nb=tuple([1])\nprint("before")\nprint(a <= b)\n',
 'fixed_left_gt': 'class Scope:pass\na=("x",)\nb=tuple([1])\nprint("before")\nprint(a > b)\n',
 'fixed_left_ge': 'class Scope:pass\na=("x",)\nb=tuple([1])\nprint("before")\nprint(a >= b)\n',
 'runtime_both_le': 'class Scope:pass\n'
                    'a=tuple(["x"])\n'
                    'b=tuple([1])\n'
                    'print("before")\n'
                    'print(a <= b)\n',
 'runtime_left_le': 'class Scope:pass\na=tuple(["x"])\nb=(1,)\nprint("before")\nprint(a <= b)\n',
 'runtime_both_ge': 'class Scope:pass\n'
                    'a=tuple(["x"])\n'
                    'b=tuple([1])\n'
                    'print("before")\n'
                    'print(a >= b)\n',
 'runtime_left_ge': 'class Scope:pass\na=tuple(["x"])\nb=(1,)\nprint("before")\nprint(a >= b)\n',
 'empty_pack_sort': 'def empty(*xs):return xs\n'
                    'a=empty()\n'
                    'print(sorted([a,(1,),()]))\n'
                    'print(min(a,(1,)),max(a,(1,)))\n',
 'empty_float_length_safe': 'def empty(*xs):return xs\n'
                            'a=empty()\n'
                            'b=tuple([float("nan")])\n'
                            'print(a<b,a<=b,b>a,b>=a,a>a)\n',
 'named_record_runtime_sort': 'from typing import NamedTuple\n'
                              'class Point(NamedTuple):\n'
                              ' x:int\n'
                              ' y:int\n'
                              'a=Point(1,3)\n'
                              'b=tuple([1,2])\n'
                              'print(a>b,a>=b,b<a,b<=a)\n'
                              'print(sorted([a,b,(0,9)]))\n',
 'named_nested_runtime_sort': 'from typing import NamedTuple\n'
                              'class Point(NamedTuple):\n'
                              ' x:int\n'
                              ' y:int\n'
                              'a=tuple([Point(1,3)])\n'
                              'b=tuple([(1,2)])\n'
                              'print(a>b,b<a)\n'
                              'print(sorted([a,b]))\n',
 'none_equal_shortcut': 'class Scope:pass\n'
                        'a=tuple([None])\n'
                        'b=(None,)\n'
                        'print(a<=b,a>=b,b<=a,b>=a,a in tuple([a,b]))\n',
 'runtime_lt_control': 'class Scope:pass\n'
                       'a=tuple(["x"])\n'
                       'b=tuple([1])\n'
                       'print("before")\n'
                       'print(a<b)\n'}

BOUNDARIES = {'empty_pack_membership': 'def empty(*xs):return xs\n'
                          'a=empty()\n'
                          'print(a in tuple([a]),a in ((),(1,)),a in [(),a])\n',
 'nested_empty_order': 'def empty(*xs):return xs\n'
                       'a=tuple([empty()])\n'
                       'b=tuple([()])\n'
                       'print(a<=b,a>=b,a==b)\n'
                       'print(sorted([a,b]))\n',
 'empty_float_membership': 'def empty(*xs):return xs\n'
                           'a=empty()\n'
                           'print(float("nan") in a,float("nan") not in a)\n',
 'empty_plain_object_membership': 'class Item:pass\n'
                                  'def empty(*xs):return xs\n'
                                  'a=empty()\n'
                                  'x=Item()\n'
                                  'print(x in a,x not in a)\n',
 'captured_effects_once': 'class Scope:pass\n'
                          'def mark(label,value):\n'
                          ' print(label)\n'
                          ' return value\n'
                          'a=mark("left",tuple([1,2]))\n'
                          'print(a<=mark("right",(1,3)))\n'
                          'print(mark("item",2) in mark("container",a))\n',
 'shared_nan_tuple_identity': 'class Scope:pass\n'
                              'nan=float("nan")\n'
                              'a=tuple([nan])\n'
                              'b=tuple([nan])\n'
                              'print(a==b,a<b,a<=b)\n',
 'observable_custom_equality': 'class Item:\n'
                               ' def __eq__(self,other):\n'
                               '  print("eq")\n'
                               '  return True\n'
                               'a=tuple([Item()])\n'
                               'print(Item() in a)\n'}

CASES["shared_nan_tuple_identity"]=BOUNDARIES.pop("shared_nan_tuple_identity")

class FrameTupleReviewProtocolTests(unittest.TestCase):
    def test_remaining_bottom_and_callable_proofs_are_positioned(self):
        for name,source in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn('Source:',str(result.diagnostics[0]))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrameTupleReviewExecutionTests(unittest.TestCase):
    exercise=support.SplitExecutionTests.exercise


def execution(source):
    def test(self):self.exercise(source)
    return test

for name,source in CASES.items():
    setattr(FrameTupleReviewExecutionTests,'test_'+name,execution(source))
