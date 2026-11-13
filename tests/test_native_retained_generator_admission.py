"""Retained admission uses canonical consumer identity and argument roles."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import Value,analyze,value
from py2fastrust.native_module_calls import BuiltinRef
from py2fastrust.native_retained_generators import requires_frames
from py2fastrust.references import BuiltinIdentity
import test_native_class_iterators as iterator_tests


CASES={
 'shared_default_cursor':'''events=[]
def source():
 events.append(1)
 return [2,3,4]
def mark(x):
 events.append(x+10)
 return x
def pull(stream=(mark(x) for x in source())):
 return next(stream,99)
print(events)
print(pull(),events)
print(pull(),events)
print(pull(),pull(),events)
''',
 'repeat_preserves_shared_payload':'''import itertools
events=[]
def mark(x):
 events.append(x)
 return x
repeated=itertools.repeat((mark(x) for x in [1,2,3]),2)
first=next(repeated)
second=next(repeated)
print(first is second,events)
print(next(first),next(second),list(first),events)
''',
 'reduce_initial_keeps_generator_identity':'''from functools import reduce
events=[]
def mark(x):
 events.append(x)
 return x
def add(left,right):return left+right
result=reduce(add,[],initial=(mark(x) for x in [3,4]))
print(events)
print(next(result),list(result),events)
''',
 'builtin_next_default_keeps_generator':'''events=[]
def mark(x):
 events.append(x)
 return x
result=next(iter(()),(mark(x) for x in [5,6]))
print(events)
print(next(result),list(result),events)
''',
 'source_shadow_has_no_eager_contract':'''from heapq import nlargest
events=[]
def source():
 events.append(1)
 return [2,3]
def mark(x):
 events.append(x+10)
 return x
def nlargest(ignored,values):return [7]
print(nlargest((mark(x) for x in source()),[]),events)
''',
 'product_repeat_error_does_not_pull_body':'''import itertools
def source():
 print('source')
 return [2]
def mark(x):
 print('body',x)
 return x
print(list(itertools.product([1],repeat=(mark(x) for x in source()))))
''',
 'noncallable_reduce_callback_zero_items':'''from functools import reduce
events=[]
def mark(x):
 events.append(x)
 return x
print(reduce((mark(x) for x in [1,2]),[],initial=7),events)
''',
 'invalid_core_keyword_evaluates_creation_only':'''def source():
 print('source')
 return [1]
def mark(x):
 print('body',x)
 return x
print(list(iterable=(mark(x) for x in source())))
''',
}


class RetainedAdmissionProofTests(unittest.TestCase):
 def selected(self,source):
  unit=build_program(source,'admission.py').main
  return requires_frames(unit,analyze(unit))

 def proved(self,identity,argument,*,unknown=False,unbound=False):
  source='f('+argument+')\n';unit=build_program(source,'proved_admission.py').main
  node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.GeneratorExp));call=unit.tree.body[0].value
  identities=Value(frozenset(identity),unknown=unknown,unbound=unbound)
  facts=SimpleNamespace(expressions={unit.ordinal(node):None},values={},calls={unit.ordinal(call):SimpleNamespace(identity=identities)})
  return requires_frames(unit,SimpleNamespace(scopes={0:facts}))

 def test_adapter_capabilities_match_actual_argument_position(self):
  checks=(
   ('itertools','product','(x for x in [1]),[2]',False),
   ('itertools','product','[2],(x for x in [1])',False),
   ('itertools','product','[2],repeat=(x for x in [1])',True),
   ('itertools','combinations','(x for x in [1]),1',False),
   ('itertools','combinations','[1],(x for x in [1])',True),
   ('itertools','combinations','iterable=(x for x in [1]),r=1',False),
   ('functools','reduce','int,(x for x in [1])',False),
   ('functools','reduce','(x for x in [1]),[]',True),
   ('functools','reduce','int,[],(x for x in [1])',True),
   ('functools','reduce','int,[],initial=(x for x in [1])',True),
   ('heapq','nlargest','1,(x for x in [1])',False),
   ('heapq','nlargest','1,iterable=(x for x in [1])',False),
   ('heapq','nlargest','(x for x in [1]),[]',True),
   ('heapq','nlargest','1,[],key=(x for x in [1])',True),
   ('heapq','heappush','[],(x for x in [1])',True),
   ('collections','Counter','(x for x in [1])',False),
   ('collections','Counter','word=(x for x in [1])',True),
   ('collections','defaultdict','int,(x for x in [1])',False),
   ('collections','defaultdict','(x for x in [1]),[]',True),
   ('collections','deque','(x for x in [1])',False),
   ('collections','deque','[],maxlen=(x for x in [1])',True),
  )
  for module,member,arguments,expected in checks:
   with self.subTest(module=module,member=member,arguments=arguments):
    self.assertEqual(self.proved([BuiltinRef(module,member)],arguments),expected)

 def test_unknown_mixed_dynamic_and_unproved_star_positions_remain_retained(self):
  eager=BuiltinRef('heapq','nlargest')
  self.assertTrue(self.proved([eager],'1,(x for x in [1])',unknown=True))
  self.assertTrue(self.proved([eager],'1,(x for x in [1])',unbound=True))
  self.assertTrue(self.proved([eager,BuiltinRef('heapq','heappush')],'1,(x for x in [1])'))
  self.assertTrue(self.proved([BuiltinRef('math','gcd')],'(x for x in [1]),1'))
  self.assertTrue(self.proved([BuiltinRef('itertools','not_a_member')],'(x for x in [1])'))
  self.assertTrue(self.proved([eager],'*(1,),(x for x in [1])'))
  self.assertFalse(self.proved([BuiltinIdentity('sum')],'(x for x in [1]),0'))
  self.assertTrue(self.proved([BuiltinIdentity('sum')],'[],(x for x in [1])'))
  self.assertTrue(self.proved([BuiltinIdentity('list')],'iterable=(x for x in [1])'))
  self.assertTrue(self.selected(CASES['source_shadow_has_no_eager_contract']))

 def test_real_canonical_heap_facts_use_iterable_only(self):
  self.assertFalse(self.selected('import heapq\nheapq.nlargest(1,(x for x in [1,2]))\n'))
  self.assertFalse(self.selected('from heapq import nsmallest\nchoose=nsmallest\nchoose(1,iterable=(x for x in [1,2]))\n'))
  self.assertTrue(self.selected('import heapq\nheapq.nlargest((x for x in [1]),[])\n'))
  self.assertTrue(self.selected('import heapq\nheapq.nlargest(1,[],key=(x for x in [1]))\n'))
  self.assertTrue(self.selected('import heapq\nitems=[]\nheapq.heappush(items,(x for x in [1]))\n'))

 def test_remaining_protocols_are_diagnosed_after_retained_admission(self):
  checks={
   'typed fallible heap comparison protocol':'import heapq\nitems=[]\nheapq.heappush(items,(x for x in [1]))\n',
   'callable-object protocol':'print(sorted([],key=(x for x in [1])))\n',
   'integer bounded-selection count':'import heapq\nprint(heapq.nlargest((x for x in [1]),[]))\n',
  }
  for expected,source in checks.items():
   with self.subTest(expected=expected):
    self.assertTrue(self.selected(source))
    result=transpile(source,TranspileOptions(license='none',filename='protocol_boundary.py'))
    self.assertFalse(result.success)
    self.assertIn(expected,str(result.diagnostics))
    self.assertTrue(all(d.code=='E006'and d.line>0 for d in result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class RetainedAdmissionExecutionTests(unittest.TestCase):
 cases=CASES
 check=iterator_tests.IteratorExecutionTests.check
 def test_shared_default_and_member_payloads(self):
  for name in ('shared_default_cursor','repeat_preserves_shared_payload','reduce_initial_keeps_generator_identity','builtin_next_default_keeps_generator'):
   with self.subTest(name=name):self.check(name)
 def test_non_eager_callbacks_and_argument_errors(self):
  for name in ('source_shadow_has_no_eager_contract','product_repeat_error_does_not_pull_body','noncallable_reduce_callback_zero_items','invalid_core_keyword_evaluates_creation_only'):
   with self.subTest(name=name):self.check(name)

 def test_crossmodule_generator_observes_its_own_module_live_bindings(self):
  library='''offset=3
def stream(values):return (offset+x for x in values)
def update(value):
 global offset
 offset=value
'''
  source='''import stream_helpers
offset=1000
first=stream_helpers.stream([1,2])
second=stream_helpers.stream([7,8])
stream_helpers.update(20)
print(next(first),next(second))
stream_helpers.update(40)
print(list(first),list(second),offset)
'''
  with tempfile.TemporaryDirectory(prefix='pytors-generator-module-')as directory:
   module=Path(directory,'stream_helpers.py');module.write_text(library)
   reference='import sys\nsys.path.insert(0,sys.argv[1])\n'+source
   cp=subprocess.run([sys.executable,'-I','-S','-c',reference,directory],capture_output=True,text=True,timeout=10)
   self.assertEqual(cp.returncode,0,cp.stderr)
   for mode in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
     result=transpile(source,TranspileOptions(integer=mode,filename=str(Path(directory,'main.py')),module_paths=(Path(directory),),license='none'))
    self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native')
    self.assertLess(len(result.rust_source.encode()),512*1024)
    rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021','--crate-name','generator_module',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(cp.returncode,cp.stdout,cp.stderr))
