"""Normal source completion contributes a stable actual None result."""
import ast
import unittest
import test_native_annotations_assertions as assertion_tests
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,shape
from py2fastrust.native_types import NullableType

CASES={
 'method_empty_no_match_and_return':('class Search:\n def find(self,values,target):\n  for value in values:\n   if value>=target:return value\nsearch=Search()\nprint(search.find([],1),search.find([2,4],9),search.find([2,4],3))\n',('',)),
 'reverse_list_method_fallthrough':('class Search:\n def floor(self,rows,target):\n  for row in reversed(rows):\n   if row[0]<=target:return row[-1]\nsearch=Search()\nprint(search.floor([],3),search.floor([[2,3],[5,6]],1),search.floor([[2,3],[5,6]],5))\n',('',)),
 'canonical_cursor_exhaustion':('class Search:\n def find(self,values,target):\n  for value in iter(values):\n   if value==target:return value\nsearch=Search()\nprint(search.find([],1),search.find([3,4],1),search.find([3,4],4))\n',('',)),
 'source_generator_cursor_exhaustion':('def values(limit):\n for item in range(limit):yield item\nclass Search:\n def find(self,limit,target):\n  for value in values(limit):\n   if value==target:return value\nsearch=Search()\nprint(search.find(0,1),search.find(3,8),search.find(3,2))\n',('',)),
 'ordinary_function_data_returns':('choices=[3,5]\ndef find(target):\n for value in choices:\n  if value>=target:return value\nprint(find(2),find(4),find(9))\n',('',)),
 'branch_and_explicit_none_returns':('class Search:\n def find(self,mode):\n  if mode<0:return\n  if mode>0:return mode\nsearch=Search()\nprint(search.find(-1),search.find(0),search.find(3))\n',('',)),
 'nested_loops_and_empty_outer_inner':('class Search:\n def find(self,rows,target):\n  for row in rows:\n   for value in row:\n    if value==target:return value\nsearch=Search()\nprint(search.find([],1),search.find([[],[2]],1),search.find([[2],[3]],3))\n',('',)),
 'for_else_effect_before_completion':('class Search:\n def find(self,values,target):\n  for value in values:\n   if value==target:return value\n  else:print("exhausted")\nsearch=Search()\nprint(search.find([],1),search.find([2],1),search.find([2],2))\n',('',)),
 'while_break_and_no_match':('class Search:\n def find(self,values,target):\n  index=0\n  while index<len(values):\n   value=values[index]\n   if value==target:return value\n   if value<0:break\n   index+=1\nsearch=Search()\nprint(search.find([],1),search.find([-1,1],1),search.find([0,1],1))\n',('',)),
 'recursive_nullable_result':('class Search:\n def find(self,values,index,target):\n  if index<len(values):\n   if values[index]==target:return values[index]\n   return self.find(values,index+1,target)\nsearch=Search()\nprint(search.find([],0,1),search.find([2,3],0,8),search.find([2,3],0,3))\n',('',)),
 'default_and_retained_method_alias':('class Search:\n def find(self,values,target=3):\n  for value in values:\n   if value==target:return value\nsearch=Search()\nlookup=search.find\nprint(lookup([]),lookup([2,3]),lookup([2,3],8))\n',('',)),
 'finally_runs_on_return_and_fallthrough':('class Search:\n def find(self,values,target):\n  try:\n   for value in values:\n    if value==target:return value\n  finally:print("cleanup")\nsearch=Search()\nprint(search.find([],1),search.find([2],9),search.find([2],2))\n',('',)),
 'handler_and_finally_completion':('class Search:\n def find(self,values,denominator):\n  try:\n   for value in values:\n    return value//denominator\n  except ZeroDivisionError:print("zero")\n  finally:print("cleanup")\nsearch=Search()\nprint(search.find([],1),search.find([4],0),search.find([4],2))\n',('',)),
 'callback_mutates_live_list':('class Search:\n def grow(self,values):values.append(7)\n def find(self,values,target):\n  for value in values:\n   if value==0:self.grow(values)\n   if value==target:return value\nsearch=Search()\nprint(search.find([],7),search.find([0],7),search.find([1],7))\n',('',)),
 'context_cleanup_on_return_and_fallthrough':('class Scope:\n def __enter__(self):print("enter")\n def __exit__(self,kind,error,trace):\n  print("exit")\n  return False\nclass Search:\n def find(self,values,target):\n  with Scope():\n   for value in values:\n    if value==target:return value\nsearch=Search()\nprint(search.find([],1),search.find([2],8),search.find([2],2))\n',('',)),
 'lambda_returns_its_expression':('class Search:\n def choose(self):\n  operation=lambda value:value+1\n  return operation(3)\nprint(Search().choose())\n',('',)),
 'abrupt_before_possible_return':('class Search:\n def find(self,values):\n  for value in values:return 10//value\nprint(Search().find([int(input())]))\n',('0\n','2\n')),
 'no_normal_exit_with_guaranteed_return':('class Search:\n def find(self,value):\n  while True:\n   if value<0:raise ValueError("negative")\n   return value+1\nprint(Search().find(int(input())))\n',('2\n','-1\n')),
}

class ImplicitReturnExecutionTests(unittest.TestCase):
 compare=assertion_tests.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
BOUNDARIES={'finally_runs_on_return_and_fallthrough','handler_and_finally_completion'}
for _name in CASES:
 if _name not in BOUNDARIES:setattr(ImplicitReturnExecutionTests,'test_'+_name,_case(_name))

class ImplicitReturnBoundaryTests(unittest.TestCase):
 def test_nested_loop_exception_unwinding_retains_a_positioned_boundary(self):
  for name in sorted(BOUNDARIES):
   source=CASES[name][0]
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename='implicit_return.py'))
    self.assertFalse(result.success,(name,integer))
    self.assertTrue(any(item.code=='E006'and item.line==3 and 'exception-handler routing and unwinding'in item.message for item in result.diagnostics),result.diagnostics)

class ImplicitReturnModelTests(unittest.TestCase):
 def test_final_validation_keeps_genuine_completion_in_registered_producers(self):
  source=CASES['method_empty_no_match_and_return'][0]
  unit=build_program(source,'implicit_return.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  plan=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='find')
  self.assertEqual(shape(plan.result),NullableType('int'))
  value=model.node_cells[(plan.index,id(plan.node),'implicit_return')]
  self.assertEqual(shape(value),'none')
  normal=model.analyze_body(plan,{**model.global_symbols,**plan.arguments})
  self.assertIsNotNone(normal)
  self.assertIs(model.node_cells[(plan.index,id(plan.node),'implicit_return')],value)
  self.assertEqual(shape(plan.result),NullableType('int'))
 def test_abrupt_only_body_does_not_gain_none_or_a_completion_producer(self):
  source=CASES['no_normal_exit_with_guaranteed_return'][0]
  unit=build_program(source,'implicit_return.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  plan=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='find')
  self.assertEqual(shape(plan.result),'int')
  self.assertNotIn((plan.index,id(plan.node),'implicit_return'),model.node_cells)
 def test_lambda_has_no_ordinary_fallthrough_producer(self):
  source=CASES['lambda_returns_its_expression'][0]
  unit=build_program(source,'implicit_return.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  plan=next(plan for plan in model.plans if isinstance(plan.node,ast.Lambda))
  self.assertEqual(shape(plan.result),'int')
  self.assertNotIn((plan.index,id(plan.node),'implicit_return'),model.node_cells)
 def test_generator_results_keep_the_yield_protocol(self):
  source='class Owner:\n def values(self):\n  yield 3\nprint(list(Owner().values()))\n'
  unit=build_program(source,'implicit_return.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  plan=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='values')
  self.assertIsNotNone(getattr(plan,'source_generator',None))
  self.assertNotIn((plan.index,id(plan.node),'implicit_return'),model.node_cells)

if __name__=='__main__':unittest.main()
