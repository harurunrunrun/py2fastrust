"""Class-body callable reads preserve actual preceding source publication."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests
import test_native_module_linking as linked_tests

CASES={
'direct_builtin_named_source_functions':'''def type(value):return value+7
def object(value):return value+11
def bytearray(value):return value+13
def property(value):return value+17
class Box:
 first=type(3)
 second=object(3)
 third=bytearray(3)
 fourth=property(3)
print(Box.first,Box.second,Box.third,Box.fourth)
''',
'published_alias':'''def helper(value):return value+7
type=helper
class Box:value=type(3)
print(Box.value+1)
''',
'before_and_after_definition':'''class Before:value=len([1,2])
def len(value):return 9
class After:value=len([0])
print(Before.value,After.value)
''',
'after_class_rebinding':'''def len(value):return 9
class Before:value=len([1,2])
def later(value):return 13
len=later
class After:value=len([0])
print(Before.value,After.value)
''',
'competing_source_writer':'''def len(value):return 9
def later(value):return 13
len=later
class Box:value=len([1,2])
print(Box.value)
''',
'dormant_function_writer':'''def object(value):return value+7
def unused():
 global object
 object=lambda value:value*9
class Box:value=object(3)
print(Box.value)
''',
'captured_defaults_and_function_identity':'''state=[]
def type(value,values=state):
 values.append(value)
 return len(values)
saved=type
class Box:
 first=type(3)
 second=type(4)
state=[]
print(Box.first,Box.second,type(5),saved is type,state)
''',
'callee_captured_before_argument_writer':'''def len(value):return 9
def other(value):return 13
def mutate():
 global len
 len=other
 print('mutate')
 return [1,2]
class Box:value=len(mutate())
print(Box.value,len([0]))
''',
'class_local_shadow':'''def len(value):return 9
class Box:
 len=23
 value=len
print(Box.value,len([0]))
''',
'actual_builtins_without_source_shadow':'''class Box:value=len([1,2])
print(Box.value)
''',
}
CASES.update({
'successive_reads_with_dormant_writer':'''def object(value):return value+7
def unused():
 global object
 object=lambda value:value*9
class Box:
 first=object(3)
 second=object(4)
print(Box.first,Box.second)
''',
'class_body_live_rebinding':'''def object(value):return value+7
def mutate():
 global object
 object=lambda value:value*9
 print('mutate')
 return 0
class Box:
 first=object(3)
 event=mutate()
 second=object(4)
print(Box.first,Box.second)
''',
'alias_successive_reads':'''def callback(value):return value+7
type=callback
class Box:
 first=type(3)
 second=type(4)
print(Box.first,Box.second)
''',
'actual_builtin_payload_assignment':'''builtin_len=len
def len(value):return 9
len=builtin_len
class Box:value=len([1,2])
print(Box.value)
''',
'explicit_delete_restores_builtin_fallback':'''def len(value):return 9
del len
class Box:value=len([1,2])
print(Box.value)
''',

})
for name in ('type','object','bytearray','property'):
 CASES['alias_'+name]='def callback(value):return value+7\n'+name+'=callback\nclass Box:value='+name+'(3)\nprint(Box.value)\n'

CASES['successive_reads_with_dormant_delete']='''def object(value):return value+7
def unused():
 global object
 del object
class Box:
 first=object(3)
 second=object(4)
print(Box.first,Box.second)
'''
CASES['nested_class_module_function']='''def object(value):return value+7
class Outer:
 class Inner:value=object(3)
print(Outer.Inner.value)
'''

CASES['lambda_alias_actual_default']='''data=[7]
type=lambda value,items=data:value+items[0]
class Box:value=type(3)
data=[100]
print(Box.value,type(4),type is type)
'''
CASES['returned_closure_aliases_actual_instances']='''def make(offset):
 values=[]
 def step(value,items=values):
  items.append(value)
  return offset+len(items)
 return step
type=make(10)
object=make(20)
class Box:
 first=type(7)
 second=object(8)
 third=type(9)
print(Box.first,Box.second,Box.third,type is object)
'''

CASES['bound_method_alias_captured_receiver']='''class Helper:
 def __init__(self,offset):self.offset=offset
 def step(self,value):return value+self.offset
helper=Helper(7)
type=helper.step
class Box:value=type(3)
helper=Helper(100)
print(Box.value+1,type(4))
'''
CASES['builtin_callable_alias_actual_payload']='''type=len
class Box:value=type([1,2,3])
print(Box.value+1)
'''
CASES['module_callable_alias_actual_payload']='''from math import gcd
type=gcd
class Box:value=type(12,18)
print(Box.value+1)
'''

CASES['returned_closure_pending_producer']='''def factory(delta):
 def build(value):return delta+value
 return build
type=factory(7)
class Box:result=type(3)
print(Box.result+1)
'''

CASES['pending_noncallable_producer_preserves_argument_effects']='''def make():print('make');return 11
type=make()
def argument():print('argument');return 5
class Box:value=type(argument())
'''
CASES['actual_none_callable_argument_failure_first']='''def make():print('make');return None
object=make()
def argument():print('argument');return 1//0
class Box:value=object(argument())
'''
CASES['finite_callable_aliases_keep_actual_target']='''def first(value):return value+7
def second(value):return value+20
def choose(flag):
 if flag:return first
 return second
type=choose(False)
class Box:value=type(3)
print(Box.value+1)
'''
CASES['finite_none_callable_aliases_keep_actual_none']='''def first(value):return value+7
def choose(flag):
 if flag:return first
 return None
type=choose(False)
def argument():print('argument');return 5
class Box:value=type(argument())
'''

class FunctionPublicationExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_original_module_publication(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)
for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(FunctionPublicationExecutionTests,_name,None)

class FunctionPublicationModuleTests(unittest.TestCase):
 exercise=linked_tests.NativeLinkedModuleTests.exercise
 def test_independent_original_modules(self):
  self.exercise({
   'main.py':'import left\nimport right\nprint(left.Box.value,right.Box.value,left.saved is left.type)\n',
   'left.py':'state=[]\ndef type(value,items=state):\n items.append(value)\n return len(items)\nsaved=type\nclass Box:value=type(3)\n',
   'right.py':'def type(value):return value+20\nclass Box:value=type(3)\n'})

class FunctionPublicationBoundaries(unittest.TestCase):
 def test_decorated_source_publication_keeps_explicit_boundary(self):
  result=transpile('def decorate(function):return function\n@decorate\ndef type(value):return value+7\nclass Box:value=type(3)\nprint(Box.value)\n',TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertTrue(any('decorat'in diagnostic.message.lower()for diagnostic in result.diagnostics),result.diagnostics)

class FunctionPublicationProofTests(unittest.TestCase):
 def model(self,source,others=None):
  import tempfile
  from pathlib import Path
  from types import SimpleNamespace
  from py2fastrust.frontend import build_program
  from py2fastrust.native_module_linking import LinkedProgram
  temporary=tempfile.TemporaryDirectory(prefix='pytors-publication-proof-')
  self.addCleanup(temporary.cleanup)
  root=Path(temporary.name)
  for name,contents in (others or{}).items():(root/name).write_text(contents)
  program=build_program(source,str(root/'main.py'),(root,))
  unit=LinkedProgram.from_program(program).unit
  return SimpleNamespace(unit=unit,namespace=SimpleNamespace(owners={row.node:row for row in unit.bindings},globals_observed=False),
                         iter_nodes=unit.iter_nodes,module_owner=lambda scope:unit.scopes[scope].kind=='module')
 def test_actual_exception_alias_is_an_implicit_unbinding(self):
  from py2fastrust.native_class_body_function_reads import _is_unbinding
  source='def len(value):return 9\ntry:raise ValueError()\nexcept ValueError as len:pass\nclass Box:value=len([1,2])\n'
  model=self.model(source)
  nodes={model.unit.ordinal(node):node for node in model.iter_nodes()}
  cleanup=[row for row in model.unit.bindings if row.role=='store'and row.name.endswith(':len')]
  self.assertEqual(len(cleanup),1)
  self.assertTrue(_is_unbinding(cleanup[0],nodes))
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertTrue(any('exception-handler routing'in diagnostic.message for diagnostic in result.diagnostics),result.diagnostics)
 def test_unreferenced_function_proof_and_all_reference_barriers(self):
  import ast
  from py2fastrust.native_class_body_function_reads import _unbinding_can_execute,_effects_closed
  from types import SimpleNamespace
  library='def object(value):return value+7\ndef unused():\n global object\n del object\n'
  for name,source,others,expected in (
   ('unreferenced',library,None,False),
   ('callback_reference',library+'callbacks=[unused]\n',None,True),
   ('decorator_reference',library+'@unused\ndef registered():pass\n',None,True),
   ('annotation_reference',library+'def registered(value:unused):pass\n',None,True),
   ('module_member','import helper\ncallback=helper.unused\n',{'helper.py':library},True),
   ('import_alias','from helper import unused as callback\n',{'helper.py':library},True),
   ('star_import','from helper import *\n',{'helper.py':library},True),
   ('module_protocol',library.replace('unused','__dir__'),None,True)):
   with self.subTest(name=name):
    model=self.model(source,others)
    deletes=[row for row in model.unit.bindings if row.role=='delete']
    self.assertEqual(len(deletes),1)
    self.assertEqual(_unbinding_can_execute(model,deletes[0]),expected)
  for expression in ('globals()["unused"]','getattr(module,"unused")','module.__dict__["unused"]','module.__getattribute__("unused")'):
   with self.subTest(expression=expression):
    model=self.model(library+'callback='+expression+'\n')
    self.assertFalse(_effects_closed(model,SimpleNamespace(spelling=lambda name:'object'),'object'))
