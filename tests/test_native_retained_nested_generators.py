"""Retained multi-clause generator expressions keep original suspended state."""
import ast
import os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Model
import test_native_annotations_assertions as support


CASES={
 'legacy_original_for':('''
answer=0
for value in (x+y for x in range(3) for y in range(4) if y%2):
    if value==1:
        continue
    if value==4:
        break
    answer+=value
print(answer,value)
answer=0
for value in (x for x in (y*y for y in range(5))):
    if value==1:
        continue
    if value==9:
        break
    answer+=value
print(answer,value)
''',('',)),
 'retained_iterator_identity_inner':('''source=iter([4,5,6])
def make():
 return (item for outer in [1,2] for item in source)
g=make()
print(next(g),next(source),list(g),next(source,99))
''',('',)),
 'returned_captured_inner_cursor_alias':('''saved=iter([2,3,4,5])
class Shared:
 def __iter__(self):return saved
g=((x,y) for x in [1,2] for y in Shared())
print(next(saved),next(g),next(saved),list(g),next(saved,99))
''',('',)),
 'created_never_pulled_nested_body':('''g=(missing(x,y) for x in [1,2] for y in unknown)
print(type(g).__name__,g.close())
''',('',)),
 'nested_parameter_rows':('''def make(rows):
 return (x+y for x,row in enumerate(rows) for y in row if y>1)
rows=[[1,2],[3,4]]
g=make(rows)
print(next(g))
rows[1].append(5)
print(list(g),rows)
''',('',)),
 'finite_inner_cursor_choices':('''def choose(flag):
 if flag:return iter([2,3])
 return iter(range(2))
g=((x,y) for x in [0,1] for y in choose(x))
print(next(g),list(g))
''',('',)),
 'promoted_original_multiple_for_boundary':('g=(x+y for x in [1] for y in [2])\nprint(list(g))',('',)),
 'competitive_edge_expansion':('''n=int(input())
rows=[[1,2],[2],[],[0,2]]
edges=((u,v) for u in range(n) if u%2==0 for v in rows[u] if v!=u)
print(next(edges,(-1,-1)))
print(list(edges),next(edges,(-2,-2)))
''',('0\n','4\n')),
 'creation_inner_acquisition_and_filters':('''events=[]
def outer():
 events.append(1)
 return [0,1,2,3]
def inner(x):
 events.append(10+x)
 return range(x)
def keep(x):
 events.append(20+x)
 return x!=2
def value(x,y):
 events.append(30+x+y)
 return 10*x+y
g=(value(x,y) for x in outer() if keep(x) for y in inner(x) if keep(y))
print(events)
print(next(g),events)
print(list(g),events)
''',('',)),
 'three_clauses_repeated_empty_inner':('''g=((x,y,z) for x in [0,2,1] for y in range(x) for z in range(y+1) if x+z!=2)
print(next(g,(-1,-1,-1)))
print(list(g),next(g,(-2,-2,-2)))
''',('',)),
 'shared_partial_input_and_generator_alias':('''source=iter([1,2,3,4,5,6])
g=(10*x+y for x in [1,2,3] for y in source if y%2)
alias=g
print(iter(alias) is g,next(source),next(g),next(source),next(alias))
print(list(g),list(source),next(alias,77))
''',('',)),
 'two_generators_share_inner_cursor':('''source=iter([2,3,4,5,6])
first=(x+y for x in [10,20] for y in source)
second=(x*y for x in [2,3] for y in source)
print(next(first),next(second),next(first),next(second))
print(list(first),list(second))
''',('',)),
 'inner_iter_protocol_is_deferred_and_repeated':('''events=[]
class Values:
 def __init__(self,x):self.x=x
 def __iter__(self):
  events.append(self.x)
  return iter([self.x,self.x+1])
g=(x+y for x in [2,5] for y in Values(x))
print(events)
print(next(g),events)
print(list(g),events)
''',('',)),
 'reused_targets_and_nonleaking_scope':('''x=90
y=80
g=(x+y for x in [2,3] for x,y in [(x,1),(x+10,2)])
print(next(g),x,y)
print(list(g),x,y)
''',('',)),
 'late_binding_inner_callback_and_global':('''scale=2
def make():
 offset=1
 g=(scale*(x+y)+offset for x in [1,2] for y in range(offset))
 offset=3
 return g
g=make()
scale=4
print(next(g))
scale=10
print(list(g))
''',('',)),
 'inner_target_captured_by_yielded_lambda':('''g=(lambda:(x,y) for x in [1,2] for y in [3,4])
first=next(g)
second=next(g)
print(first(),second())
rest=list(g)
print(first(),rest[0](),rest[1]())
''',('',)),
 'inner_live_owner_rebinding':('''values=[2,3]
g=(x+y for x in [10,20] for y in values)
print(next(g))
old=values
values=[8]
old.append(4)
print(list(g),old,values)
''',('',)),
 'inner_unpack_error_after_partial_yield':('''g=(x+a+b for x in [1,2] for a,b in [[3,4],[5]])
print('created',next(g))
print(next(g))
''',('',)),
 'inner_source_error_is_deferred':('''def inner(x):
 print('inner',x)
 return range(3//x)
g=(x+y for x in [2,0,3] for y in inner(x))
print('created')
print(next(g))
print(next(g))
''',('',)),
 'inner_filter_error_keeps_scope':('''g=(x+y for x in [1,2] for y in [2,0] if 4//y)
print('created',next(g))
print(next(g))
''',('',)),
 'outer_iter_error_happens_at_creation':('''print('before')
g=(x+y for x in 7 for y in [1,2])
print('after')
''',('',)),
 'close_before_and_mid_inner':('''events=[]
def value(x,y):
 events.append(x+y)
 return x*y
g=(value(x,y) for x in [2,3] for y in [4,5])
print(g.close(),next(g,77),events)
h=(value(x,y) for x in [3,4] for y in [5,6])
print(next(h),events)
print(h.close(),next(h,88),events)
''',('',)),
}


BOUNDARIES={
 'walrus':"g=((saved:=x+y) for x in [1] for y in [2])\nprint(list(g),saved)\n",
 'collected_inner_target':"class Node:\n def __init__(self):self.edge=None\nroot=Node()\nroot.edge=root\ng=(node for x in [1] for node in [root])\nprint(next(g) is root)\n",
 'owned_environment_cycle_without_pull':"def make():\n source=[]\n g=(x for unused in [1] for x in source)\n source.append(g)\n return g\nprint(type(make()).__name__)\n",
 'send':"g=(x+y for x in [1] for y in [2])\nprint(g.send(None))\n",
 'throw':"g=(x+y for x in [1] for y in [2])\nprint(g.throw(ValueError))\n",
 'self_cycle':"g=(x+y for x in [1] for y in g)\nprint(next(g))\n",
 'callback_environment_cycle':"def make():\n g=(x+y for x in [1] for y in map(lambda _:next(g),[1]))\n return g\nprint(next(make()))\n",
}


class RetainedNestedGeneratorMetadataTests(unittest.TestCase):
 def test_original_ast_and_suspended_scope(self):
  source=CASES['three_clauses_repeated_empty_inner'][0]
  unit=parse_source(source)
  before=ast.dump(unit.tree,include_attributes=True)
  from py2fastrust.native import try_generate_native
  seen=[];actual=Model.analyze_body
  def analyze(model,plan,environment):
   if getattr(plan,'_native_retained_expression',False):
    self.assertIsInstance(plan.node,ast.GeneratorExp)
    self.assertIn(plan.node,tuple(ast.walk(model.unit.tree)))
    self.assertEqual(plan.scope,'<genexpr>')
    self.assertEqual(model.lexical.scope(plan),model.unit.scope_for(plan.node).ordinal)
    seen.append(plan.index)
   return actual(model,plan,environment)
  diagnostics=[]
  with patch.object(Model,'analyze_body',analyze):
   result=try_generate_native(source,unit.filename,'i64',unit=unit,diagnostic_out=diagnostics)
  self.assertIsNotNone(result,diagnostics)
  self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
  self.assertTrue(seen)
  self.assertNotIn('enum Instruction',result)

 def test_true_cycles_and_injection_protocols_stay_guarded(self):
  expected={'collected_inner_target':'traced nested-generator class roots','owned_environment_cycle_without_pull':'reference cycle','self_cycle':'reference cycle','callback_environment_cycle':'reference cycle','send':'send()','throw':'throw()','walrus':'assignment expressions'}
  for name,source in BOUNDARIES.items():
   for integer in ('i64','i128','bigint'):
    with self.subTest(name=name,integer=integer):
     result=transpile(source,TranspileOptions(integer=integer,filename='nested_generator.py'))
     self.assertFalse(result.success)
     self.assertTrue(any(d.code=='E006'and d.line>0 for d in result.diagnostics),result.diagnostics)
     self.assertIn(expected[name],' '.join(d.message for d in result.diagnostics))

 def test_raw_graph_retains_actual_returned_inner_cursor(self):
  source=CASES['returned_captured_inner_cursor_alias'][0]
  import py2fastrust.native_class_gc as collector
  actual=collector.lexical_projection;snapshots=[]
  def observe(model,edges):
   snapshots.append((model,{node:set(children)for node,children in edges.items()}))
   return actual(model,edges)
  with patch.object(collector,'lexical_projection',observe):
   result=transpile(source,TranspileOptions(filename='nested_generator.py'))
  self.assertTrue(result.success,result.diagnostics)
  found=False
  for model,edges in snapshots:
   registry=getattr(model,'retained_generators',None)
   if registry is None:continue
   for expression in registry.records:
    if len(expression.node.generators)<=1 or expression.body is None:continue
    found=True
    self.assertEqual(len(expression.inners),len(expression.node.generators)-1)
    for kind in expression.inners:
     self.assertTrue(model.iterators.owns(kind))
     self.assertIn(('iterator',kind.index),edges[('iterator',expression.iterator.index)])
  self.assertTrue(found)



PEP479_SOURCE='''def source(value):
 if value==0:raise StopIteration('inner stopped')
 return range(value)
g=(x+y for x in [1,0] for y in source(x))
print(next(g))
print(next(g))
'''


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class RetainedNestedGeneratorExceptionTests(unittest.TestCase):
 def test_inner_stopiteration_keeps_pep479_cause_chain(self):
  source=PEP479_SOURCE;filename='nested_generator_stop.py'
  reference='import traceback,sys\ntry:exec(compile('+repr(source)+','+repr(filename)+',"exec"))\nexcept BaseException as e:traceback.print_exception(e);sys.exit(1)\n'
  cp=subprocess.run([sys.executable,'-I','-S','-c',reference],capture_output=True,text=True,timeout=10)
  expected=re.findall(r'File "nested_generator_stop.py", line (\d+), in ([^\n]+)',cp.stderr)
  with tempfile.TemporaryDirectory(prefix='pytors-nested-expression-')as directory:
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename=filename,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    self.assertLess(len(result.rust_source.encode()),512*1024)
    rust=Path(directory)/(integer+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((ran.returncode,ran.stdout),(cp.returncode,cp.stdout),ran.stderr)
     self.assertEqual(ran.stderr.splitlines()[-1],cp.stderr.splitlines()[-1])
     self.assertEqual(re.findall(r'File "nested_generator_stop.py", line (\d+), in ([^\n]+)',ran.stderr),expected)
     self.assertIn('The above exception was the direct cause',ran.stderr)


class RetainedNestedGeneratorExecutionTests(unittest.TestCase):
 pass


def _case(name):
 def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*CASES[name])
 return test


for _name in CASES:
 setattr(RetainedNestedGeneratorExecutionTests,'test_'+_name,_case(_name))


if __name__=='__main__':unittest.main()
