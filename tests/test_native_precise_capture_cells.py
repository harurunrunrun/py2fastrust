"""Exact strong lexical cells preserve escaping lambda capture semantics."""
import unittest
from unittest.mock import patch
import ast
import test_native_annotations_assertions as assertion_tests
from py2fastrust import TranspileOptions,transpile

CASES={'minimal_assignment_shape': ('def make(A):\n pi=[1,2]\n residual=lambda i,j:A[i][j]-pi[j]\n def read():return residual(0,1)\n return read(),residual\nvalue,callback=make([[5,9],[7,11]])\nprint(value,callback(1,0))\n', ('',)), 'escaping_live_rebindings': ('def make(values):\n callback=lambda index:values[index]\n def read():return callback(0)\n def replace(other):\n  nonlocal values\n  values=other\n return callback,read,replace\ncallback,read,replace=make([5,7])\nsaved=callback\nprint(callback(1),read(),callback is saved)\nreplace([11,13])\nprint(callback(1),read(),callback is saved)\nread=None\nreplace=None\nprint(saved(0))\n', ('',)), 'sibling_lambda_cells': ('def make(value):\n first=lambda:value+1\n second=lambda:value+2\n def total():return first()+second()\n def update(other):\n  nonlocal value\n  value=other\n return first,second,total,update\nfirst,second,total,update=make(3)\nsaved=first\nprint(first(),second(),total(),first is second,first is saved)\nupdate(9)\nprint(first(),second(),total(),first is saved)\n', ('',)), 'transitive_grandparent_cells': ('def outer(start):\n values=[start]\n def middle():\n  extra=[1]\n  callback=lambda:values[0]+extra[0]\n  def read():return callback()\n  return callback,read,extra\n return middle,values\nfactory,values=outer(3)\nfirst,read_first,extra_first=factory()\nsecond,read_second,extra_second=factory()\nprint(first(),second(),read_first(),read_second())\nvalues[0]=10\nextra_first[0]=7\nfactory=None\nprint(first(),second(),read_first(),read_second(),extra_first is extra_second)\n', ('',)), 'default_snapshot_and_live_rebind': ('def make(values):\n callback=lambda step=1,saved=values:saved[0]+values[0]+step\n def read():return callback()\n def replace(other):\n  nonlocal values\n  values=other\n return callback,read,replace\noriginal=[3]\ncallback,read,replace=make(original)\nprint(callback(),read())\nreplace([9])\noriginal[0]=5\nprint(callback(2),read())\n', ('',)), 'unbound_and_deleted_shared_cell': ('def make(enabled):\n if enabled:value=[5]\n callback=lambda:value[0]\n def read():return callback()\n def erase():\n  nonlocal value\n  del value\n return callback,read,erase\ncallback,read,erase=make(int(input()))\nprint(read())\nerase()\nprint(callback())\n', ('0\n', '1\n')), 'mutated_captured_list': ('def make(items):\n callback=lambda value:(items.append(value),len(items))[1]\n def read(value):return callback(value)\n return callback,read\nitems=[2]\ncallback,read=make(items)\nprint(callback(3),read(5),items)\nitems.append(7)\nprint(callback(11),items)\n', ('',)), 'legacy_lambda_shares_promoted_environment': ('def make(value):\n data=[value]\n first=lambda:data[0]\n second=lambda:first\n def read():return first()\n return first,second,read\nfirst,second,read=make(7)\nprint(second() is first,read(),second()())\n', ('',)), 'callback_parameter_writes_shared_cell': ('def make():\n value=3\n def update():\n  nonlocal value\n  value=9\n  return 1\n callback=lambda operation:value+operation()\n def read():return callback(update)\n return callback,read,update\ncallback,read,update=make()\nprint(callback(update),read())\n', ('',))}
BOUNDARIES={'real_self_callable_cycle': 'def make():\n callback=lambda:callback\n def read():return callback\n return callback,read\ncallback,read=make()\nprint(callback() is callback,read() is callback)\n', 'real_callable_list_cycle': 'def make():\n values=[]\n callback=lambda:values[0]\n def read():return callback()\n values.append(callback)\n return callback,read\ncallback,read=make()\nprint(callback() is callback,read() is callback)\n', 'function_binding_capture_needs_its_own_instance_view': 'def make():\n value=3\n def update():\n  nonlocal value\n  value=9\n  return 1\n callback=lambda:value+update()\n def read():return callback()\n return callback,read\ncallback,read=make()\nprint(callback(),read())\n'}

class PreciseCaptureExecutionTests(unittest.TestCase):
 compare=assertion_tests.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
for _name in CASES:setattr(PreciseCaptureExecutionTests,'test_'+_name,_case(_name))

class PreciseCaptureBoundaryTests(unittest.TestCase):
 def test_genuine_callable_cycles_still_need_collection(self):
  for name,source in BOUNDARIES.items():
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename='capture.py'))
    self.assertFalse(result.success,(name,integer))
    self.assertTrue(any(d.code=='E006'and 'cycl'in d.message for d in result.diagnostics),(name,result.diagnostics))

GENERATOR_BOUNDARIES={'generator_yields_captured_lambda': 'def produce():\n value=3\n yield lambda:value\n value=9\n yield lambda:value\niterator=produce()\nfirst=next(iterator)\nprint(first())\nsecond=next(iterator)\nprint(first(),second(),first is second)\n', 'lambda_yield_body': 'def make(value):\n callback=lambda:(yield value)\n def read():return callback\n return callback,read\ncallback,read=make(5)\nprint(next(callback()),next(read()()))\n', 'lambda_yield_from_body': 'def make(value):\n callback=lambda:(yield from [value])\n def read():return callback\n return callback,read\ncallback,read=make(5)\nprint(next(callback()),next(read()()))\n', 'generator_immediate_captured_lambda': 'def produce():\n value=3\n print((lambda:value)())\n yield value\nprint(list(produce()))\n'}

class PreciseCaptureSuspensionTests(unittest.TestCase):
 def test_yielding_lambda_and_source_generator_layouts_are_positioned_boundaries(self):
  for name,source in GENERATOR_BOUNDARIES.items():
   if name=='generator_immediate_captured_lambda':continue
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename='capture_generator.py'))
    self.assertFalse(result.success,(name,integer))
    self.assertTrue(any(d.code=='E006'and d.line>0 for d in result.diagnostics),(name,result.diagnostics))
 def test_source_generator_parent_never_receives_an_ordinary_capture_view(self):
  from py2fastrust.frontend import build_program
  from py2fastrust.native_classes import Model
  source=GENERATOR_BOUNDARIES['generator_immediate_captured_lambda']
  for integer in ('i64','i128','bigint'):
   unit=build_program(source,'capture_generator.py').main
   model=Model(unit.tree,unit.filename,integer,unit.native_imports,unit=unit).run()
   self.assertTrue(model.lambda_cells.active)
   for definition in model.lambda_cells.active:
    plan=model.lambda_cells.plans[definition]
    parent=model.lexical.environments[model.lexical.parent_scope(plan)].plan
    self.assertIsNotNone(getattr(parent,'source_generator',None))
    self.assertNotIn(definition,model.lexical_capture_views)
   self.assertFalse(model.lexical_shared_capture_cells)

class PreciseCaptureOwnershipTests(unittest.TestCase):
 def test_lifetime_edges_match_the_actual_strong_free_cell_layout(self):
  from py2fastrust.frontend import build_program
  from py2fastrust.native_classes import Model
  import py2fastrust.native_class_gc as gc
  source=CASES['minimal_assignment_shape'][0]
  unit=build_program(source,'capture.py').main
  captured=[];original=gc.lexical_projection
  def observe(model,edges):
   captured.append({key:set(value)for key,value in edges.items()})
   return original(model,edges)
  with patch.object(gc,'lexical_projection',observe):
   model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  definition=next(iter(model.lambda_cells.active));plan=model.lambda_cells.plans[definition]
  scope=model.lexical.scope(plan)
  free={symbol.name for symbol in unit.scope_for(plan.node).symbols if symbol.has('free')}
  expected={(row.owner,row.name)for row in unit.bindings if row.scope==scope and row.role=='load'and row.name in free}
  view=model.lexical_capture_views[definition]
  self.assertEqual(set(view.cells),expected)
  edges=captured[-1]
  self.assertEqual(edges['lambda',definition],{('lexical_cell',owner,name)for owner,name in expected})
  self.assertIn(('lambda',definition),edges['environment',model.lexical.parent_scope(plan)])
  for owner,name in expected:
   self.assertEqual(edges['lexical_cell',owner,name],set())
  emitter=model.emitter(model.module)
  runtime=model.lambda_cells.runtime(emitter)
  self.assertIn('struct '+view.rust+'{',runtime)
  self.assertIn('environment:'+view.rust,runtime)
  self.assertNotIn('Weak',runtime)
  self.assertNotIn('environment:std::rc::Rc<ClassLexicalEnvironment',runtime)

if __name__=='__main__':unittest.main()
