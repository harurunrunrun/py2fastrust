"""Owned starred remainders and unpack snapshots preserve Python values."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_owned_local_lists as places
import test_native_class_iterators as support


def program(body):
 return 'class Marker:pass\ndef main():\n'+''.join(' '+line+'\n' for line in body.splitlines())+'main()\n'


CASES={
 'dynamic_lengths':(program('head,*tail=map(int,input().split())\na,b=tail\nprint(head,a,b)'),
                    ('1 2 3\n','1 2\n','1 2 3 4\n','\n','bad 2 3\n','1 2 bad\n')),
 'zero_trip_unbound':(program('n=int(input())\nfor _ in range(n):\n head,*tail=map(int,input().split())\na,b=tail\nprint(a,b)'),
                     ('0\n','1\n1 2 3\n')),
 'zero_trip_initial_value':(program('tail=[99,100]\nn=int(input())\nfor _ in range(n):\n head,*tail=map(int,input().split())\na,b=tail\nprint(a,b)'),
                          ('0\n','1\n1 2 3\n','2\n1 2 3\n4 5 6\n')),
 'consumer_stores_into_source':(program('head,*tail=map(int,input().split())\ntail[1],tail[0]=tail\nprint(head,tail[0],tail[1])'),('1 2 3\n',)),
 'empty_unpack':(program('head,*tail=iter([7])\n[]=tail\nprint(head)'),('',)),
 'mutable_iteration':(program('head,*tail=iter(range(5))\ntotal=0\nfor value in tail:\n total+=value\n if value==2:tail.append(8)\nprint(head,total,len(tail),tail[-1])'),('',)),
 'shared_child_identity':(program('first=[1]\nsecond=[2]\nthird=[3]\nhead,*tail=iter([first,second,third])\na,b=tail\na.append(4)\nprint(second,a is second,b is third)'),('',)),
 'heterogeneous_elements':(program('head,*tail=iter([0,1,"two"])\na,b=tail\nprint(head,a,b)'),('',)),
 'alias_retains_shared_list':(program('head,*tail=map(int,input().split())\nalias=tail\ntail.append(4)\na,b,c=alias\nprint(tail is alias,a,b,c)'),('1 2 3\n',)),
 'mixed_variable_kinds':(program('tail="before"\nn=int(input())\nfor _ in range(n):\n head,*tail=map(int,input().split())\nprint(tail)'),('0\n','1\n1 2 3\n')),
 'target_effects':('''bucket=[0]
def place():
 print('target')
 return bucket
class Marker:pass
def main():
 place()[0],*tail=map(int,input().split())
 a,b=tail
 print(bucket,a,b)
main()
''',('1 2 3\n','1 2\n','1 bad 3\n')),
 'large_unpack':(program('head,*tail=iter(range(34))\n'+','.join('v'+str(i) for i in range(33))+'=tail\nprint(head,v0,v32)'),('',)),
}


class OwnedStarVectorProofs(unittest.TestCase):
 def inspect(self,name,mode='i64'):
  observed=[];original=places.prepare
  def prepare(emitter):
   before=ast.dump(emitter.model.unit.tree,include_attributes=True)
   result=original(emitter)
   self.assertEqual(before,ast.dump(emitter.model.unit.tree,include_attributes=True))
   observed.extend((emitter,local) for local in result.values() if local.binding[1]=='tail')
   return result
  with patch.object(places,'prepare',prepare):
   result=transpile(CASES[name][0],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  actual=[(emitter,local) for emitter,local in observed if local.name in emitter.owned_local_lists]
  return result,actual

 def test_nonescaping_starred_bindings_have_native_vector_slots(self):
  for mode in ('i64','i128','bigint'):
   for name in ('dynamic_lengths','consumer_stores_into_source','zero_trip_unbound','heterogeneous_elements'):
    with self.subTest(mode=mode,name=name):
     result,observed=self.inspect(name,mode)
     self.assertTrue(observed)
     for emitter,local in observed:
      self.assertIn(f'{emitter.slot(local.name,local.kind)}:Option<Vec<{emitter.rust_type(local.kind.element)}>>',result.rust_source)

 def test_aliases_and_kind_changes_keep_the_existing_value_representation(self):
  for name in ('alias_retains_shared_list','mixed_variable_kinds'):
   with self.subTest(name=name):
    _,observed=self.inspect(name)
    self.assertFalse(observed)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class OwnedStarVectorExecution(unittest.TestCase):
 def exercise(self,name):
  source,inputs=CASES[name];filename='owned_star.py'
  references=[subprocess.run([sys.executable,'-I','-S','-c',support.REFERENCE,source,filename],input=data,
               text=True,capture_output=True,timeout=15) for data in inputs]
  with tempfile.TemporaryDirectory(prefix='pytors-owned-star-') as directory:
   root=Path(directory)
   for mode in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy generation entered')):
     result=transpile(source,TranspileOptions(filename=filename,integer=mode,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    self.assertEqual(result.backend,'native')
    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=root/(mode+str(optimized))
     built=subprocess.run(['rustc','--edition=2021','--crate-name','owned_star',*(['-O'] if optimized else []),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
     self.assertEqual(built.returncode,0,built.stderr)
     for data,expected in zip(inputs,references):
      with self.subTest(mode=mode,optimized=optimized,input=data):
       actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=15,
                env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
       self.assertEqual((actual.stdout,actual.returncode),(expected.stdout,expected.returncode),actual.stderr)
       if expected.returncode:
        error=json.loads(expected.stderr)
        self.assertEqual(actual.stderr.splitlines()[-1],error['message'])
        self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(row) for row in error['frames']])
       else:self.assertEqual(actual.stderr,'')


def runtime_case(name):
 def test(self):self.exercise(name)
 return test
for _name in CASES:
 setattr(OwnedStarVectorExecution,'test_'+_name,runtime_case(_name))
