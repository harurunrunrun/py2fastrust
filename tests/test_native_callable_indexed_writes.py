"""Finite callable/list stores retain Python target capture and error timing."""
import ast
import shutil
import unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_aot_callables import AotFunctionType
from py2fastrust.native_classes import InstanceType
from py2fastrust.native_finite_list_writes import supported
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_module_linking import ClassReferenceType
from py2fastrust.native_type_objects import BuiltinClass
from py2fastrust.native_types import ListType,union_type
from py2fastrust.references import BuiltinIdentity
import test_native_class_iterators as iterator_tests


CASES={
 'source_function_and_list':'''def callback():
 print('not called')
 return 1
def owner(value):
 print('owner')
 return value
def index():
 print('index')
 return 0
def rhs():
 print('rhs')
 return 9
def scenario(use_list):
 row=[2]
 target=row if use_list else callback
 owner(target)[index()]=rhs()
 print(row)
scenario(True)
scenario(False)
''',
 'bound_method_and_list':'''class Operation:
 def apply(self):
  print('not called')
  return 1
def scenario(use_list):
 row=[2]
 operation=Operation()
 target=row if use_list else operation.apply
 target[0]=9
 print(row)
scenario(True)
scenario(False)
''',
 'builtin_function_and_list':'''def scenario(use_list):
 row=[2]
 target=row if use_list else len
 target[0]=9
 print(row)
scenario(True)
scenario(False)
''',
 'module_function_and_list':'''import math
def scenario(use_list):
 row=[2]
 target=row if use_list else math.gcd
 target[0]=9
 print(row)
scenario(True)
scenario(False)
''',
 'legacy_builtin_type_and_list':'''def scenario(use_list):
 row=[2]
 target=row if use_list else int
 target[0]=9
 print(row)
scenario(True)
scenario(False)
''',
 'instance_field_shadows_method_with_missing_branch':'''class Storage:
 def add(self,value):return value+1
 def __init__(self,store):
  if store:self.add=[3]
def scenario(store):
 storage=Storage(store)
 storage.add[0]=8
 print(storage.add[0])
scenario(True)
scenario(False)
''',
 'augmented_read_error_precedes_rhs':'''def callback():return 1
def owner(value):
 print('owner')
 return value
def index():
 print('index')
 return 0
def rhs():
 print('rhs')
 return 4
def scenario(use_list):
 row=[2]
 target=row if use_list else callback
 owner(target)[index()]+=rhs()
 print(row)
scenario(True)
scenario(False)
''',
 'captured_augmented_owner_and_old_value':'''def callback():return 1
row=[2]
targets=[row,callback]
def owner():
 print('owner')
 return targets[0]
def index():
 print('index')
 targets[0]=callback
 return 0
def rhs():
 print('rhs')
 row[0]=20
 return 4
owner()[index()]+=rhs()
print(row,targets[0] is callback)
''',
 'assignment_rhs_changes_selected_owner':'''def callback():return 1
row=[2]
targets=[row,callback]
def rhs():
 print('rhs')
 targets[0]=callback
 return 8
def index():
 print('index')
 return 0
targets[0][index()]=rhs()
print(row)
''',
 'index_error_precedes_callable_assignment_error':'''def callback():return 1
def rhs():
 print('rhs')
 return 8
def index():
 print('index')
 return 1//0
row=[2]
targets=[row,callback]
target=targets[int(input())]
target[index()]=rhs()
''',
 'function_owner_error_precedes_bad_key_protocol':'''def callback():return 1
row=[2]
targets=[row,callback]
target=targets[int(input())]
def key():
 print('key')
 return len
def rhs():
 print('rhs')
 return 8
target[key()]=rhs()
''',
 'shared_nested_leaf_identity':'''def callback():return 1
leaf=[3]
row=[leaf]
targets=[row,callback]
target=targets[0]
target[0]=leaf
leaf.append(4)
print(target[0] is leaf,row[0],leaf)
''',
}


class CallableIndexedWriteProofTests(unittest.TestCase):
 def test_list_alternative_remains_required(self):
  function=AotFunctionType.from_targets((BuiltinIdentity('len'),))
  self.assertFalse(supported(function,'int'))
  self.assertTrue(supported(union_type(ListType('int'),function),'int'))
  self.assertFalse(supported(union_type(ListType('int'),ClassReferenceType(1)),'int'))
  self.assertFalse(supported(union_type(ListType('int'),BuiltinClass('type')),'int'))
  self.assertFalse(supported(union_type(ListType('int'),function),InstanceType('Index')))
  self.assertFalse(supported(union_type(ListType('int'),InstanceType('Receiver')),'int'))

 def test_source_selection_preserves_official_nodes_and_uniform_list_path(self):
  unit=build_program(CASES['source_function_and_list'],'callable_write.py').main
  before=ast.dump(unit.tree,include_attributes=True)
  for mode in ('i64','i128','bigint'):
   selection=select_frames(unit,integer=mode)
   self.assertTrue(selection.required)
  self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
  ordinary=select_frames(build_program('row=[1]\nrow[0]=2\nprint(row)\n','ordinary.py').main)
  self.assertNotIn('finite builtin indexed assignment targets',ordinary.reasons)

 def test_pure_callable_and_custom_index_keep_explicit_boundaries(self):
  cases=(
   'def callback():return 1\ncallback[0]=8\n',
   'def callback():return 1\nrow=[2]\ntargets=[row,callback]\ntarget=targets[1]\ntarget[0]=8\n',
   'class Index:\n def __index__(self):return 0\nrow=[1]\nrow[Index()]=8\n',
  )
  for source in cases:
   for mode in ('i64','i128','bigint'):
    with self.subTest(source=source,mode=mode):
     result=transpile(source,TranspileOptions(integer=mode,license='none',filename='boundary.py'))
     self.assertFalse(result.success)
     self.assertTrue(all(d.code=='E006'and d.line>0 for d in result.diagnostics))

 def test_separate_reference_contexts_remain_diagnostics(self):
  for name in ('module_function_and_list',):
   source=CASES[name]
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result=transpile(source,TranspileOptions(integer=mode,license='none',filename='reference_boundary.py'))
     self.assertFalse(result.success)
     self.assertTrue(all(d.code=='E006'and d.line>0 for d in result.diagnostics))
     self.assertIn('unresolved',str(result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class CallableIndexedWriteExecutionTests(unittest.TestCase):
 cases=CASES
 inputs={'index_error_precedes_callable_assignment_error':'1\n','function_owner_error_precedes_bad_key_protocol':'1\n'}
 check=iterator_tests.IteratorExecutionTests.check
 def test_source_bound_and_builtin_callable_arms(self):
  for name in ('source_function_and_list','bound_method_and_list','builtin_function_and_list','legacy_builtin_type_and_list','instance_field_shadows_method_with_missing_branch'):
   with self.subTest(name=name):self.check(name)
 def test_evaluation_order_capture_and_aliases(self):
  for name in ('augmented_read_error_precedes_rhs','captured_augmented_owner_and_old_value','assignment_rhs_changes_selected_owner','index_error_precedes_callable_assignment_error','function_owner_error_precedes_bad_key_protocol','shared_nested_leaf_identity'):
   with self.subTest(name=name):self.check(name)
