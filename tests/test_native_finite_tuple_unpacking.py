"""Finite fixed tuples retain their field positions across optional source flow."""
from pathlib import Path
import os,re,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions

CASES = [('nested_prepare_tuple_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run():\n'
  ' slots=[None]\n'
  ' def prepare():slots[0]=(3,Node(7))\n'
  ' prepare()\n'
  ' i,e=slots[0]\n'
  ' return i+e.value\n'
  'print(run())\n',
  ''),
 ('nested_optional_tuple_loop_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run(n):\n'
  ' slots=[None]*(n+1)\n'
  ' def prepare():\n'
  '  for i in range(n):slots[i]=(i+1,Node(i+4))\n'
  ' prepare()\n'
  ' v=0\n'
  ' answer=0\n'
  ' while slots[v] is not None:\n'
  '  u,e=slots[v]\n'
  '  answer+=e.value\n'
  '  v=u\n'
  ' return answer\n'
  'print(run(int(input())))\n',
  '0\n'),
 ('nested_optional_tuple_loop_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run(n):\n'
  ' slots=[None]*(n+1)\n'
  ' def prepare():\n'
  '  for i in range(n):slots[i]=(i+1,Node(i+4))\n'
  ' prepare()\n'
  ' v=0\n'
  ' answer=0\n'
  ' while slots[v] is not None:\n'
  '  u,e=slots[v]\n'
  '  answer+=e.value\n'
  '  v=u\n'
  ' return answer\n'
  'print(run(int(input())))\n',
  '1\n'),
 ('nested_optional_tuple_loop_2',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run(n):\n'
  ' slots=[None]*(n+1)\n'
  ' def prepare():\n'
  '  for i in range(n):slots[i]=(i+1,Node(i+4))\n'
  ' prepare()\n'
  ' v=0\n'
  ' answer=0\n'
  ' while slots[v] is not None:\n'
  '  u,e=slots[v]\n'
  '  answer+=e.value\n'
  '  v=u\n'
  ' return answer\n'
  'print(run(int(input())))\n',
  '5\n'),
 ('global_forward_tuple_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'slots=[None]\n'
  'def read():\n'
  ' prepare()\n'
  ' i,e=slots[0]\n'
  ' return e.value+i\n'
  'def prepare():slots[0]=(2,Node(8))\n'
  'print(read())\n',
  ''),
 ('class_prepare_tuple_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'class Graph:\n'
  ' def __init__(self):self.slots=[None]\n'
  ' def read(self):\n'
  '  self.prepare()\n'
  '  i,e=self.slots[0]\n'
  '  return e.value+i\n'
  ' def prepare(self):self.slots[0]=(3,Node(4))\n'
  'print(Graph().read())\n',
  ''),
 ('prepare_saved_alias_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run():\n'
  ' slots=[None]\n'
  ' def write():slots[0]=(8,Node(6))\n'
  ' saved=write\n'
  ' saved()\n'
  ' i,e=slots[0]\n'
  ' return e.value-i\n'
  'print(run())\n',
  ''),
 ('prepare_callback_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def invoke(fn):fn()\n'
  'def run():\n'
  ' slots=[None]\n'
  ' def write():slots[0]=(5,Node(2))\n'
  ' invoke(write)\n'
  ' i,e=slots[0]\n'
  ' return e.value+i\n'
  'print(run())\n',
  ''),
 ('second_attribute_after_prepare_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run():\n'
  ' slots=[None]\n'
  ' def write():slots[0]=(0,Node(3))\n'
  ' write()\n'
  ' i,e=slots[0]\n'
  ' e.value+=4\n'
  ' return e.value\n'
  'print(run())\n',
  ''),
 ('retained_tuple_on_error_branch_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run(flag):\n'
  ' slots=[None]\n'
  ' def write():\n'
  '  if flag:slots[0]=(1,Node(9))\n'
  ' write()\n'
  ' i,e=slots[0]\n'
  ' return e.value\n'
  'print(run(int(input())))\n',
  '0\n'),
 ('retained_tuple_on_error_branch_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run(flag):\n'
  ' slots=[None]\n'
  ' def write():\n'
  '  if flag:slots[0]=(1,Node(9))\n'
  ' write()\n'
  ' i,e=slots[0]\n'
  ' return e.value\n'
  'print(run(int(input())))\n',
  '1\n'),
 ('optional_tuple_positions_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else None\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '0\n'),
 ('optional_tuple_positions_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else None\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '1\n'),
 ('two_tuple_layouts_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else(5,Node(2))\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '0\n'),
 ('two_tuple_layouts_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else(5,Node(2))\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '1\n'),
 ('different_field_representations_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else("x",Node(2))\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '0\n'),
 ('different_field_representations_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else("x",Node(2))\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '1\n'),
 ('short_tuple_error_before_stores_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else(5,)\n'
  'print("before")\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '0\n'),
 ('short_tuple_error_before_stores_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else(5,)\n'
  'print("before")\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '1\n'),
 ('long_tuple_error_before_stores_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else(5,Node(2),9)\n'
  'print("before")\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '0\n'),
 ('long_tuple_error_before_stores_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else(5,Node(2),9)\n'
  'print("before")\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '1\n'),
 ('integer_noniterable_error_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else 9\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '0\n'),
 ('integer_noniterable_error_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else 9\n'
  'i,e=item\n'
  'print(i,e.value)\n',
  '1\n'),
 ('nested_target_positions_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,(2,Node(7)))if int(input())else None\n'
  'i,(j,e)=item\n'
  'print(i,j,e.value)\n',
  '0\n'),
 ('nested_target_positions_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,(2,Node(7)))if int(input())else None\n'
  'i,(j,e)=item\n'
  'print(i,j,e.value)\n',
  '1\n'),
 ('mutable_payload_sharing_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'a=[4]\n'
  'item=(a,Node(7))if int(input())else None\n'
  'values,e=item\n'
  'values.append(8)\n'
  'print(a,values is a,e.value)\n',
  '0\n'),
 ('mutable_payload_sharing_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'a=[4]\n'
  'item=(a,Node(7))if int(input())else None\n'
  'values,e=item\n'
  'values.append(8)\n'
  'print(a,values is a,e.value)\n',
  '1\n'),
 ('source_evaluated_once_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'events=[]\n'
  'def choose(flag):\n'
  ' events.append(1)\n'
  ' return(3,Node(7))if flag else None\n'
  'i,e=choose(int(input()))\n'
  'print(i,e.value,events)\n',
  '0\n'),
 ('source_evaluated_once_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'events=[]\n'
  'def choose(flag):\n'
  ' events.append(1)\n'
  ' return(3,Node(7))if flag else None\n'
  'i,e=choose(int(input()))\n'
  'print(i,e.value,events)\n',
  '1\n'),
 ('attribute_target_position_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'target=Node(8)\n'
  'item=(3,Node(7))if int(input())else None\n'
  'target.value,e=item\n'
  'print(target.value,e.value)\n',
  '0\n'),
 ('attribute_target_position_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'target=Node(8)\n'
  'item=(3,Node(7))if int(input())else None\n'
  'target.value,e=item\n'
  'print(target.value,e.value)\n',
  '1\n')]
def canonical_error(stderr):
    return [line for line in stderr.splitlines()if line.startswith(('Traceback (most recent call last):','  File ','During handling of the above exception, another exception occurred:'))or re.match(r'^[A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Iteration)(?::|$)',line)]


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FiniteTupleUnpackExecutionTests(unittest.TestCase):
    def exercise(self,source,stdin):
        with tempfile.TemporaryDirectory(prefix='pytors-finite-unpack-')as directory:
            root=Path(directory);main=root/'main.py';main.write_text(source)
            expected=subprocess.run([sys.executable,'-S',str(main)],input=stdin,capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with self.subTest(integer=mode):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy emitter entered')):
                        result=transpile(source,TranspileOptions(filename=str(main),integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','struct PegParser','UNICODE LICENSE V3'):
                        self.assertNotIn(marker,result.rust_source)
                    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        with self.subTest(optimized=optimized):
                            binary=root/(mode+('_release'if optimized else'_debug'))
                            build=subprocess.run(['rustc','--edition=2021','--crate-name','native_finite_tuple_unpack_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],input=stdin,capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                            self.assertEqual(actual.stdout,expected.stdout)
                            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                            self.assertEqual(canonical_error(actual.stderr),canonical_error(expected.stderr))


def _execution(source,stdin):
    def test(self):self.exercise(source,stdin)
    return test


for _name,_source,_stdin in CASES:
    setattr(FiniteTupleUnpackExecutionTests,'test_'+_name,_execution(_source,_stdin))
