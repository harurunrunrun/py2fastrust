"""Source generator frames own actual lexical cells across suspension."""
import unittest
import test_native_annotations_assertions as assertion_tests

CASES={'original_immediate_lambda': ('def produce():\n value=3\n print((lambda:value)())\n yield value\nprint(list(produce()))\n', ('',)), 'captured_parameter_rebind': ('def produce(values):\n print("start",(lambda:values[0])())\n yield values[0]\n values=[9]\n print("again",(lambda:values[0])())\n yield values[0]\nvalues=[3]\niterator=produce(values)\nprint("created")\nvalues[0]=7\nprint(next(iterator))\nvalues[0]=11\nprint(next(iterator),values)\n', ('',)), 'independent_interleaved_frames': ('def produce(start):\n print("read",(lambda:start)())\n yield start\n start+=1\n print("read",(lambda:start)())\n yield start\nfirst=produce(3)\nsecond=produce(10)\nsaved=first\nprint(first is saved,next(first),next(second))\nprint(next(saved),next(second))\n', ('',)), 'parent_live_nonlocal': ('def make():\n value=3\n def produce(step):\n  nonlocal value\n  print("start",value)\n  yield value\n  value+=step\n  print("again",value)\n  yield value\n def change(other):\n  nonlocal value\n  value=other\n return produce,change\nproduce,change=make()\niterator=produce(2)\nprint("created")\nchange(7)\nprint(next(iterator))\nchange(11)\nprint(next(iterator))\n', ('',)), 'own_and_parent_cells': ('def make(values):\n def produce(offset):\n  print("before",(lambda:values[0]+offset)())\n  yield offset\n  offset+=2\n  print("after",(lambda:values[0]+offset)())\n  yield offset\n return produce\nvalues=[3]\nproduce=make(values)\niterator=produce(5)\nvalues[0]=7\nprint(next(iterator))\nvalues[0]=11\nprint(next(iterator))\n', ('',)), 'defaults_before_creation_not_pull': ('def make(values):\n def produce(step=len(values)):\n  print("default",(lambda:step)())\n  yield step\n  step+=1\n  print("changed",(lambda:step)())\n  yield step\n return produce\nvalues=[1,2]\nproduce=make(values)\nvalues.append(3)\niterator=produce()\nvalues.append(4)\nprint("created",values)\nprint(next(iterator),next(iterator))\n', ('',)), 'captured_mutable_alias': ('def produce(values):\n print((lambda:(values.append(5),len(values))[1])())\n yield len(values)\n print((lambda:(values.append(9),len(values))[1])())\n yield len(values)\nvalues=[3]\niterator=produce(values)\nprint(next(iterator),values)\nvalues.append(7)\nprint(next(iterator),values)\n', ('',)), 'unbound_cell_before_yield': ('def produce():\n if int(input()):value=5\n print((lambda:value)())\n yield value\niterator=produce()\nprint("created")\nprint(next(iterator))\n', ('0\n', '1\n')), 'error_after_partial_consumption': ('def produce(values):\n print((lambda:values[0])())\n yield values[0]\n print((lambda:values[1])())\n yield values[1]\nvalues=[3]\niterator=produce(values)\nprint(next(iterator))\nprint(next(iterator))\n', ('',)), 'parent_rebound_before_first_pull': ('def make():\n values=[3]\n def produce():\n  yield values[0]\n  yield values[0]+1\n def replace(other):\n  nonlocal values\n  values=other\n return produce,replace\nproduce,replace=make()\niterator=produce()\nreplace([10])\nprint(next(iterator))\nreplace([20])\nprint(next(iterator))\n', ('',)), 'parent_effects_only_on_pull': ('def make():\n value=0\n def produce():\n  nonlocal value\n  value+=1\n  yield value\n  value+=1\n  yield value\n def read():return value\n return produce,read\nproduce,read=make()\niterator=produce()\nprint("created",read())\nprint(next(iterator),read())\nprint("partial",read())\n', ('',)), 'captured_scalar_type_changes': ('def produce(value):\n print((lambda:value)())\n yield 1\n value="changed"\n print((lambda:value)())\n yield 2\n value=None\n print((lambda:value)())\n yield 3\nprint(list(produce(7)))\n', ('',))}

CASES.update({'parent_deleted_after_yield': ('def make():\n values=[3]\n def produce():\n  yield values[0]\n  yield values[0]+1\n def erase():\n  nonlocal values\n  del values\n return produce,erase\nproduce,erase=make()\niterator=produce()\nprint(next(iterator))\nerase()\nprint(next(iterator))\n', ('',)), 'mutable_default_alias': ('def make(values):\n def produce(items=values):\n  print((lambda:items[0])())\n  yield items[0]\n  items.append(9)\n  print((lambda:items[-1])())\n  yield len(items)\n return produce\nvalues=[3]\nproduce=make(values)\niterator=produce()\nvalues[0]=7\nprint(next(iterator))\nvalues.append(11)\nprint(next(iterator),values)\n', ('',)), 'captured_loop_state': ('def produce(n):\n total=0\n for index in range(n):\n  total+=index\n  print((lambda:total)())\n  yield total\nfirst=produce(4)\nsecond=produce(2)\nprint(next(first),next(first),next(second))\nprint(list(first),list(second))\n', ('',)), 'grandparent_chain': ('def outer(values):\n def middle(offset):\n  def produce(step):\n   print((lambda:values[0]+offset+step)())\n   yield step\n   step+=2\n   print((lambda:values[0]+offset+step)())\n   yield step\n  return produce\n return middle\nvalues=[3]\nfactory=outer(values)\nproduce=factory(5)\niterator=produce(7)\nvalues[0]=11\nprint(next(iterator))\nvalues[0]=13\nprint(next(iterator))\n', ('',)), 'frame_outlives_callable_aliases': ('def make(values):\n def produce():\n  yield values[0]\n  yield values[0]+1\n def replace(other):\n  nonlocal values\n  values=other\n return produce,replace\nproduce,replace=make([3])\niterator=produce()\nreplace([7])\nproduce=None\nreplace=None\nprint(next(iterator),next(iterator))\n', ('',))})

CASES.update({'nested_without_free_cells':('def make():\n def produce(n):\n  yield n\n  yield n+1\n return produce\nprint(list(make()(7)))\n',('',))})

CASES.update({'repeated_generator_default_snapshots':('def make():\n functions=[]\n for value in (3,7):\n  def produce(saved=[value]):\n   yield saved[0]\n   saved[0]+=1\n   yield saved[0]\n  functions.append(produce)\n return functions\nfirst,second=make()\na,b=first(),second()\nfirst=None\nsecond=None\nprint(next(a),next(b),next(a),next(b))\n',('',))})

class SourceGeneratorEnvironmentExecutionTests(unittest.TestCase):
 compare=assertion_tests.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
for _name in CASES:setattr(SourceGeneratorEnvironmentExecutionTests,'test_'+_name,_case(_name))

BOUNDARIES={'actual_parent_generator_cycle': 'def make():\n cursor=None\n def produce():\n  yield cursor is not None\n cursor=produce()\n return cursor\niterator=make()\nprint(next(iterator))\n', 'parent_callable_payload_boundary': 'def make(callback):\n def produce():\n  yield callback()\n return produce\nproduce=make(lambda:7)\nprint(list(produce()))\n'}

BOUNDARIES.update({'default_function_cycle':'def make():\n functions=[]\n def read():return functions[0]\n for unused in (0,):\n  def produce(saved=read):\n   yield 1\n  functions.append(produce)\n return produce\niterator=make()()\nprint(next(iterator))\n'})

class SourceGeneratorEnvironmentBoundaryTests(unittest.TestCase):
 def test_real_cycle_and_unsupported_parent_payload_keep_positioned_diagnostics(self):
  from py2fastrust import transpile,TranspileOptions
  for name,source in BOUNDARIES.items():
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename='generator_environment.py'))
    self.assertFalse(result.success,(name,integer,result.diagnostics))
    self.assertTrue(any(d.code=='E006'and d.line>0 for d in result.diagnostics),(name,result.diagnostics))
    if name in {'actual_parent_generator_cycle','default_function_cycle'}:
     self.assertTrue(any('cycle'in d.message for d in result.diagnostics),result.diagnostics)
    else:self.assertTrue(any('retains a callable'in d.message for d in result.diagnostics),result.diagnostics)

class SourceGeneratorEnvironmentOwnershipTests(unittest.TestCase):
 def test_concrete_frame_and_lifetime_graph_retain_the_actual_environment(self):
  from unittest.mock import patch
  from py2fastrust import transpile,TranspileOptions
  import py2fastrust.native_source_generators as generators
  import py2fastrust.native_class_gc as gc
  for name in ('captured_parameter_rebind','parent_rebound_before_first_pull','own_and_parent_cells','repeated_generator_default_snapshots'):
   source=CASES[name][0];observed=[];generated=[]
   original=gc.lexical_projection;original_generate=generators.generate
   def observe(model,edges):
    observed.append({key:set(value)for key,value in edges.items()})
    return original(model,edges)
   def observe_generate(emitter):
    code=original_generate(emitter)
    if code is not None:generated.append((emitter,code))
    return code
   with patch.object(gc,'lexical_projection',observe),patch.object(generators,'generate',observe_generate):
    result=transpile(source,TranspileOptions(integer='i64',filename='generator_environment.py'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertEqual(len(generated),1)
   emitter,code=generated[0];model=emitter.model;plan=emitter.plan
   own=model.lexical.environments.get(model.lexical.scope(plan))
   parent=model.lexical.parent_scope(plan);record=plan.source_generator.record
   expected=own.scope if own is not None else parent
   self.assertIn(('environment',expected),observed[-1]['iterator',record.index])
   self.assertNotIn('Weak',code)
   if own is not None:
    self.assertIn('lexical_environment:std::rc::Rc<'+model.lexical.environment_type(own.scope)+'>',code)
    self.assertIn('let class_lexical_environment=frame.lexical_environment.clone();',code)
    self.assertFalse({key[0]for key in emitter.slots}.intersection(own.fields))
   else:
    self.assertIn('lexical_parent:std::rc::Rc<'+model.lexical.environment_type(parent)+'>',code)
    self.assertIn('let class_lexical_parent=frame.lexical_parent.clone();',code)
   self.assertFalse(model.lexical_capture_views)
   from py2fastrust.native_classes import shape
   from py2fastrust.native_source_generator_environments import retained_kinds
   retained=retained_kinds(model,plan)
   scope=own.scope if own is not None else parent
   while scope is not None:
    environment=model.lexical.environments[scope]
    for cell in environment.defaults.values():self.assertIn(shape(cell),retained)
    for definition,function in environment.functions.items():
     if definition in model.lexical.repeated_definitions:
      self.assertIn(('function_defaults',definition),observed[-1]['environment',scope])
      self.assertIn(('function_defaults',definition),observed[-1])
    scope=environment.parent
 def test_default_function_backedges_remain_in_the_actual_ownership_graph(self):
  from unittest.mock import patch
  from py2fastrust import transpile,TranspileOptions
  import py2fastrust.native_class_gc as gc
  observed=[];original=gc.lexical_projection
  def observe(model,edges):
   observed.append({key:set(value)for key,value in edges.items()})
   return original(model,edges)
  with patch.object(gc,'lexical_projection',observe):
   result=transpile(BOUNDARIES['default_function_cycle'],TranspileOptions(filename='generator_defaults.py'))
  self.assertFalse(result.success)
  self.assertTrue(any(d.code=='E006'and 'cycle'in d.message for d in result.diagnostics),result.diagnostics)
  self.assertTrue(observed)
  nodes=[node for node in observed[-1]if node[0]=='function_defaults']
  self.assertTrue(nodes)
  self.assertTrue(any(target[0]=='environment'for node in nodes for target in observed[-1][node]))
  self.assertTrue(any(node in targets for source,targets in observed[-1].items()if source[0]=='environment'for node in nodes))

if __name__=='__main__':unittest.main()
