"""Real producer bodies settle before provisional method/data indexing errors."""
import ast
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_classes import Cell,shape
from py2fastrust.native_pending_source_effects import Registry,wait_for_indexed_receiver
from py2fastrust.native_types import ListType
import test_native_class_iterators as iterator_tests


CASES={
 'direct_initializer_and_alias':'''class Cabinet:
 def shelves(self):return 1
 def __init__(self,value):self.shelves=[value]
def scenario(value):
 cabinet=Cabinet(value)
 alias=cabinet.shelves
 cabinet.shelves[0]+=4
 print(alias is cabinet.shelves,alias[0])
scenario(3)
''',
 'helper_initializer_chain':'''def finish(item,value):
 item.contents=[value]
def initialize(item,value):finish(item,value+1)
class Parcel:
 def contents(self):return 1
 def __init__(self,value):initialize(self,value)
def scenario(value):
 parcel=Parcel(value)
 parcel.contents[0]=9
 print(parcel.contents[0])
scenario(2)
''',
 'callee_installs_after_construction':'''class Record:
 def data(self):return 1
def install(record):record.data=[3]
def scenario():
 record=Record()
 install(record)
 record.data[0]+=2
 print(record.data[0])
scenario()
''',
 'callback_initializer':'''def install(record):record.data=[3]
class Record:
 def data(self):return 1
 def __init__(self,callback):callback(self)
def scenario():
 record=Record(install)
 record.data[0]+=2
 print(record.data[0])
scenario()
''',
 'closure_initializer_live_capture':'''class Record:
 def data(self):return 1
 def __init__(self,callback):callback(self)
def scenario():
 seed=3
 def install(record):record.data=[seed]
 first=Record(install)
 seed=7
 second=Record(install)
 first.data[0]+=1
 second.data[0]+=2
 print(first.data[0],second.data[0])
scenario()
''',
 'mutually_recursive_constructors':'''class First:
 def data(self):return 1
 def __init__(self,n):
  if n:Second(n-1)
  self.data=[n]
class Second:
 def data(self):return 2
 def __init__(self,n):
  if n:First(n-1)
  self.data=[n+1]
def scenario():
 first=First(3)
 first.data[0]+=7
 print(first.data[0])
scenario()
''',
 'ancestor_reads_before_later_field_assignment':'''def probe(record):
 print('probe')
 return record.data[0]
def initialize(record):
 print('initialize')
 return probe(record)
class Record:
 def data(self):return 1
 def __init__(self):
  initialize(self)
  print('later')
  self.data=[3]
print('before')
Record()
print('after')
''',
 'constructor_runtime_error_precedes_target':'''class Record:
 def data(self):return 1
 def __init__(self):
  print('constructor')
  print(1//0)
  self.data=[3]
def scenario():
 record=Record()
 print('target')
 record.data[0]=8
scenario()
''',
 'uncalled_and_proved_dead_constructors':'''class Unused:
 def data(self):return 1
 def __init__(self):self.data=[not_defined()]
def never_called():return Unused()
while False:
 Unused()
print('kept')
''',
 'callback_global_rebinding':'''class Record:
 def data(self):return 1
def numbers(record):record.data=[2]
def more_numbers(record):record.data=[7]
configure=numbers
def make():
 record=Record()
 configure(record)
 record.data[0]=record.data[0]
 return record
first=make()
configure=more_numbers
second=make()
print(first.data[0],second.data[0])
''',
}


class PendingSourceEffectProofTests(unittest.TestCase):
 def capture(self,source):
  captured=[];initialize=Registry.__init__
  def start(registry,model):
   initialize(registry,model);captured.append(registry)
  with patch.object(Registry,'__init__',start),patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
   result=transpile(source,TranspileOptions(license='none',filename='pending_case.py'))
  return result,captured

 def test_internal_models_without_official_scope_metadata_keep_existing_boundary(self):
  from py2fastrust.native_bound_methods import BoundMethodTarget
  model=SimpleNamespace(final=False,unit=None)
  receiver=Cell('function',(BoundMethodTarget(1,'Owner'),))
  self.assertIsNone(wait_for_indexed_receiver(model,None,None,receiver))
  self.assertFalse(hasattr(model,'pending_source_effects'))

 def test_real_initializer_writes_supply_the_field_type(self):
  result,registries=self.capture(CASES['direct_initializer_and_alias'])
  self.assertTrue(result.success,result.diagnostics);self.assertTrue(registries)
  registry=registries[0]
  owner=next(owner for owner in registry.model.classes.values()if owner.node.name=='Cabinet')
  self.assertTrue(owner.fields['shelves'].written)
  self.assertEqual(shape(owner.fields['shelves'].cell),ListType('int'))
  self.assertTrue(owner.methods['__init__'].reachable)
  self.assertGreater(registry.stats['waits'],0)
  self.assertGreater(registry.stats['releases'],0)
  self.assertEqual(registry.stats['full_namespace_snapshots'],0)
  original=registry.model.unit.original_unit(owner.node)
  self.assertTrue(any(node is owner.node for node in ast.walk(original.tree)))

 def test_any_ancestor_dependency_is_excluded_without_requiring_an_scc(self):
  registry=object.__new__(Registry)
  plans=[SimpleNamespace(index=index,reachable=True)for index in range(5)]
  registry.model=SimpleNamespace(call_edges={1:{2,3},2:{0}},plans=plans,
      classes={'Record':SimpleNamespace(methods={'__init__':plans[1]})})
  registry.children={};registry.parents={};registry.graph_key=None
  registry.stats={'backdependencies':0}
  # 1 -> 2 -> consumer0 is one-way. Waiting for1 or2 would deadlock.
  self.assertEqual(registry.producers(plans[0],{'Record'}),frozenset({3}))
  registry.model.call_edges[0]={4};registry.model.call_edges[4]={0}
  self.assertEqual(registry.producers(plans[0],{'Record'}),frozenset({3}))
  self.assertGreater(registry.stats['backdependencies'],0)

 def test_release_signature_observes_inputs_fields_and_lexical_cells(self):
  result,registries=self.capture(CASES['closure_initializer_live_capture'])
  self.assertTrue(result.success,result.diagnostics);registry=registries[0];model=registry.model
  producer=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='install')
  owners=frozenset(model.classes);producers=frozenset({producer.index})
  registry.graph();before=registry.signature(producers,owners)
  name=next(iter(producer.arguments));old=producer.arguments[name]
  producer.arguments[name]=Cell('str')
  self.assertNotEqual(registry.signature(producers,owners),before)
  producer.arguments[name]=old
  environment=next(environment for environment in model.lexical.environments.values()if 'seed'in environment.fields)
  old=environment.fields['seed'];environment.fields['seed']=Cell('str')
  self.assertNotEqual(registry.signature(producers,owners),before)
  environment.fields['seed']=old
  owner=next(iter(model.classes.values()));field=owner.fields['data'];old=field.cell
  field.cell=Cell('str')
  self.assertNotEqual(registry.signature(producers,owners),before)
  field.cell=old
  model.namespace.cells['unrelated_compiler_control']=Cell('str')
  self.assertEqual(registry.signature(producers,owners),before)
  self.assertEqual(registry.stats['full_namespace_snapshots'],0)

 def test_release_signature_observes_actual_namespace_and_callee_changes(self):
  result,registries=self.capture(CASES['callback_global_rebinding'])
  self.assertTrue(result.success,result.diagnostics);registry=registries[0];model=registry.model
  producer=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='make')
  owners=frozenset(model.classes);producers=frozenset({producer.index})
  registry.graph();before=registry.signature(producers,owners)
  node=next(node for node in registry.reads[producer.index]if node.id=='configure')
  name=model.resolved_name(producer,node);old=model.namespace.cells[name]
  model.namespace.cells[name]=Cell('int')
  self.assertNotEqual(registry.signature(producers,owners),before)
  model.namespace.cells[name]=old
  edges=model.call_edges[producer.index];old_edges=set(edges)
  self.assertTrue(old_edges)
  edges.remove(next(iter(old_edges)));registry.graph()
  self.assertNotEqual(registry.signature(producers,owners),before)
  model.call_edges[producer.index]=old_edges;registry.graph()
  self.assertEqual(registry.signature(producers,owners),before)

 def test_opaque_iterator_payload_change_invalidates_equal_family_kind(self):
  result,registries=self.capture(CASES['direct_initializer_and_alias'])
  self.assertTrue(result.success,result.diagnostics);registry=registries[0];model=registry.model
  producer=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='__init__')
  record=model.iterators._record(producer,producer.node,'source',identity='signature_control')
  record.source=Cell('list',(Cell('int'),));record.element=Cell('int');kind=record.kind
  name=next(iter(producer.arguments));old=producer.arguments[name]
  producer.arguments[name]=Cell('tuple',(Cell('list',(Cell(kind),)),))
  owners=frozenset(model.classes);producers=frozenset({producer.index});registry.graph()
  before=registry.signature(producers,owners)
  record.element=Cell('str')
  self.assertEqual(kind,record.kind)
  self.assertNotEqual(registry.signature(producers,owners),before)
  producer.arguments[name]=old

 def test_module_attribute_payload_is_part_of_a_producer_signature(self):
  source='''import builtins
class Record:
 def data(self):return 1
 def __init__(self):self.data=[builtins.abs(-2)]
def scenario():
 record=Record()
 record.data[0]+=1
 print(record.data[0])
scenario()
'''
  result,registries=self.capture(source)
  self.assertTrue(result.success,result.diagnostics);registry=registries[0];model=registry.model
  producer=next(plan for plan in model.plans if getattr(plan.node,'name',None)=='__init__')
  producers=frozenset({producer.index});owners=frozenset(model.classes);registry.graph()
  before=registry.signature(producers,owners)
  key=model.unit.global_name('builtins','abs');old=model.namespace.cells[key]
  model.namespace.cells[key]=Cell('int')
  self.assertNotEqual(registry.signature(producers,owners),before)
  model.namespace.cells[key]=old
  self.assertGreater(registry.stats['module_attribute_reads'],0)

 def test_true_method_only_and_unsupported_effect_producers_keep_diagnostics(self):
  cases={
   'method_only':'''class Record:
 def data(self):return 1
 def __init__(self):pass
def scenario():
 record=Record()
 record.data[0]=8
scenario()
''',
   'unknown_effect':'''def install(record):record.data=eval(input())
class Record:
 def data(self):return 1
 def __init__(self):install(self)
def scenario():
 record=Record()
 record.data[0]=8
scenario()
''',
  }
  for name,source in cases.items():
   with self.subTest(name=name):
    result,registries=self.capture(source)
    self.assertFalse(result.success);self.assertIsNone(result.rust_source)
    self.assertTrue(all(d.code=='E006'and d.line>0 for d in result.diagnostics))
    if name=='method_only':
     self.assertTrue(all('data'not in owner.fields for registry in registries for owner in registry.model.classes.values()))
    else:self.assertIn('eval',str(result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PendingSourceEffectExecutionTests(unittest.TestCase):
 cases=CASES
 check=iterator_tests.IteratorExecutionTests.check
 def test_direct_helper_and_callback_initializers(self):
  for name in ('direct_initializer_and_alias','helper_initializer_chain','callee_installs_after_construction','callback_initializer','closure_initializer_live_capture'):
   with self.subTest(name=name):self.check(name)
 def test_recursive_ancestor_dead_and_blocked_controls(self):
  for name in ('mutually_recursive_constructors','ancestor_reads_before_later_field_assignment','constructor_runtime_error_precedes_target','uncalled_and_proved_dead_constructors','callback_global_rebinding'):
   with self.subTest(name=name):self.check(name)
