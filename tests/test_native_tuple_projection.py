"""Stable local tuple projections preserve aliases and evaluation order."""
import ast,shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_tuple_projection import read
import test_native_class_iterators as iterator_tests

CASES={'class_leaves': 'class Box:\n'
                 ' def __init__(self,value):self.value=value\n'
                 'def choose(pair):return pair[0].value+pair[1].value\n'
                 'print(choose((Box(3),Box(7))))\n',
 'list_leaf_alias': 'class Picker:\n'
                    ' def select(self,pair):return pair[0]\n'
                    'left=[1]\n'
                    'right=[2]\n'
                    'pair=(left,right)\n'
                    'selected=Picker().select(pair)\n'
                    'selected.append(9)\n'
                    'print(left,right,selected is left)\n',
 'same_class_alias': 'class Box:\n'
                     ' def __init__(self,value):self.value=value\n'
                     'def same(pair):return pair[0]is pair[1]\n'
                     'value=Box(4)\n'
                     'print(same((value,value)),same((value,Box(4))))\n',
 'nested_tuple_chain': 'class Box:\n'
                       ' def __init__(self,value):self.value=value\n'
                       'def choose(pair):return pair[0][1],pair[1][0]\n'
                       'a,b=Box(1),Box(2)\n'
                       'x,y=choose(((a,b),(a,b)))\n'
                       'x.value+=7\n'
                       'print(a.value,b.value,x is b,y is a)\n',
 'scalar_tuple': 'class Sum:\n'
                 ' def total(self,pair):return pair[0]+pair[1]\n'
                 'print(Sum().total((3,8)))\n',
 'stable_local_rebinding': 'class Box:\n'
                           ' def __init__(self,value):self.value=value\n'
                           'def choose(flag):\n'
                           ' pair=(Box(1),Box(2))\n'
                           ' alias=pair\n'
                           ' if flag:pair=(Box(7),Box(8))\n'
                           ' pair[0].value+=3\n'
                           ' return alias[0].value,pair[0].value\n'
                           'print(choose(False),choose(True))\n',
 'later_argument_mutation': 'class Box:\n'
                            ' def __init__(self,value):self.value=value\n'
                            'def later(pair):\n'
                            ' print("later")\n'
                            ' pair[0].value=9\n'
                            ' return 7\n'
                            'def use(first,second):return first.value,second\n'
                            'def main():\n'
                            ' pair=(Box(1),Box(2))\n'
                            ' print(use(pair[0],later(pair)))\n'
                            'main()\n',
 'root_error_before_later_argument_0': 'class Box:\n'
                                       ' def '
                                       '__init__(self,value):self.value=value\n'
                                       'def later():\n'
                                       ' print("unreachable")\n'
                                       ' return 1\n'
                                       'def use(first,second):return '
                                       'first.value+second\n'
                                       'def choose(flag):\n'
                                       ' if flag:pair=(Box(1),Box(2))\n'
                                       ' return use(pair[0],later())\n'
                                       'print(choose(bool(int(input()))))\n',
 'root_error_before_later_argument_1': 'class Box:\n'
                                       ' def '
                                       '__init__(self,value):self.value=value\n'
                                       'def later():\n'
                                       ' print("unreachable")\n'
                                       ' return 1\n'
                                       'def use(first,second):return '
                                       'first.value+second\n'
                                       'def choose(flag):\n'
                                       ' if flag:pair=(Box(1),Box(2))\n'
                                       ' return use(pair[0],later())\n'
                                       'print(choose(bool(int(input()))))\n',
 'zero_trip_unbound_0': 'class Box:\n'
                        ' def __init__(self,value):self.value=value\n'
                        'def choose(count):\n'
                        ' for pair in [(Box(3),Box(7))][:count]:pass\n'
                        ' return pair[0].value\n'
                        'print(choose(int(input())))\n',
 'zero_trip_unbound_1': 'class Box:\n'
                        ' def __init__(self,value):self.value=value\n'
                        'def choose(count):\n'
                        ' for pair in [(Box(3),Box(7))][:count]:pass\n'
                        ' return pair[0].value\n'
                        'print(choose(int(input())))\n',
 'module_owned_excluded': 'class Box:\n'
                          ' def __init__(self,value):self.value=value\n'
                          'pair=(Box(3),Box(7))\n'
                          'def choose():return pair[0].value\n'
                          'print(choose())\n',
 'captured_excluded': 'class Box:\n'
                      ' def __init__(self,value):self.value=value\n'
                      'def choose():\n'
                      ' pair=(Box(3),Box(7))\n'
                      ' def read():return pair[0].value\n'
                      ' pair=(Box(8),Box(9))\n'
                      ' return read()\n'
                      'print(choose())\n',
 'comprehension_target_excluded': 'class Box:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'def choose(pair):return [pair[0].value for '
                                  'pair in [(Box(1),Box(2)),pair]]\n'
                                  'print(choose((Box(3),Box(4))))\n',
 'outer_local_in_comprehension': 'class Box:\n'
                                 ' def __init__(self,value):self.value=value\n'
                                 'def choose(pair):return [pair[0].value+i for '
                                 'i in range(3)]\n'
                                 'print(choose((Box(3),Box(4))))\n',
 'generator_state_excluded': 'class Box:\n'
                             ' def __init__(self,value):self.value=value\n'
                             'def choose(pair):return sum(pair[0].value for '
                             'unused in range(3))\n'
                             'print(choose((Box(3),Box(4))))\n',
 'point_storage_union_excluded': 'class Box:\n'
                                 ' def __init__(self,value):self.value=value\n'
                                 'def choose(flag):\n'
                                 ' pair=(Box(3),Box(4))\n'
                                 ' if flag:pair=None\n'
                                 ' if pair is None:return 0\n'
                                 ' return pair[0].value\n'
                                 'print(choose(False),choose(True))\n',
 'final_tuple_leaf': 'class Box:\n'
                     ' def __init__(self,value):self.value=value\n'
                     'def choose(pair):return pair[0]\n'
                     'a,b=Box(3),Box(4)\n'
                     'selected=choose(((a,b),7))\n'
                     'selected[0].value=11\n'
                     'print(a.value,b.value)\n',
 'delete_then_unbound': 'class Box:\n'
                        ' def __init__(self,value):self.value=value\n'
                        'def choose():\n'
                        ' pair=(Box(3),Box(4))\n'
                        ' del pair\n'
                        ' return pair[0].value\n'
                        'print(choose())\n',
 'selection_before_property_error': 'class Box:\n'
                                    ' def '
                                    '__init__(self,value):self.value=value\n'
                                    'def choose(pair):return pair[0].missing\n'
                                    'print(choose((Box(3),Box(4))))\n',
 'dynamic_index_boundary': 'class Box:\n'
                           ' def __init__(self,value):self.value=value\n'
                           'def choose(pair,index):return pair[index].value\n'
                           'print(choose((Box(3),Box(4)),int(input())))\n',
 'negative_index_boundary': 'class Box:\n'
                            ' def __init__(self,value):self.value=value\n'
                            'def choose(pair):return pair[-1].value\n'
                            'print(choose((Box(3),Box(4))))\n',
 'named_root': 'from typing import NamedTuple\n'
               'class Pair(NamedTuple):\n'
               ' left:int\n'
               ' right:int\n'
               'def choose(pair):return pair[0]+pair[1]\n'
               'print(choose(Pair(3,7)))\n',
 'named_intermediate': 'from typing import NamedTuple\n'
                       'class Pair(NamedTuple):\n'
                       ' left:int\n'
                       ' right:int\n'
                       'def choose(value):return value[0][1]\n'
                       'print(choose((Pair(3,7),9)))\n',
 'named_leaf': 'from typing import NamedTuple\n'
               'class Pair(NamedTuple):\n'
               ' left:int\n'
               ' right:int\n'
               'def choose(value):return value[0]\n'
               'print(choose((Pair(3,7),9)))\n'}
INPUTS={'root_error_before_later_argument_0': '0\n',
 'root_error_before_later_argument_1': '1\n',
 'zero_trip_unbound_0': '0\n',
 'zero_trip_unbound_1': '1\n',
 'dynamic_index_boundary': '0\n'}
BOUNDARIES={'namedtuple_excluded': 'class Box:\n'
                        ' def __init__(self,value):self.value=value\n'
                        'from collections import namedtuple\n'
                        'Pair=namedtuple("Pair","left right")\n'
                        'def choose(pair):return pair[0].value\n'
                        'print(choose(Pair(Box(3),Box(4))))\n',
 'invalid_index_boundary': 'class Box:\n'
                           ' def __init__(self,value):self.value=value\n'
                           'def choose(pair):return pair[2].value\n'
                           'print(choose((Box(3),Box(4))))\n'}

class TupleProjectionProofs(unittest.TestCase):
 def compile(self,name,mode='i64',disabled=False):
  calls=[]
  def project(emitter,node):
   result=None if disabled else read(emitter,node)
   if result is not None:
    self.assertIsInstance(node,ast.Subscript)
    self.assertGreaterEqual(emitter.model.unit.ordinal(node),0)
    calls.append((emitter.plan.scope,node.lineno,result.code))
   return result
  with patch('py2fastrust.native_tuple_projection.read',side_effect=project):
   result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return result,calls
 def test_local_projection_returns_only_an_owned_selected_leaf(self):
  result,calls=self.compile('class_leaves')
  self.assertEqual(len(calls),2)
  for scope,line,code in calls:
   self.assertIn('.as_ref().ok_or_else(',code)
   self.assertRegex(code,r'\(class_temp_\d+\.[01]\)\.clone\(\)')
   self.assertNotRegex(code,r'class_local_\d+\.clone\(\)')
 def test_nested_projection_uses_one_root_check(self):
  result,calls=self.compile('nested_tuple_chain')
  self.assertEqual(len(calls),2)
  self.assertTrue(all(code.count('.ok_or_else(')==1 for _,_,code in calls))
  self.assertTrue(all(code.count('.clone()')==1 for _,_,code in calls))
 def test_unproved_storage_and_foreign_bindings_keep_existing_emission(self):
  names=('module_owned_excluded','captured_excluded','comprehension_target_excluded',
         'outer_local_in_comprehension','generator_state_excluded',
         'point_storage_union_excluded','negative_index_boundary','dynamic_index_boundary')
  for name in names:
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.compile(name,mode)
     old,_=self.compile(name,mode,disabled=True)
     self.assertFalse(calls)
     self.assertEqual(result.rust_source,old.rust_source)
 def test_named_tuple_receivers_and_fields_remain_unmodified(self):
  for name in ('named_root','named_intermediate','named_leaf'):
   result,calls=self.compile(name)
   old,_=self.compile(name,disabled=True)
   self.assertFalse(calls)
   self.assertEqual(result.rust_source,old.rust_source)
 def test_existing_unsupported_invocations_keep_positioned_diagnostics(self):
  for source in BOUNDARIES.values():
   for mode in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=mode,license='none'))
    self.assertFalse(result.success)
    self.assertTrue(result.diagnostics)
    self.assertTrue(all(d.code=='E006'for d in result.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class TupleProjectionExecution(unittest.TestCase):
 cases=CASES
 inputs=INPUTS
 check=iterator_tests.IteratorExecutionTests.check
 def test_class_leaves(self):self.check('class_leaves')
 def test_list_leaf_alias(self):self.check('list_leaf_alias')
 def test_same_class_alias(self):self.check('same_class_alias')
 def test_nested_tuple_chain(self):self.check('nested_tuple_chain')
 def test_scalar_tuple(self):self.check('scalar_tuple')
 def test_stable_local_rebinding(self):self.check('stable_local_rebinding')
 def test_later_argument_mutation(self):self.check('later_argument_mutation')
 def test_root_error_before_later_argument_0(self):self.check('root_error_before_later_argument_0')
 def test_root_error_before_later_argument_1(self):self.check('root_error_before_later_argument_1')
 def test_zero_trip_unbound_0(self):self.check('zero_trip_unbound_0')
 def test_zero_trip_unbound_1(self):self.check('zero_trip_unbound_1')
 def test_module_owned_excluded(self):self.check('module_owned_excluded')
 def test_captured_excluded(self):self.check('captured_excluded')
 def test_comprehension_target_excluded(self):self.check('comprehension_target_excluded')
 def test_outer_local_in_comprehension(self):self.check('outer_local_in_comprehension')
 def test_generator_state_excluded(self):self.check('generator_state_excluded')
 def test_point_storage_union_excluded(self):self.check('point_storage_union_excluded')
 def test_final_tuple_leaf(self):self.check('final_tuple_leaf')
 def test_delete_then_unbound(self):self.check('delete_then_unbound')
 def test_selection_before_property_error(self):self.check('selection_before_property_error')
 def test_dynamic_index_boundary(self):self.check('dynamic_index_boundary')
 def test_negative_index_boundary(self):self.check('negative_index_boundary')
 def test_named_root(self):self.check('named_root')
 def test_named_intermediate(self):self.check('named_intermediate')
 def test_named_leaf(self):self.check('named_leaf')
