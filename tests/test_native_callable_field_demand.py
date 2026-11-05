"""Private callable captures follow original invocation and observation demand."""
import ast,re,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_callable_field_demand as demand
from py2fastrust.native_callable_carriers import registry,payload_type
from py2fastrust.native_bound_methods import BoundMethodTarget
from tests import test_native_module_linking as execution

PROJECTS={'callee_snapshot_before_global_replacement': {'main.py': 'def square(value):return value*value\n'
                                                          'def offset(value):return value+20\n'
                                                          'selected=square\n'
                                                          'def later():\n'
                                                          ' global selected\n'
                                                          " print('later')\n"
                                                          ' selected=offset\n'
                                                          ' return 3\n'
                                                          'print(selected(later()),selected(3))\n'},
 'captured_state_finalizer_boundary': {'main.py': 'import gc\n'
                                                  'class Token:\n'
                                                  " def __del__(self):print('released')\n"
                                                  'def build():\n'
                                                  ' token=Token()\n'
                                                  ' def square(value):return value*value\n'
                                                  ' def retain():return token\n'
                                                  ' return square\n'
                                                  'callback=build()\n'
                                                  'gc.collect()\n'
                                                  'print(callback(4))\n'},
 'comprehension_callable_named_len': {'main.py': 'def factory():\n'
                                                 ' def square(value):return value*value\n'
                                                 ' return square\n'
                                                 'first=factory()\n'
                                                 'second=factory()\n'
                                                 'def observe(callback):\n'
                                                 ' print(callback is first)\n'
                                                 ' return callback(3)\n'
                                                 'class Pipeline:\n'
                                                 ' def run(self):return [len(second) for len in [observe]]\n'
                                                 'print(Pipeline().run())\n'},
 'default_state_and_definition_effects': {'main.py': 'number=3\n'
                                                     'def seed():\n'
                                                     " print('default',number)\n"
                                                     ' return number\n'
                                                     'def square(value=seed()):return value*value\n'
                                                     'saved=square\n'
                                                     'number=8\n'
                                                     'print(saved(),saved(5),square())\n'},
 'foreign_parameter_field_callback': {'main.py': 'import pure\n'
                                                 'class Pipeline:\n'
                                                 ' def __init__(self,callback):self.callback=callback\n'
                                                 ' def run(self,value):return self.callback(value)\n'
                                                 'def relay(callback,value):return callback(value)\n'
                                                 'p=Pipeline(pure.score)\n'
                                                 'print(p.run(6),relay(pure.score,4))\n',
                                      'pure.py': 'def score(value):return value*value+1\n'},
 'foreign_pure_nested_transport': {'main.py': 'import pure\n'
                                              'class Pipeline:\n'
                                              ' def __init__(self,callback):self.callback=callback\n'
                                              ' def run(self,value):return self.callback(value)\n'
                                              'first=pure.factory()\n'
                                              'second=pure.factory()\n'
                                              'print(Pipeline(first).run(3),second(4),[callback(5) for '
                                              'callback in [first,second]])\n',
                                   'pure.py': 'def factory():\n'
                                              ' def square(value):return value*value\n'
                                              ' return square\n'},
 'foreign_same_definition_identity': {'main.py': 'import pure\n'
                                                 'first=pure.factory()\n'
                                                 'second=pure.factory()\n'
                                                 'class Pipeline:\n'
                                                 ' def run(self,a,b):return a is b,a==b,a(3),b(4)\n'
                                                 'print(Pipeline().run(first,second),first is first)\n',
                                      'pure.py': 'def factory():\n'
                                                 ' def square(value):return value*value\n'
                                                 ' return square\n'},
 'foreign_saved_bound_reader': {'main.py': 'import pure\n'
                                           'item=pure.Gauge(7)\n'
                                           'saved=item.read\n'
                                           'item.value=12\n'
                                           'del item\n'
                                           'print(saved(),saved(7))\n',
                                'pure.py': 'class Gauge:\n'
                                           ' def __init__(self,value):self.value=value\n'
                                           ' def read(self,extra=2):return self.value+extra\n'},
 'function_metadata_defaults_observer': {'main.py': 'def square(value=3):return value*value\n'
                                                    'print(square.__defaults__==(3,))\n'
                                                    'print(square())\n'},
 'implicit_container_identity_consumers': {'main.py': 'def build():\n'
                                                      ' def square(value):return value*value\n'
                                                      ' return square\n'
                                                      'first=build()\n'
                                                      'second=build()\n'
                                                      'third=build()\n'
                                                      'callbacks=[first,second,first]\n'
                                                      'print(callbacks.count(first),callbacks.count(second),callbacks.count(third))\n'
                                                      'print(callbacks.index(second),third in callbacks)\n'},
 'live_free_cell_after_later_argument_effect': {'main.py': 'def build():\n'
                                                           ' bias=2\n'
                                                           ' def add(value):return value+bias\n'
                                                           ' def change(value):\n'
                                                           '  nonlocal bias\n'
                                                           '  bias=value\n'
                                                           "  print('changed',value)\n"
                                                           '  return 3\n'
                                                           ' return add,change\n'
                                                           'add,change=build()\n'
                                                           'print(add(change(9)),add(4))\n'},
 'nested_non_capture_multiple_instances_call_only': {'main.py': 'def build():\n'
                                                                ' def cube(value):return value*value*value\n'
                                                                ' return cube\n'
                                                                'first=build()\n'
                                                                'second=build()\n'
                                                                'callbacks=(first,second,first)\n'
                                                                'print([callback(3)for callback in '
                                                                'callbacks])\n'},
 'unused_parent_fields_shared_with_live_closure': {'main.py': 'def build():\n'
                                                              ' state=[2]\n'
                                                              ' def square(value):return value*value\n'
                                                              ' def bump(amount):\n'
                                                              '  state[0]+=amount\n'
                                                              '  return state[0]\n'
                                                              ' return square,bump\n'
                                                              'square,bump=build()\n'
                                                              'print(square(3),bump(5),square(4),bump(1))\n'}}

PROJECTS.update({'foreign_bound_starred': {'helper.py': 'class Gauge:\n'
                                        ' def __init__(self,value):self.value=value\n'
                                        ' def read(self,extra=2):return self.value+extra\n',
                           'main.py': 'import helper\n'
                                      'item=helper.Gauge(7)\n'
                                      'saved=item.read\n'
                                      'arguments=[3]\n'
                                      'print(saved(*arguments))\n'
                                      'item.value=9\n'
                                      'arguments=[]\n'
                                      'print(saved(*arguments))\n'},
 'foreign_pure_nested_starred': {'helper.py': 'def factory():\n'
                                              ' def square(value=3):return value*value\n'
                                              ' return square\n',
                                 'main.py': 'import helper\n'
                                            'selected=helper.factory()\n'
                                            'arguments=list(map(int,input().split()))\n'
                                            'print(selected(*arguments))\n'}})

PROJECTS.update({'direct_id_observer': {'main.py': 'class Counter:\n'
                                   ' def __init__(self,value):self.value=value\n'
                                   ' def score(self,callback,value):return '
                                   'callback(value)+self.value\n'
                                   'def factory():\n'
                                   ' def square(value):return value*value\n'
                                   ' return square\n'
                                   'def main():\n'
                                   ' holder=Counter(3)\n'
                                   ' callback=factory()\n'
                                   ' print(id(holder)==id(holder),holder.score(callback,4))\n'
                                   'main()\n'},
 'direct_str_address_observer': {'main.py': 'class Counter:\n'
                                            ' def __init__(self,value):self.value=value\n'
                                            ' def score(self,callback,value):return '
                                            'callback(value)+self.value\n'
                                            'def factory():\n'
                                            ' def square(value):return value*value\n'
                                            ' return square\n'
                                            'def main():\n'
                                            ' holder=Counter(3)\n'
                                            ' callback=factory()\n'
                                            ' print(str(holder).startswith("<__main__.Counter '
                                            'object at 0x"),holder.score(callback,4))\n'
                                            'main()\n'}})

def inspect(name,mode='i64'):
 models=[];original=demand.prepare
 def observe(model):
  units=getattr(model.unit,'source_units',(model.unit,));before=[ast.dump(unit.tree,include_attributes=True)for unit in units]
  original(model);models.append(model)
  assert before==[ast.dump(unit.tree,include_attributes=True)for unit in units]
 with tempfile.TemporaryDirectory(prefix='pytors-callable-demand-')as directory:
  root=Path(directory)
  for filename,source in PROJECTS[name].items():(root/filename).write_text(source)
  main=root/'main.py';options=TranspileOptions(filename=str(main),integer=mode,license='none')
  with patch.object(demand,'prepare',side_effect=observe):result=transpile(main.read_text(),options)
  with patch.object(demand,'prepare',side_effect=lambda model:setattr(model,'callable_field_demand',None)):
   baseline=transpile(main.read_text(),options)
 return result,baseline,models


def layouts(model,function):
 carrier=registry(model)
 return [(target,carrier.logical_layout(target),carrier.layout(target),demand.demand(model,target))
         for target in carrier.targets.values()if type(target)is int
         and getattr(model.callable_cells.plans[target].node,'name',None)==function]


class CallableFieldDemandProofs(unittest.TestCase):
 def test_missing_func_point_fact_uses_boolean_static_builtin_contract(self):
  from py2fastrust.references import BuiltinIdentity
  for name,builtin in [('direct_id_observer','id'),('direct_str_address_observer','str')]:
   result,baseline,models=inspect(name)
   self.assertTrue(result.success,result.diagnostics);self.assertTrue(baseline.success,baseline.diagnostics)
   self.assertEqual(result.rust_source,baseline.rust_source)
   model=models[0];proof=model.callable_field_demand
   self.assertIsNotNone(proof.barrier)
   calls=[(plan,node)for plan in proof.plans for node in model.value_classes.own_nodes(plan)
          if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id==builtin]
   self.assertTrue(calls)
   for plan,node in calls:
    self.assertNotIn((plan.index,id(node.func)),model.records)
    self.assertEqual(proof.call_identities(plan,node),{BuiltinIdentity(builtin)})
   self.assertTrue(all(logical.fields==physical.fields for _,logical,physical,_ in layouts(model,'square')))
 def test_missing_func_point_fact_does_not_turn_comprehension_shadow_into_builtin(self):
  _,_,model=self.checked('comprehension_callable_named_len');proof=model.callable_field_demand
  calls=[(plan,node)for plan in proof.plans for node in model.value_classes.own_nodes(plan)
         if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id=='len']
  self.assertTrue(calls)
  for plan,node in calls:
   with patch.object(proof,'kind',return_value=None):self.assertEqual(proof.call_identities(plan,node),set())
 def test_possible_builtin_module_member_uses_recorded_identity_not_fallback_spelling(self):
  from py2fastrust.native_aot_callables import AotFunctionType
  from py2fastrust.native_module_calls import BuiltinRef
  from py2fastrust.references import BuiltinIdentity
  _,_,models=inspect('direct_id_observer');proof=models[0].callable_field_demand
  plan,node=next((plan,node)for plan in proof.plans for node in models[0].value_classes.own_nodes(plan)
                if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id=='id')
  possible={BuiltinIdentity('len'),BuiltinRef('builtins','repr')}
  kind=AotFunctionType.from_targets(tuple(possible))
  with patch.object(proof,'kind',return_value=kind),patch('py2fastrust.native_physical_list_builtins.static_builtin')as fallback:
   self.assertEqual(proof.call_identities(plan,node),possible);fallback.assert_not_called()
  self.assertEqual(demand.builtin_names(possible),{'len','repr'})
 def test_implicit_result_observer_protocol_requires_its_own_certificate(self):
  from py2fastrust.references import BuiltinIdentity
  from py2fastrust.native_module_calls import BuiltinRef
  for identity in (BuiltinIdentity('iter'),BuiltinRef('builtins','iter')):
   self.assertTrue(demand.observes_produced_identity(ast.parse('chosen(callback,sentinel)',mode='eval').body,{identity}))
   self.assertFalse(demand.observes_produced_identity(ast.parse('chosen(values)',mode='eval').body,{identity}))
  self.assertFalse(demand.observes_produced_identity(ast.parse('chosen(callback,sentinel)',mode='eval').body,set()))
  self.assertEqual(demand.builtin_names({BuiltinRef('builtins','repr')}),{'repr'})
 def checked(self,name,mode='i64'):
  result,baseline,models=inspect(name,mode)
  self.assertTrue(result.success,result.diagnostics);self.assertTrue(baseline.success,baseline.diagnostics)
  self.assertEqual(len(models),1);self.assertIsNone(models[0].callable_field_demand.barrier)
  return result,baseline,models[0]
 def test_linked_nested_fields_disappear_in_every_integer_mode(self):
  for mode in ('i64','i128','bigint'):
   result,baseline,model=self.checked('foreign_pure_nested_transport',mode)
   rows=layouts(model,'square');self.assertTrue(rows)
   for target,logical,physical,required in rows:
    self.assertEqual(set(dict(logical.fields)),{'module','environment'})
    self.assertEqual(physical.fields,());self.assertFalse(required.module or required.environment)
    self.assertIn('struct '+payload_type(target)+'{}',result.rust_source)
   self.assertNotEqual(result.rust_source,baseline.rust_source)
 def test_bound_starred_adapter_uses_the_same_filtered_schema(self):
  result,baseline,_=self.checked('foreign_bound_starred')
  self.assertNotEqual(result.rust_source,baseline.rust_source)
  self.assertNotIn('class_selected_method.module',result.rust_source)
 def test_unproved_starred_source_retains_its_original_boundary(self):
  result,baseline,_=inspect('foreign_pure_nested_starred')
  self.assertFalse(result.success);self.assertEqual(result.diagnostics,baseline.diagnostics)
  self.assertTrue(all(item.code=='E006'and item.line>0 for item in result.diagnostics))
 def test_module_field_local_and_parameter_share_one_empty_exact_payload(self):
  _,_,model=self.checked('foreign_parameter_field_callback')
  rows=layouts(model,'score');self.assertTrue(rows)
  self.assertTrue(all('module'in dict(logical.fields)and not physical.fields for _,logical,physical,_ in rows))
 def test_unused_parent_payload_does_not_discard_a_live_sibling_environment(self):
  _,_,model=self.checked('unused_parent_fields_shared_with_live_closure')
  self.assertTrue(all(not physical.fields for _,_,physical,_ in layouts(model,'square')))
  self.assertTrue(all('environment'in dict(physical.fields)for _,_,physical,_ in layouts(model,'bump')))
 def test_same_definition_identity_and_implicit_container_consumers_keep_actual_captures(self):
  for name in ('foreign_same_definition_identity','implicit_container_identity_consumers'):
   _,_,model=self.checked(name)
   rows=layouts(model,'square');self.assertTrue(rows)
   self.assertTrue(all(logical.fields==physical.fields and required.environment for _,logical,physical,required in rows))
 def test_live_cells_and_nonliteral_default_binding_retain_source_demand(self):
  for name,function in [('live_free_cell_after_later_argument_effect','add'),('default_state_and_definition_effects','square')]:
   _,_,model=self.checked(name)
   rows=layouts(model,function);self.assertTrue(rows)
   self.assertTrue(all(required.module and required.environment for _,_,_,required in rows))
 def test_bound_receiver_remains_while_proved_private_module_disappears(self):
  result,_,model=self.checked('foreign_saved_bound_reader')
  carrier=registry(model);targets=[target for target in carrier.targets.values()if isinstance(target,BoundMethodTarget)]
  self.assertTrue(targets)
  for target in targets:
   self.assertFalse(demand.demand(model,target).module)
   self.assertEqual(set(dict(carrier.layout(target).fields)),{'bound'})
   fields=re.search(r'struct ClassBoundMethod'+str(target.definition)+r'\{([^}]*)\}',result.rust_source).group(1)
   self.assertIn('receiver:',fields);self.assertNotIn('module:',fields)
 def test_builtin_spelling_in_a_comprehension_does_not_hide_source_identity_observation(self):
  result,baseline,model=self.checked('comprehension_callable_named_len')
  self.assertTrue(all(logical.fields==physical.fields for _,logical,physical,_ in layouts(model,'square')))
  self.assertEqual(result.rust_source,baseline.rust_source)
 def test_metadata_and_finalizers_keep_original_positioned_boundaries(self):
  for name in ('function_metadata_defaults_observer','captured_state_finalizer_boundary'):
   result,baseline,_=inspect(name)
   self.assertFalse(result.success);self.assertEqual(result.diagnostics,baseline.diagnostics)
   self.assertTrue(all(item.code=='E006'and item.line>0 for item in result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class CallableFieldDemandExecution(unittest.TestCase):
 def exercise(self,name):execution.NativeLinkedModuleTests.exercise(self,PROJECTS[name])
 def test_actual_foreign_field_parameter_and_bound_receiver(self):
  for name in ('foreign_parameter_field_callback','foreign_saved_bound_reader'):
   with self.subTest(name=name):self.exercise(name)
 def test_actual_pure_nested_and_live_sibling_environment(self):
  for name in ('foreign_pure_nested_transport','unused_parent_fields_shared_with_live_closure'):
   with self.subTest(name=name):self.exercise(name)
 def test_actual_identity_observer_and_shadowed_builtin_callable(self):
  for name in ('implicit_container_identity_consumers','comprehension_callable_named_len'):
   with self.subTest(name=name):self.exercise(name)
 def test_actual_callee_snapshot_before_later_argument_rebinding(self):self.exercise('callee_snapshot_before_global_replacement')

 def test_actual_saved_bound_starred_arguments_keep_receiver_and_defaults(self):self.exercise('foreign_bound_starred')

 def test_actual_direct_observers_keep_capture_lifetime_boundaries(self):
  for name in ("direct_id_observer","direct_str_address_observer"):
   with self.subTest(name=name):self.exercise(name)
