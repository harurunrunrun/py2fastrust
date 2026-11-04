"""Control-flow carrier liveness preserves original binding effects and reads."""
import ast,shutil,unittest
from types import SimpleNamespace
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_constraints import analyze
from py2fastrust.native_join_liveness import Flow,UnsupportedFlow

CASES={'dead_nested_rows': 'def total(rows):\n'
                     ' for unused in range(3):\n'
                     '  for index,row in enumerate(rows):\n'
                     '   if row[0]<0:continue\n'
                     '   target=rows[index]\n'
                     '   target[0]+=index\n'
                     ' return sum(sum(row)for row in rows)\n'
                     'print(total([[1],[2],[-3]]))\n',
 'live_postloop_row_0': 'rows=[[1],[2],[3]]\n'
                        'count=int(input())\n'
                        'for row in rows[:count]:\n'
                        ' row[0]+=10\n'
                        'print(row,rows)\n',
 'live_postloop_row_1': 'rows=[[1],[2],[3]]\n'
                        'count=int(input())\n'
                        'for row in rows[:count]:\n'
                        ' row[0]+=10\n'
                        'print(row,rows)\n',
 'live_postloop_row_2': 'rows=[[1],[2],[3]]\n'
                        'count=int(input())\n'
                        'for row in rows[:count]:\n'
                        ' row[0]+=10\n'
                        'print(row,rows)\n',
 'zero_trip_retains_owner_0': 'row=[7]\n'
                              'alias=row\n'
                              'for row in range(int(input())):\n'
                              ' pass\n'
                              'alias.append(8)\n'
                              'print(row,alias)\n',
 'zero_trip_retains_owner_1': 'row=[7]\n'
                              'alias=row\n'
                              'for row in range(int(input())):\n'
                              ' pass\n'
                              'alias.append(8)\n'
                              'print(row,alias)\n',
 'skipped_store_live_exit': 'row=[7]\n'
                            'for i in range(4):\n'
                            ' if i==3:continue\n'
                            ' row=[i]\n'
                            'print(row)\n',
 'while_carried_read': 'i=0\n'
                       'row=[2]\n'
                       'while i<5:\n'
                       ' if i%2:row[0]+=i\n'
                       ' else:row=[row[0]+2]\n'
                       ' i+=1\n'
                       'print(row)\n',
 'break_keeps_current_binding': 'row=[9]\n'
                                'for i in range(5):\n'
                                ' row=[i]\n'
                                ' if i==2:break\n'
                                'print(row)\n',
 'continue_to_outer_read': 'result=[]\n'
                           'for i in range(3):\n'
                           ' for j in range(4):\n'
                           '  row=[i,j]\n'
                           '  if j==1:continue\n'
                           '  if j==2:break\n'
                           ' result.append(row)\n'
                           'print(result)\n',
 'delete_postloop_name': 'for row in []:\n pass\ndel row\n',
 'alias_payload_survives': 'rows=[[1],[2]]\n'
                           'alias=rows[1]\n'
                           'for row in rows:\n'
                           ' row[0]+=3\n'
                           'row=0\n'
                           'alias.append(8)\n'
                           'print(rows,alias,row)\n',
 'return_current_row': 'def choose(rows):\n'
                       ' for row in rows:\n'
                       '  if row[0]>1:return row\n'
                       ' return [0]\n'
                       'rows=[[1],[3]]\n'
                       'answer=choose(rows)\n'
                       'answer.append(9)\n'
                       'print(rows,answer)\n',
 'exception_before_dead_join': 'rows=[[1],[]]\n'
                               'for row in rows:\n'
                               ' print("visit",len(row))\n'
                               ' target=row[0]\n'
                               'print("unreachable")\n',
 'comprehension_scope_is_distinct': 'def total(rows):\n'
                                    ' for row in rows:\n'
                                    '  row[0]+=1\n'
                                    ' return sum(row[0]for row in rows)\n'
                                    'print(total([[1],[2]]))\n',
 'generator_free_cell_is_live': 'def total(rows):\n'
                                ' row=[5]\n'
                                ' for i in range(3):\n'
                                '  row=[row[0]+i]\n'
                                ' return sum(row[0]for unused in range(2))\n'
                                'print(total([[1]]))\n',
 'closure_observes_late_binding': 'def total(rows):\n'
                                  ' functions=[]\n'
                                  ' for row in rows:\n'
                                  '  functions.append(lambda:row[0])\n'
                                  ' row=[9]\n'
                                  ' return [function()for function in '
                                  'functions]\n'
                                  'print(total([[1],[2]]))\n',
 'global_function_observer': 'row=[0]\n'
                             'def observe():return row[0]\n'
                             'for i in range(3):\n'
                             ' row=[i]\n'
                             ' print(observe())\n'
                             'print(row)\n',
 'old_binding_read_before_target': 'row=[2,3]\n'
                                   'for row in [row]:\n'
                                   ' print(row)\n'
                                   'print(row)\n',
 'augmented_old_value': 'row=[1]\n'
                        'for i in range(3):\n'
                        ' row[0]+=i\n'
                        ' print(row[0])\n'
                        'print(row)\n',
 'for_else_observation_0': 'row=[8]\n'
                           'for i in range(int(input())):\n'
                           ' row=[i]\n'
                           ' if i==2:break\n'
                           'else:\n'
                           ' print("else",row)\n'
                           'print("last",row)\n',
 'for_else_observation_1': 'row=[8]\n'
                           'for i in range(int(input())):\n'
                           ' row=[i]\n'
                           ' if i==2:break\n'
                           'else:\n'
                           ' print("else",row)\n'
                           'print("last",row)\n',
 'for_else_observation_2': 'row=[8]\n'
                           'for i in range(int(input())):\n'
                           ' row=[i]\n'
                           ' if i==2:break\n'
                           'else:\n'
                           ' print("else",row)\n'
                           'print("last",row)\n',
 'nested_repeated_dead_binding': 'def total(rows):\n'
                                 ' result=0\n'
                                 ' for i in range(4):\n'
                                 '  for row in rows:\n'
                                 '   target=row\n'
                                 '   result+=target[0]+i\n'
                                 ' return result\n'
                                 'print(total([[1],[2],[3]]))\n',
 'shared_row_rebinding_on_branch': 'rows=[[1],[2]]\n'
                                   'row=rows[0]\n'
                                   'for i in range(3):\n'
                                   ' if i%2:row=rows[1]\n'
                                   ' row[0]+=i\n'
                                   'print(rows,row)\n',
 'delete_then_rebind': 'row=[7]\n'
                       'for i in range(3):\n'
                       ' del row\n'
                       ' row=[i]\n'
                       'print(row)\n',
 'unbound_conditional_store_0': 'for i in range(int(input())):\n'
                                ' if i:row=[i]\n'
                                'print(row)\n',
 'unbound_conditional_store_1': 'for i in range(int(input())):\n'
                                ' if i:row=[i]\n'
                                'print(row)\n',
 'unbound_conditional_store_2': 'for i in range(int(input())):\n'
                                ' if i:row=[i]\n'
                                'print(row)\n',
 'module_live_binding': 'for value in [[1],[2]]:\n'
                        ' pass\n'
                        'value:int\n'
                        'print(value)\n',
 'function_live_binding': 'def choose(rows):\n'
                          ' for value in rows:\n'
                          '  pass\n'
                          ' value:int\n'
                          ' return value\n'
                          'print(choose([[1],[2]]))\n',
 'zero_trip_annotation_0': 'value=[7]\n'
                           'for value in range(int(input())):\n'
                           ' pass\n'
                           'value:int\n'
                           'print(value)\n',
 'zero_trip_annotation_1': 'value=[7]\n'
                           'for value in range(int(input())):\n'
                           ' pass\n'
                           'value:int\n'
                           'print(value)\n',
 'unbound_annotation': 'for value in []:\n pass\nvalue:int\nprint(value)\n'}
INPUTS={'live_postloop_row_0': '0\n',
 'live_postloop_row_1': '1\n',
 'live_postloop_row_2': '3\n',
 'zero_trip_retains_owner_0': '0\n',
 'zero_trip_retains_owner_1': '3\n',
 'for_else_observation_0': '0\n',
 'for_else_observation_1': '2\n',
 'for_else_observation_2': '4\n',
 'unbound_conditional_store_0': '0\n',
 'unbound_conditional_store_1': '1\n',
 'unbound_conditional_store_2': '3\n',
 'zero_trip_annotation_0': '0\n',
 'zero_trip_annotation_1': '2\n'}
BOUNDARIES={'globals_observer': 'for row in [[1],[2]]:\n pass\nprint(globals()["row"])\n',
 'locals_observer_boundary': 'def total():\n'
                             ' for row in [[1],[2]]:\n'
                             '  pass\n'
                             ' return locals()["row"]\n'
                             'print(total())\n'}

class JoinLivenessProofs(unittest.TestCase):
 def flow(self,source,function=True):
  unit=parse_source(source,'liveness.py');before=ast.dump(unit.tree,include_attributes=True)
  result=analyze(unit)
  if function:
   definition=next(node for node in unit.tree.body if isinstance(node,ast.FunctionDef))
   facts=next(facts for(definition_id,_),facts in result.scopes.items()if definition_id==unit.ordinal(definition))
   function=SimpleNamespace(node=definition)
  else:facts=result.scopes[(None,())];function=None
  flow=Flow(SimpleNamespace(source_unit=unit,function=function,constraint_facts=facts,type_analysis=result))
  self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
  return unit,flow
 def test_generator_target_has_a_distinct_official_binding(self):
  unit,flow=self.flow(CASES['comprehension_scope_is_distinct'])
  loop=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.For))
  self.assertNotIn('row',flow.exits[id(loop)])
  self.assertNotIn('row',flow.pinned)
 def test_free_generator_cell_remains_live(self):
  unit,flow=self.flow(CASES['generator_free_cell_is_live'])
  loop=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.For))
  self.assertIn('row',flow.exits[id(loop)])
  self.assertIn('row',flow.pinned)
 def test_escaping_closure_cell_remains_live(self):
  # Original CP-first independent reviewer witness, without an unresolved
  # callback invocation in the factory body.
  source='def solve():\n value=1\n def read():\n  return value\n for i in range(3):\n  value=i+10\n return read\nprint(solve()())\n'
  unit,flow=self.flow(source)
  self.assertIn('value',flow.pinned)
 def test_unresolved_closure_invocation_keeps_the_conservative_path(self):
  with self.assertRaises(UnsupportedFlow):self.flow(CASES['closure_observes_late_binding'])
 def test_annotation_without_value_preserves_live_binding(self):
  unit,flow=self.flow(CASES['module_live_binding'],function=False)
  loop=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.For))
  self.assertIn('value',flow.exits[id(loop)])
 def test_namespace_observers_keep_the_conservative_path(self):
  for source in BOUNDARIES.values():
   with self.assertRaises(UnsupportedFlow):self.flow(source,function='def 'in source)
 def test_unimplemented_namespace_protocols_still_have_diagnostics(self):
  for source in BOUNDARIES.values():
   for mode in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=mode,license='none'))
    self.assertFalse(result.success)
    self.assertTrue(result.diagnostics)
    self.assertTrue(all(d.code=='E006'for d in result.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class JoinLivenessExecution(unittest.TestCase):
 # CP's exception object str/type and user frames are checked; optional CLI
 # spelling suggestions are not part of the exception object's message.
 cases=CASES
 inputs=INPUTS
 check=iterator_tests.IteratorExecutionTests.check
 def test_dead_nested_rows(self):self.check('dead_nested_rows')
 def test_live_postloop_row_0(self):self.check('live_postloop_row_0')
 def test_live_postloop_row_1(self):self.check('live_postloop_row_1')
 def test_live_postloop_row_2(self):self.check('live_postloop_row_2')
 def test_zero_trip_retains_owner_0(self):self.check('zero_trip_retains_owner_0')
 def test_zero_trip_retains_owner_1(self):self.check('zero_trip_retains_owner_1')
 def test_skipped_store_live_exit(self):self.check('skipped_store_live_exit')
 def test_while_carried_read(self):self.check('while_carried_read')
 def test_break_keeps_current_binding(self):self.check('break_keeps_current_binding')
 def test_continue_to_outer_read(self):self.check('continue_to_outer_read')
 def test_delete_postloop_name(self):self.check('delete_postloop_name')
 def test_alias_payload_survives(self):self.check('alias_payload_survives')
 def test_return_current_row(self):self.check('return_current_row')
 def test_exception_before_dead_join(self):self.check('exception_before_dead_join')
 def test_comprehension_scope_is_distinct(self):self.check('comprehension_scope_is_distinct')
 def test_generator_free_cell_is_live(self):self.check('generator_free_cell_is_live')
 def test_closure_observes_late_binding(self):self.check('closure_observes_late_binding')
 def test_global_function_observer(self):self.check('global_function_observer')
 def test_old_binding_read_before_target(self):self.check('old_binding_read_before_target')
 def test_augmented_old_value(self):self.check('augmented_old_value')
 def test_for_else_observation_0(self):self.check('for_else_observation_0')
 def test_for_else_observation_1(self):self.check('for_else_observation_1')
 def test_for_else_observation_2(self):self.check('for_else_observation_2')
 def test_nested_repeated_dead_binding(self):self.check('nested_repeated_dead_binding')
 def test_shared_row_rebinding_on_branch(self):self.check('shared_row_rebinding_on_branch')
 def test_delete_then_rebind(self):self.check('delete_then_rebind')
 def test_unbound_conditional_store_0(self):self.check('unbound_conditional_store_0')
 def test_unbound_conditional_store_1(self):self.check('unbound_conditional_store_1')
 def test_unbound_conditional_store_2(self):self.check('unbound_conditional_store_2')
 def test_module_live_binding(self):self.check('module_live_binding')
 def test_function_live_binding(self):self.check('function_live_binding')
 def test_zero_trip_annotation_0(self):self.check('zero_trip_annotation_0')
 def test_zero_trip_annotation_1(self):self.check('zero_trip_annotation_1')
 def test_unbound_annotation(self):self.check('unbound_annotation')
