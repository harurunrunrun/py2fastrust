"""Literal while tests preserve normal-exit edges without inventing returns."""
import ast
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_loop_else import condition
from types import SimpleNamespace


CASES={
'return_from_always_true_search':'''def choose(value):
 while True:
  if value:return value
  value=7
print(choose(0)+1,choose(9)+1)
''',
'multiple_returns_continue_and_feedback':'''def solve(value):
 while True:
  value+=1
  if value%2:continue
  if value<6:return value*3
  return value-1
print(solve(0)+1,solve(5)+1)
''',
'nested_break_belongs_to_inner_loop':'''def choose(value):
 while True:
  for item in [3,4,5]:
   value+=item
   break
  while True:
   value+=1
   break
  return value
print(choose(1)+2)
''',
'unreachable_break_does_not_create_none':'''def answer():
 while True:
  return 8
  break
 missing()
print(answer()+2)
''',
'outer_break_retains_real_none':'''def answer(flag):
 while True:
  if flag:break
  return 12
print(answer(True),answer(False))
''',
'break_in_inner_else_targets_outer':'''def answer(flag):
 while True:
  for item in []:print(item)
  else:
   if flag:break
  return 13
print(answer(True),answer(False))
''',
'inner_else_continue_targets_outer':'''def answer(value):
 while True:
  value+=1
  for item in []:print(item)
  else:
   if value<3:continue
  return value
print(answer(0)+4)
''',
'false_loop_preserves_unbound_local':'''def answer():
 while False:value=8
 return value
print(answer())
''',
'false_loop_local_shadow_does_not_read_global':'''value=42
def mark():print('later argument');return 3
def answer():
 while False:value=8
 print(value,mark())
answer()
''',
'deleted_local_read_still_raises':'''def answer():
 value=3
 del value
 while False:value=8
 return value
print(answer())
''',
'zero_trip_for_local_does_not_use_loop_target_type':'''def answer():
 while False:pass
 for value in []:pass
 return value
print(answer())
''',
'nested_local_shadow_is_not_a_closure_read':'''def outer():
 value=99
 def answer():
  while False:value=8
  return value
 return answer()
print(outer())
''',
'global_and_free_reads_retain_real_binding':'''value=42
def outer():
 captured=9
 def answer():
  global value
  while False:value=8
  return value+captured
 return answer()
print(outer())
''',
'false_loop_omits_unsupported_body':'''while False:
 missing()
print('after')
''',
'false_loop_preserves_else':'''def answer():
 while 0:missing()
 else:print('else')
print(answer())
''',
'literal_integer_and_negative_truth':'''def first():
 while 1:return 3
def second():
 while -2:return 5
print(first()+second())
''',
'effectful_test_is_evaluated_each_time':'''def condition(value):
 print('test',value)
 return value<3
def answer():
 value=0
 while condition(value):
  value+=1
  if value==2:return value
 return -1
print(answer())
''',
'default_value_is_not_assumed':'''def answer(flag=True):
 while flag:return 4
print(answer(),answer(False))
''',
'return_runs_context_cleanup':'''class Manager:
 def __enter__(self):print('enter')
 def __exit__(self,typ,value,trace):print('exit')
def answer():
 while True:
  with Manager():return 9
print(answer()+1)
''',
'with_suppression_stays_inside_loop':'''class Manager:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):print('suppressed');return True
def answer():
 value=0
 while True:
  value+=1
  with Manager():
   if value<2:raise ValueError('again')
   return value
print(answer()+1)
''',
'raising_loop_preserves_failure_frame':'''def answer():
 while True:raise ValueError('stop')
print(answer())
''',
}


class LoopNormalExitExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_literal_loop_exit_contracts(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)


for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(LoopNormalExitExecutionTests,_name,None)


class LoopNormalExitProofTests(unittest.TestCase):
 def test_profile_aware_literal_truth(self):
  for mode,bits in [('i64',64),('i128',128),('bigint',0)]:
   for literal in ['True','False','1','0','-1',str(1<<64),str(1<<128)]:
    node=ast.parse('while '+literal+':pass').body[0]
    value=eval(literal,{'__builtins__':{}})
    if bits and type(value)is int:value=(value+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))
    self.assertIs(condition(SimpleNamespace(integer=mode),node),bool(value))

 def test_unresolved_or_effectful_truth_is_not_a_loop_proof(self):
  for source in ['while flag:pass','while bool(1):pass','while produce():pass','while 1+2:pass']:
   self.assertIsNone(condition(SimpleNamespace(integer='i64'),ast.parse(source).body[0]))

 def test_reached_literal_loop_selects_capability_before_codegen(self):
  unit=parse_source(CASES['return_from_always_true_search'],'main.py')
  self.assertTrue(select_frames(unit).required)
  unit=parse_source('def forever():\n while True:continue\nprint(2)\n','main.py')
  self.assertNotIn('loop exhaustion and else control flow',select_frames(unit).reasons)

 def test_continue_only_forever_helper_compiles_without_iteration_cap(self):
  source='def forever():\n while True:continue\nif int(input()):forever()\nprint(2)\n'
  with tempfile.TemporaryDirectory(prefix='pytors-loop-proof-')as directory:
   for mode in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
     result=transpile(source,TranspileOptions(integer=mode,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    self.assertEqual(result.backend,'native')
    self.assertNotIn('iteration limit',result.rust_source)
    rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     # Compile the reached helper; deliberately never execute its infinite body.

 def test_large_literals_follow_selected_wrapping_truth(self):
  source='def answer():\n while 18446744073709551616:return 7\nprint(answer())\n'
  with tempfile.TemporaryDirectory(prefix='pytors-loop-width-')as directory:
   for mode in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=mode,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(0,'None\n'if mode=='i64'else'7\n',''))

 def test_cleanup_syntax_does_not_disappear_behind_infinite_loop_proof(self):
  for clause in ['finally:\n   print(2)','except ValueError:\n   break']:
   source='def answer():\n while True:\n  try:\n   return 1\n  '+clause+'\nprint(answer())\n'
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertTrue(any('Try'in diagnostic.message or 'try'in diagnostic.message for diagnostic in result.diagnostics),result.diagnostics)

