"""Source generator frames preserve Python creation and suspension semantics."""
import unittest
import os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={
 'finite_multiple_yields':'''def values(n):
 yield -1
 for i in range(n):
  yield i
  yield i+10
 yield 99
stream=values(3)
other=stream
print(next(stream),next(other),list(stream),list(other),next(stream,123))
''',
 'infinite_numeric_state':'''def values(seed=5):
 while True:
  seed=seed*3+1
  yield seed
stream=values()
print(next(stream),next(stream),next(stream))
second=values(2)
print(next(second),next(stream),next(second))
''',
 'creation_and_argument_defaults':'''events=[]
def mark(value):
 events.append(value)
 return value
def values(first=mark(7)):
 events.append(30)
 yield first
 events.append(40)
 yield first+1
stream=values(mark(9))
print(events)
print(next(stream),events)
print(next(stream),events)
print(next(stream,0),events)
print(list(values()),events)
''',
 'live_globals':'''value=2
def values():
 yield value
 yield value
stream=values()
value=7
print(next(stream))
value=11
print(next(stream),next(stream,99))
''',
 'aliases_and_mutation':'''def values(items):
 yield items[0]
 items.append(9)
 yield items[-1]
items=[3]
stream=values(items)
items[0]=8
print(next(stream),items)
print(next(stream),items)
print(next(stream,0),items)
''',
 'while_branches_and_loop_else':'''def values(n):
 i=0
 while i<n:
  i+=1
  if i==2:continue
  if i==5:break
  yield i
 else:
  yield 70
 yield 80
print(list(values(3)),list(values(9)),list(values(0)))
''',
 'nested_for_else':'''def values():
 for i in range(3):
  for j in range(3):
   if j==1:break
   yield i*10+j
  else:yield 88
 else:yield 99
 return
 yield 77
print(list(values()))
''',
 'class_static_and_zero_arg':'''class Values:
 @staticmethod
 def values():
  yield 3
  yield 4
 def direct():
  yield 5
print(list(Values.values()),list(Values().values()),list(Values.direct()))
''',
 'body_error_deferred':'''def values():
 print('entered')
 yield 1//0
stream=values()
print('created')
print(next(stream))
''',
 'error_after_resume':'''def values():
 yield 3
 print('resumed')
 yield 1//0
stream=values()
print(next(stream))
print(next(stream))
''',
 'finite_exhaustion':'''def values():
 yield 5
 return None
stream=values()
print(next(stream))
print(next(stream))
''',
 'zero_iteration':'''def values(n):
 for i in range(n):yield i
print(list(values(0)),next(values(0),44))
''',
 'unbound_suspended_local':'''def values():
 yield x
 x=3
stream=values()
print('created')
print(next(stream))
''',
 'unreachable_yield':'''def values():
 if False:yield 1
print(list(values()),next(values(),99))
''',
 'for_mutation_and_resume':'''def values(items):
 for value in items:
  yield value
items=[1,2]
stream=values(items)
print(next(stream))
items.append(3)
print(list(stream))
''',
 'effects_and_binding_widening':'''value=0
def values():
 global value
 value=1
 yield value
 value=2
stream=values()
print(value)
print(next(stream),value)
print(next(stream,99),value)
''',
 'native_tight_inner_loop':'''def values(n):
 for i in range(n):
  j=0
  total=0
  while j<20:
   total+=j
   j+=1
  yield total+i
print(list(values(4)))
''',
 'late_global_and_callable_binding':'''def values():
 yield value
 yield current()
stream=values()
value=8
def first():return 9
def second():return 10
current=first
print(next(stream))
current=second
print(next(stream),next(stream,None))
''',
 'type_changes_and_yield_union':'''def values():
 state=3
 yield state
 state='changed'
 yield state
 yield
stream=values()
print(list(stream))
unused=values()
print('created')
''',
 'conditional_yields_and_default_evaluation':'''events=[]
def default():
 events.append(9)
 return -1
def values(n):
 for i in range(n):
  events.append(i)
  if i%2:
   yield i
   events.append(20)
  else:
   yield -i
  yield i+10
stream=values(2)
print(next(stream,default()),events)
print(next(stream,default()),events)
print(list(stream),events)
print(next(stream,default()),events)
''',
 'hidden_global_cursor_keeps_shared_position':'''source=iter([1,2,3,4])
def values():
 for value in source:
  yield value
stream=values()
print(next(source),next(stream),next(source))
print(list(stream),list(source))
''',
}

class SourceGeneratorExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_source_generator_execution(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

# Inherit the execution helper, without re-running its unrelated fixture tests.
for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(SourceGeneratorExecutionTests,_name,None)

class SourceGeneratorGuards(unittest.TestCase):
 def test_unsupported_suspension_protocols_are_diagnosed(self):
  cases=(('yield from [1]','delegat'),('x=yield 1','send'),('yield 1\nreturn 3','StopIteration.value'),('try:\n yield 1\nfinally:\n print(2)','cleanup'))
  for body,fragment in cases:
   src='def values():\n '+body.replace('\n','\n ')+'\nprint(list(values()))\n'
   with self.subTest(src=src):
    result=transpile(src,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)

 def test_send_throw_close_and_recursive_resume_are_explicit(self):
  for operation in ('send(None)','throw(ValueError())','close()'):
   result=transpile('def values():\n yield 1\nstream=values()\nstream.'+operation+'\n',TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn('source generator '+operation.split('(')[0],result.diagnostics[0].message)
  result=transpile('def values():\n yield next(stream)\nstream=values()\nprint(next(stream))\n',TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertIn('resumable recursive call continuation',result.diagnostics[0].message)

 def test_unsupported_statement_diagnostics_name_the_construct(self):
  cases=(('with manager:\n yield 1','with statement'),('raise ValueError()\nyield 1','raise statement'),('x=1\ndel x\nyield 1','del statement'),('def child():return 1\nyield 1',"nested function definition 'child'"),('class Child:pass\nyield 1',"nested class definition 'Child'"))
  for body,name in cases:
   result=transpile('def values():\n '+body.replace('\n','\n ')+'\nprint(list(values()))\n',TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn(name,result.diagnostics[0].message)

 def test_native_loops_only_dispatch_at_suspension(self):
  result=transpile(CASES['native_tight_inner_loop'],TranspileOptions(license='none'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertEqual(result.rust_source.count('match frame.pc'),1)
  self.assertGreaterEqual(result.rust_source.count(':loop{'),2)
  self.assertNotRegex(result.rust_source,r'frame\.pc=[^;]+;continue;')
  self.assertNotIn('ClassNativePc_',result.rust_source)

 def test_unreachable_generator_keeps_ordinary_optimization_proofs(self):
  source='def unused():\n yield 1\ndef total(n):\n return n+1\nprint(total(3))\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertNotIn('ClassSourceGeneratorFrame_',result.rust_source)
  self.assertNotIn('control.depth+=1',result.rust_source)
  self.assertNotIn('ClassSyncDepth',result.rust_source)

 @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
 def test_generator_stop_iteration_keeps_direct_cause(self):
  source='def values():\n yield next(iter(()))\nstream=values()\nprint("created")\nprint(next(stream))\n'
  reference='import traceback,sys\ntry:exec(compile('+repr(source)+',"generator_case.py","exec"))\nexcept BaseException as e:traceback.print_exception(e);sys.exit(1)\n'
  cp=subprocess.run([sys.executable,'-I','-S','-c',reference],capture_output=True,text=True,timeout=10)
  expected=re.findall(r'File "generator_case.py", line (\d+), in ([^\n]+)',cp.stderr)
  with tempfile.TemporaryDirectory(prefix='pytors-source-generator-')as directory:
   for mode in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=mode,filename='generator_case.py',license='none'))
    self.assertTrue(result.success,result.diagnostics)
    rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021','--crate-name','source_generator',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
     self.assertEqual(actual.stderr.splitlines()[-1],cp.stderr.splitlines()[-1])
     self.assertEqual(re.findall(r'File "generator_case.py", line (\d+), in ([^\n]+)',actual.stderr),expected)
     self.assertIn('The above exception was the direct cause',actual.stderr)

if __name__=='__main__':unittest.main()
