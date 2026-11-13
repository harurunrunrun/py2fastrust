"""Retained original generator-expression frames have Python pull semantics."""
import ast
import os,re,subprocess,sys,tempfile
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import parse_source
from py2fastrust.native_frame_selection import select_frames
import test_native_class_iterators as iterator_tests


CASES={
 'creation_filters_and_shared_cursor':'''events=[]
def outer():
 events.append(1)
 return [0,1,2,3]
def keep(x):
 events.append(x+10)
 return x%2
def value(x):
 events.append(x+20)
 return x*3
g=(value(x) for x in outer() if keep(x))
h=g
print(events,iter(g) is h)
print(next(g),events)
print(list(h),events,next(g,99),list(g))
''',
 'local_module_and_forward_binding':'''number=2
def make():
 scale=3
 g=(scale*x+number for x in [1,2])
 scale=7
 return g
g=make()
number=10
print(next(g))
number=20
print(list(g))
h=(later(x) for x in [4,5])
def later(x):return x+1
print(list(h))
''',
 'target_scopes_and_nested_expressions':'''g=(lambda:x for x in [1,2])
f=next(g)
h=next(g)
print(f(),h())
rows=[(x for _ in range(2)) for x in [3,4]]
print(list(rows[0]),list(rows[1]))
outer=((x+i for i in range(2)) for x in [10,20])
left=next(outer)
right=next(outer)
print(list(left),list(right))
g=(_ for _,_ in [(1,'a'),(2,'b')])
print(list(g))
''',
 'yielded_iterators_and_unpacking':'''rows=['1 2','3 4','5 6']
g=(map(int,row.split()) for row in rows)
print([a*10+b for a,b in g])
g=(a+b for a,b in [(1,2),(3,4)] if a<3)
print(list(g))
''',
 'outer_owner_captured_and_exhaustion':'''items=[1,2]
g=(x for x in items)
alias=items
items=[99]
print(next(g))
alias.append(3)
print(list(g))
alias.append(4)
print(list(g),items,alias)
''',
 'source_receiver_live_fields':'''class Bag:
 def __init__(self):
  self.bias=2
  self.items=[1,2]
 def stream(self):return (self.bias+x for x in self.items)
bag=Bag()
g=bag.stream()
bag.bias=20
bag.items.append(3)
print(list(g))
''',
 'outer_iter_called_at_creation':'''events=[]
class Values:
 def __iter__(self):
  events.append(7)
  return iter([1,2])
g=(x+10 for x in Values())
print(events)
print(next(g),list(g),events)
''',
 'close_before_and_after_pull':'''events=[]
def mark(x):
 events.append(x)
 return x
g=(mark(x) for x in [1,2])
print(g.close(),events,next(g,99))
h=(mark(x) for x in [3,4])
print(next(h),events)
print(h.close(),h.close(),next(h,88),events)
''',
 'created_never_pulled':'''def mark(x):
 print('unreachable',x)
 return x
g=(mark(x) for x in [1,2])
print(type(g).__name__)
print(g.close())
''',
 'outer_error_now':'''print('before')
g=(x for x in 3)
print('unreachable')
''',
 'body_error_later':'''g=(10//x for x in [2,0,3])
print('created')
print(next(g))
print(next(g))
''',
 'filter_error_later':'''def check(x):return 1//x
g=(x for x in [2,0] if check(x))
print('created')
print(next(g))
''',
 'pep479':'''def stop():raise StopIteration('halt')
g=(stop() for x in [1])
print('created')
print(next(g))
''',
 'close_running':'''g=(g.close() for x in [1])
print(next(g))
''',
 'deferred_unbound_free':'''def make():
 g=(value+x for x in [1])
 value=4
 del value
 return g
g=make()
print('created')
print(next(g))
''',
 'module_type_change':'''value=3
g=(value for x in [1,2])
print(next(g))
value='changed'
print(next(g))
''',
 'separate_enclosing_frames':'''def make(start):
 def value(x):return start+x
 return (value(x) for x in [1,2])
first=make(10)
second=make(30)
print(next(first),next(second),list(first),list(second))
''',
 'close_argument_errors':'''def mark(x):
 print('argument',x)
 return x
g=(x for x in [1])
g.close(mark(9))
''',
 'empty_close':'''empty=(x for x in [])
print(list(empty),next(empty,88),empty.close())
''',
 'nonlocal_updates_at_pull':'''def make():
 count=0
 def tick(x):
  nonlocal count
  count+=x
  return count
 first=(tick(x) for x in [1,2])
 second=(tick(x) for x in [10,20])
 return first,second
first,second=make()
print(next(first),next(second),next(first),next(second))
''',
}


class RetainedExpressionAnalysisTests(unittest.TestCase):
 def test_reached_retained_selection_and_immediate_controls(self):
  self.assertTrue(select_frames(parse_source('g=(x+1 for x in [1,2])\nprint(next(g))')).required)
  self.assertFalse(select_frames(parse_source('print(sum(x+1 for x in [1,2]))')).required)
  self.assertFalse(select_frames(parse_source('print(list(x+1 for x in [1,2]))')).required)

 def test_original_nodes_survive_scope_analysis(self):
  source='def make(xs):\n return (x+1 for x in xs if x)\ng=make([1,2])\nprint(list(g))\n'
  unit=parse_source(source)
  node=next(x for x in ast.walk(unit.tree)if isinstance(x,ast.GeneratorExp))
  self.assertEqual(unit.scope_for(node).name,'genexpr')
  before=ast.dump(unit.tree,include_attributes=True)
  from py2fastrust.native_classes import Model
  actual=Model.analyze_body;seen=[]
  def analyze(model,plan,environment):
   if getattr(plan,'_native_retained_expression',False):
    self.assertIs(model.plans[plan.index],plan)
    self.assertIsInstance(plan.node,ast.GeneratorExp)
    self.assertEqual(plan.scope,'<genexpr>')
    self.assertTrue(any(node is plan.node for node in ast.walk(model.unit.tree)))
    self.assertFalse(any(value is plan for value in model.functions.values()))
    self.assertEqual(model.lexical.scope(plan),model.unit.scope_for(plan.node).ordinal)
    seen.append(plan.index)
   return actual(model,plan,environment)
  with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')),patch.object(Model,'analyze_body',analyze):
   result=transpile(source,TranspileOptions(license='none'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
  self.assertIn('ClassRetainedExpressionFrame_',result.rust_source)
  self.assertNotIn('enum Instruction',result.rust_source)
  self.assertTrue(seen)

 def test_named_capability_boundaries(self):
  cases={
   'multiple for clauses':'g=(x+y for x in [1] for y in [2])\nprint(list(g))',
   'send':'g=(x for x in [1])\nprint(g.send(None))',
   'throw':'g=(x for x in [1])\nprint(g.throw(ValueError))',
   'recursive/asynchronous':'g=(next(g) for x in [1])\nprint(next(g))',
   'exception-handler routing':'g=(10//x for x in [0])\ntry:\n next(g)\nexcept ZeroDivisionError:\n print(next(g,77))',
  }
  for expected,source in cases.items():
   with self.subTest(expected=expected):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(expected,' '.join(str(d)for d in result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class RetainedExpressionExecutionTests(unittest.TestCase):
 cases=CASES
 check=iterator_tests.IteratorExecutionTests.check
 def test_creation_and_iteration(self):
  for name in ('creation_filters_and_shared_cursor','outer_owner_captured_and_exhaustion','outer_iter_called_at_creation'):
   with self.subTest(name=name):self.check(name)
 def test_lexical_cells_and_owned_captures(self):
  for name in ('local_module_and_forward_binding','target_scopes_and_nested_expressions','source_receiver_live_fields','module_type_change','separate_enclosing_frames','nonlocal_updates_at_pull'):
   with self.subTest(name=name):self.check(name)
 def test_nested_value_iterators_and_close(self):
  for name in ('yielded_iterators_and_unpacking','close_before_and_after_pull','created_never_pulled','empty_close'):
   with self.subTest(name=name):self.check(name)
 def test_errors_and_locations(self):
  for name in ('outer_error_now','body_error_later','filter_error_later','close_running','deferred_unbound_free','close_argument_errors'):
   with self.subTest(name=name):self.check(name)

 def test_pep479_direct_cause_and_original_scopes(self):
  source=CASES['pep479'];filename='expression_case.py'
  reference='import traceback,sys\ntry:exec(compile('+repr(source)+','+repr(filename)+',"exec"))\nexcept BaseException as e:traceback.print_exception(e);sys.exit(1)\n'
  cp=subprocess.run([sys.executable,'-I','-S','-c',reference],capture_output=True,text=True,timeout=10)
  expected=re.findall(r'File "expression_case.py", line (\d+), in ([^\n]+)',cp.stderr)
  with tempfile.TemporaryDirectory(prefix='pytors-retained-expression-')as directory:
   for mode in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
     result=transpile(source,TranspileOptions(integer=mode,filename=filename,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    self.assertEqual(result.backend,'native');self.assertLess(len(result.rust_source.encode()),512*1024)
    rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021','--crate-name','retained_expression',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
     self.assertEqual(actual.stderr.splitlines()[-1],cp.stderr.splitlines()[-1])
     self.assertEqual(re.findall(r'File "expression_case.py", line (\d+), in ([^\n]+)',actual.stderr),expected)
     self.assertIn('The above exception was the direct cause',actual.stderr)
