"""Readonly primitive parameters preserve binding semantics without Option slots."""
import ast,re,shutil,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Emitter,shape,InstanceType
from py2fastrust import native_primitive_parameter_places as places
from tests import test_native_module_linking as execution

PROJECTS={'capture_closure_and_nonlocal': {'main.py': 'class Calculator:\n'
                                             ' def calculate(self,value):\n'
                                             '  def change():\n'
                                             '   nonlocal value\n'
                                             '   value+=3\n'
                                             '   return value\n'
                                             '  return change(),value\n'
                                             'print(Calculator().calculate(4))\n'},
 'capture_generator': {'main.py': 'class Calculator:\n'
                                  ' def calculate(self,value):return sum(value+index for index in range(3))\n'
                                  'print(Calculator().calculate(4))\n'},
 'capture_returned_closure': {'main.py': 'class Calculator:\n'
                                         ' def calculate(self,value):\n'
                                         '  def read(extra):return value+extra\n'
                                         '  return read\n'
                                         'callback=Calculator().calculate(4)\n'
                                         'print(callback(7))\n'},
 'copy_argument_effects_and_definition_defaults': {'main.py': 'def seed():\n'
                                                              ' print("default")\n'
                                                              ' return 3\n'
                                                              'def argument(value):\n'
                                                              ' print("argument",value)\n'
                                                              ' return value\n'
                                                              'class Calculator:\n'
                                                              ' def calculate(self,count=seed(),*,scale=2):return '
                                                              'count*scale\n'
                                                              'c=Calculator()\n'
                                                              'print(c.calculate(scale=argument(4),count=argument(5)),c.calculate())\n'},
 'copy_foreign_module_method': {'helper.py': 'class Calculator:\n def calculate(self,count):return count*count\n',
                                'main.py': 'import helper\nprint(helper.Calculator().calculate(11))\n'},
 'copy_free_inline_comprehension': {'main.py': 'class Calculator:\n'
                                               ' def calculate(self,count):return [count+index for index in '
                                               'range(count)],count\n'
                                               'print(Calculator().calculate(3))\n'},
 'copy_global_only_rename': {'main.py': 'value=100\n'
                                        'class Calculator:\n'
                                        ' def calculate(self,value):return value+1\n'
                                        'print(Calculator().calculate(7),value)\n'},
 'copy_lambda_parameter': {'main.py': 'class Pipeline:\n'
                                      ' def __init__(self,callback):self.callback=callback\n'
                                      ' def run(self,value):return self.callback(value)\n'
                                      'callback=lambda value:value*value\n'
                                      'print(Pipeline(callback).run(9))\n'},
 'copy_method_defaults_keywords': {'main.py': 'class Weighted:\n'
                                              ' def __init__(self,bias):self.bias=bias\n'
                                              ' def evaluate(self,count,enabled=True,weight=1.5,marker=None):\n'
                                              '  total=0\n'
                                              '  for index in range(count):total+=index+self.bias\n'
                                              '  return total if enabled else 0,weight*2,marker is None\n'
                                              'w=Weighted(3)\n'
                                              'print(w.evaluate(4),w.evaluate(count=2,enabled=False,weight=2.25))\n'},
 'copy_owning_comprehension_shadow': {'main.py': 'class Calculator:\n'
                                                 ' def calculate(self,count):return [count+1 for count in '
                                                 'range(count)],count\n'
                                                 'print(Calculator().calculate(4),Calculator().calculate(0))\n'},
 'copy_parameter_private_name': {'main.py': 'class Calculator:\n'
                                            ' def calculate(self,__value):return __value+3\n'
                                            'print(Calculator().calculate(7))\n'},
 'copy_repeated_calls_and_error': {'main.py': 'class Calculator:\n'
                                              ' def calculate(self,value):return 30//value\n'
                                              'c=Calculator()\n'
                                              'print(c.calculate(3))\n'
                                              'print(c.calculate(0))\n'},
 'copy_same_callsite_exact_contexts': {'main.py': 'class Calculator:\n'
                                                  ' def calculate(self,value):return value,value+1\n'
                                                  'def apply(calculator,value):return '
                                                  'calculator.calculate(value)\n'
                                                  'c=Calculator()\n'
                                                  'print(apply(c,7),apply(c,True),apply(c,2.5))\n'},
 'definition_parameter_shadow': {'main.py': 'class Calculator:\n'
                                            ' def calculate(self,value):\n'
                                            '  def value():return 7\n'
                                            '  return value()\n'
                                            'print(Calculator().calculate(3))\n'},
 'match_mapping_rest': {'main.py': 'class Calculator:\n'
                                   ' def calculate(self,value):\n'
                                   '  match {"first":7,"second":8}:\n'
                                   '   case {"first":first,**value}:return first+value["second"]\n'
                                   'print(Calculator().calculate(3))\n'},
 'mutation_annotation_only': {'main.py': 'class Calculator:\n'
                                         ' def calculate(self,value):\n'
                                         '  value:int\n'
                                         '  return value+1\n'
                                         'print(Calculator().calculate(8))\n'},
 'mutation_assign_and_augmented': {'main.py': 'class Calculator:\n'
                                              ' def calculate(self,value):\n'
                                              '  value+=3\n'
                                              '  value=value*2\n'
                                              '  return value\n'
                                              'print(Calculator().calculate(4))\n'},
 'mutation_comprehension_walrus': {'main.py': 'class Calculator:\n'
                                              ' def calculate(self,value):return [(value:=value+index) for index '
                                              'in range(3)],value\n'
                                              'print(Calculator().calculate(4))\n'},
 'mutation_delete_before_later_effect': {'main.py': 'def later():\n'
                                                    ' print("later")\n'
                                                    ' return 3\n'
                                                    'class Calculator:\n'
                                                    ' def calculate(self,value):\n'
                                                    '  del value\n'
                                                    '  return value+later()\n'
                                                    'Calculator().calculate(9)\n'},
 'mutation_except_target': {'main.py': 'class Calculator:\n'
                                       ' def calculate(self,value):\n'
                                       '  try:raise ValueError("changed")\n'
                                       '  except ValueError as value:print(type(value).__name__)\n'
                                       '  return value\n'
                                       'Calculator().calculate(3)\n'},
 'mutation_for_target': {'main.py': 'class Calculator:\n'
                                    ' def calculate(self,value):\n'
                                    '  for value in range(2):pass\n'
                                    '  return value\n'
                                    'print(Calculator().calculate(9))\n'},
 'mutation_hidden_zero_trip': {'main.py': 'class Calculator:\n'
                                          ' def calculate(self,value):\n'
                                          '  for index in range(0):value=index\n'
                                          '  return value+1\n'
                                          'print(Calculator().calculate(8))\n'},
 'mutation_import_target': {'main.py': 'class Calculator:\n'
                                       ' def calculate(self,value):\n'
                                       '  import math as value\n'
                                       '  return value.isqrt(49)\n'
                                       'print(Calculator().calculate(3))\n'},
 'mutation_walrus': {'main.py': 'class Calculator:\n'
                                ' def calculate(self,value):return (value:=value+3),value\n'
                                'print(Calculator().calculate(4))\n'},
 'mutation_with_target': {'main.py': 'class Context:\n'
                                     ' def __enter__(self):return 7\n'
                                     ' def __exit__(self,kind,error,trace):return False\n'
                                     'class Calculator:\n'
                                     ' def calculate(self,value):\n'
                                     '  with Context() as value:print(value)\n'
                                     '  return value\n'
                                     'print(Calculator().calculate(3))\n'},
 'namespace_globals': {'main.py': 'token=5\n'
                                  'class Calculator:\n'
                                  ' def calculate(self,value):return value+1,"token"in globals()\n'
                                  'print(Calculator().calculate(9))\n'},
 'noncopy_list_alias': {'main.py': 'class Calculator:\n'
                                   ' def calculate(self,values):\n'
                                   '  values.append(3)\n'
                                   '  return values[0],len(values)\n'
                                   'values=[8]\n'
                                   'print(Calculator().calculate(values),values)\n'},
 'observer_frame': {'main.py': 'import sys\n'
                               'class Calculator:\n'
                               ' def calculate(self,value):return sys._getframe().f_locals["value"]\n'
                               'print(Calculator().calculate(9))\n'},
 'observer_locals': {'main.py': 'class Calculator:\n'
                                ' def calculate(self,value):return locals()["value"]\n'
                                'print(Calculator().calculate(9))\n'},
 'suspended_recursive': {'main.py': 'class Calculator:\n'
                                    ' def calculate(self,value):\n'
                                    '  if value<2:return 1\n'
                                    '  return value*self.calculate(value-1)\n'
                                    'print(Calculator().calculate(5))\n'}}

def inspect(name,mode='i64'):
 observed=[];original=Emitter.generate
 def generate(emitter):
  units=getattr(emitter.model.unit,'source_units',(emitter.model.unit,));before=[ast.dump(unit.tree,include_attributes=True)for unit in units]
  code=original(emitter);assert before==[ast.dump(unit.tree,include_attributes=True)for unit in units]
  observed.append((emitter,code))
  return code
 with tempfile.TemporaryDirectory(prefix='pytors-primitive-parameter-')as directory:
  root=Path(directory)
  for filename,source in PROJECTS[name].items():(root/filename).write_text(source)
  main=root/'main.py';options=TranspileOptions(filename=str(main),integer=mode,license='none')
  with patch.object(Emitter,'generate',generate):result=transpile(main.read_text(),options)
  with patch.object(places,'prepare',return_value={}):baseline=transpile(main.read_text(),options)
 return result,baseline,observed


def named(observed,name):return[(emitter,code)for emitter,code in observed if getattr(emitter.plan.node,'name',None)==name]


class PrimitiveParameterProofs(unittest.TestCase):
 def test_incomplete_internal_model_has_no_parameter_certificate(self):
  unit=parse_source(PROJECTS['copy_method_defaults_keywords']['main.py'],'parameter_partial.py')
  node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.FunctionDef)and node.name=='evaluate')
  emitter=SimpleNamespace(model=SimpleNamespace(unit=unit),plan=SimpleNamespace(node=node,reachable=True))
  self.assertEqual(places.prepare(emitter),{})
 def checked(self,name,mode='i64'):
  result,baseline,observed=inspect(name,mode)
  self.assertTrue(result.success,result.diagnostics);self.assertTrue(baseline.success,baseline.diagnostics)
  return result,baseline,observed
 def assert_no_slot(self,emitter,code,name):
  parameter=emitter.primitive_parameters[name]
  for (other,kind),slot in emitter.slots.items():
   if other==name and kind==parameter.kind:
    self.assertNotIn('let mut '+slot+':',code);self.assertNotIn(slot+'=Some(',code)
  for node in emitter.model.value_classes.own_nodes(emitter.plan):
   if not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load):continue
   binding=emitter.model.lexical.binding(node)
   if binding is not None and binding.owner==parameter.scope and binding.name==name:
    self.assertEqual(places.read(emitter,node).code,parameter.code)
 def test_exact_copy_parameters_use_actual_argument_and_no_slot_all_modes(self):
  for mode in ('i64','i128','bigint'):
   result,baseline,observed=self.checked('copy_method_defaults_keywords',mode)
   methods=named(observed,'evaluate');self.assertTrue(methods)
   for emitter,code in methods:
    expected={'enabled','weight','marker'}|({'count'}if mode!='bigint'else set())
    self.assertEqual(set(emitter.primitive_parameters),expected)
    for name in expected:self.assert_no_slot(emitter,code,name)
   self.assertNotEqual(result.rust_source,baseline.rust_source)
 def test_inline_comprehension_owners_do_not_overwrite_parameter(self):
  for project in ('copy_owning_comprehension_shadow','copy_free_inline_comprehension'):
   _,_,observed=self.checked(project)
   for emitter,code in named(observed,'calculate'):
    self.assertIn('count',emitter.primitive_parameters);self.assert_no_slot(emitter,code,'count')
 def test_all_original_producers_and_captures_keep_the_existing_place(self):
  for project in ('mutation_assign_and_augmented','mutation_walrus','mutation_comprehension_walrus','mutation_for_target','mutation_delete_before_later_effect','mutation_hidden_zero_trip','mutation_annotation_only','mutation_with_target','mutation_import_target','capture_closure_and_nonlocal','capture_returned_closure','capture_generator','noncopy_list_alias','suspended_recursive'):
   with self.subTest(project=project):
    _,_,observed=self.checked(project)
    self.assertTrue(named(observed,'calculate'))
    for emitter,_ in named(observed,'calculate'):
     self.assertNotIn('value',emitter.primitive_parameters);self.assertNotIn('values',emitter.primitive_parameters)
 def test_official_scope_rows_and_symbol_assignment_seal_cover_non_name_producers(self):
  negatives=('mutation_assign_and_augmented','mutation_walrus','mutation_comprehension_walrus','mutation_for_target','mutation_delete_before_later_effect','mutation_hidden_zero_trip','mutation_annotation_only','mutation_with_target','mutation_import_target','mutation_except_target','definition_parameter_shadow','match_mapping_rest')
  for project in negatives:
   unit=parse_source(PROJECTS[project]['main.py'],'parameter_producers.py')
   node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.FunctionDef)and node.name=='calculate');scope=unit.scope_for(node).ordinal
   self.assertFalse(places.readonly_parameter(unit,unit.bindings,scope,'value'),project)
  unit=parse_source(PROJECTS['copy_owning_comprehension_shadow']['main.py'],'parameter_comp.py')
  node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.FunctionDef)and node.name=='calculate');scope=unit.scope_for(node).ordinal
  self.assertTrue(places.readonly_parameter(unit,unit.bindings,scope,'count'))
 def test_private_parameter_names_and_foreign_methods_keep_official_owner(self):
  for project in ('copy_parameter_private_name','copy_foreign_module_method'):
   _,_,observed=self.checked(project)
   methods=named(observed,'calculate');self.assertTrue(methods)
   self.assertTrue(all(emitter.primitive_parameters for emitter,_ in methods))
   for emitter,code in methods:
    for name in emitter.primitive_parameters:self.assert_no_slot(emitter,code,name)
 def test_namespace_and_unsupported_frame_observers_remain_conservative(self):
  result,baseline,observed=self.checked('namespace_globals')
  self.assertEqual(result.rust_source,baseline.rust_source)
  self.assertTrue(all(not emitter.primitive_parameters for emitter,_ in observed))
  for project in ('mutation_except_target','observer_locals','observer_frame','match_mapping_rest','definition_parameter_shadow'):
   result,baseline,_=inspect(project)
   self.assertFalse(result.success);self.assertEqual(result.diagnostics,baseline.diagnostics)
   self.assertTrue(all(item.code=='E006'and item.line>0 for item in result.diagnostics))
 def test_noncopy_unions_and_bigint_int_are_not_plain_copy_parameters(self):
  from py2fastrust.native_types import ListType,TupleType,NullableType,union_type
  for mode in ('i64','i128','bigint'):
   model=SimpleNamespace(integer=mode)
   for kind in ('bool','float','none'):self.assertTrue(places.copy_kind(model,kind))
   self.assertEqual(places.copy_kind(model,'int'),mode!='bigint')
   for kind in ('int_bool','str','bytes',None,ListType('int'),TupleType(('int',)),NullableType('int'),union_type('int','float'),InstanceType('C')):
    self.assertFalse(places.copy_kind(model,kind),(mode,kind))
 def test_lambda_body_parameters_use_the_same_readonly_place(self):
  _,_,observed=self.checked('copy_lambda_parameter')
  rows=[(emitter,code)for emitter,code in observed if isinstance(emitter.plan.node,ast.Lambda)]
  self.assertTrue(rows)
  self.assertTrue(any('value'in emitter.primitive_parameters for emitter,_ in rows))
  for emitter,code in rows:
   if 'value'in emitter.primitive_parameters:self.assert_no_slot(emitter,code,'value')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PrimitiveParameterExecution(unittest.TestCase):
 def exercise(self,name):execution.NativeLinkedModuleTests.exercise(self,PROJECTS[name])
 def test_actual_copy_primitives_and_default_argument_effects(self):
  for project in ('copy_method_defaults_keywords','copy_argument_effects_and_definition_defaults'):
   with self.subTest(project=project):self.exercise(project)
 def test_actual_inline_comprehension_and_mutating_walrus_owners(self):
  for project in ('copy_owning_comprehension_shadow','copy_free_inline_comprehension','mutation_comprehension_walrus'):
   with self.subTest(project=project):self.exercise(project)
 def test_actual_deletion_error_and_live_captured_cells(self):
  for project in ('mutation_delete_before_later_effect','capture_closure_and_nonlocal'):
   with self.subTest(project=project):self.exercise(project)
 def test_actual_nonsuspended_and_namespace_boundaries(self):
  for project in ('suspended_recursive','namespace_globals'):
   with self.subTest(project=project):self.exercise(project)
