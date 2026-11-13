"""Fixed tuple payloads retain every direct class edge during trial deletion."""
from pathlib import Path
import shutil,subprocess,tempfile,unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_class_gc import supported_field,_trace,RUNTIME
from py2fastrust.native_classes import InstanceType
from py2fastrust.native_aot_callables import AotFunctionType
from py2fastrust.native_types import TupleType,TupleSequenceType,ListType,NullableType,union_type,NamedTupleType
import test_native_module_linking as support

CASES={
'numeric_tuple_beside_self_cycle':'''class Node:
 def __init__(self,n):self.payload=(n,n+1);self.link=None
node=Node(3)
node.link=node
print(node.payload,node.link.payload,node.link is node)
''',
'nested_builtin_tuple_payload':'''class Node:
 def __init__(self,n):
  self.payload=(n,('label',b'bytes',True,None),(1.5,()))
  self.link=None
node=Node(3)
node.link=node
print(node.payload,node.link is node)
''',
'finite_tuple_scalar_payloads':'''class Node:
 def __init__(self,n):self.payload=(n,n+1);self.link=None
node=Node(3)
node.link=node
for payload in [(7,8),None,9,('text',2)]:
 node.payload=payload
 print(node.payload,node.link is node)
''',
'class_edges_inside_tuple':'''class Node:
 def __init__(self,n):self.n=n;self.links=(None,None)
a=Node(3)
b=Node(7)
a.links=(b,b)
b.links=(a,None)
print(a.links[0].n,a.links[1] is b,b.links[0] is a)
''',
'nested_tuple_duplicate_self_edges':'''class Node:
 def __init__(self,n):self.n=n;self.links=(None,(None,0))
node=Node(3)
node.links=(node,(node,7))
print(node.links[0] is node,node.links[1][0].n,node.links[1][1])
''',
'external_tuple_roots_among_garbage':'''class Node:
 def __init__(self,n):self.n=n;self.links=(None,None)
a=Node(3)
b=Node(7)
a.links=(b,b)
b.links=(a,None)
keep=(a.links[0],b.links[0])
del a
del b
for i in range(400):
 node=Node(i)
 node.links=(node,node)
print(keep[0].n,keep[1].n,keep[0].links[0] is keep[1])
''',
'captured_tuple_roots_among_garbage':'''class Node:
 def __init__(self,n):self.n=n;self.links=(None,None)
def make():
 a=Node(3)
 b=Node(7)
 a.links=(b,b)
 b.links=(a,None)
 keep=(a,b)
 def read():return keep[0].n+keep[1].n
 return read
read=make()
for i in range(400):
 node=Node(i)
 node.links=(node,node)
print(read(),read())
''',
'mutual_classes_with_tuple_payload':'''class Left:
 def __init__(self):self.payload=(1,2);self.links=(None,)
class Right:
 def __init__(self):self.payload=(3,4);self.links=(None,)
a=Left()
b=Right()
a.links=(b,)
b.links=(a,)
print(a.links[0].payload,b.links[0].payload,a.links[0].links[0] is a)
''',
'sealed_named_tuple_payload':'''from typing import NamedTuple
class Pair(NamedTuple):
 left:int
 right:int
class Node:
 def __init__(self,n):self.payload=Pair(n,n+1);self.link=None
node=Node(3)
node.link=node
print(node.payload.left,node.payload.right,node.link is node)
''',
}

class TupleGcExecutionTests(unittest.TestCase):
 exercise=support.NativeLinkedModuleTests.exercise

for _name,_source in CASES.items():
 def _test(self,source=_source):self.exercise({'main.py':source})
 setattr(TupleGcExecutionTests,'test_'+_name,_test)

class TupleGcAdmissionTests(unittest.TestCase):
 def test_recursive_payload_capability_keeps_shared_and_callback_boundaries(self):
  node=InstanceType('Node')
  for kind in (TupleType(()),TupleType(('int','int')),TupleType((node,TupleType(('bytes',NullableType(node))))),union_type('none',TupleType(('str',node)))):
   self.assertTrue(supported_field(kind),kind)
  for kind in (ListType(node),TupleSequenceType(node),TupleType((ListType(node),)),TupleType((TupleSequenceType('int'),)),TupleType((AotFunctionType((1,)),))):
   self.assertFalse(supported_field(kind),kind)
 def test_mutable_callback_and_finalizer_payloads_remain_positioned(self):
  cases=(
   'class Node:\n def __init__(self):self.payload=([],);self.link=None\na=Node()\na.link=a\nprint(a.link is a)\n',
   'class Node:\n def __init__(self):self.link=None\na=Node()\na.link=a\na.payload=tuple([a,a])\nprint(a.link is a)\n',
   'class Node:\n def __init__(self):self.link=None\na=Node()\na.link=a\na.payload=(lambda:a,)\nprint(a.link is a)\n',
   'class Node:\n def __init__(self):self.payload=(1,2);self.link=self\n def __del__(self):print("destroyed")\na=Node()\n',
  )
  for source in cases:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none',filename='gc_tuple_boundary.py'))
    self.assertFalse(result.success)
    self.assertGreater(result.diagnostics[0].line,0)
    self.assertTrue(any('cycle'in item.message or '__del__'in item.message for item in result.diagnostics),result.diagnostics)
 def test_scalar_tuples_do_not_invent_class_edges(self):
  self.assertEqual(_trace(TupleType(('int',TupleType(('str','bytes')))),'value',{'Node'}),'()')

class TupleGcKernelTests(unittest.TestCase):
 @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
 def test_generated_tuple_traces_reclaim_only_unrooted_physical_edges(self):
  node=InstanceType('Node')
  kind=TupleType((NullableType(node),TupleType((NullableType(node),'int'))))
  trace=_trace(kind,'(*value)',{'Node'})
  fixture=Path(__file__).with_name('native_class_gc_tuple_kernel.rs').read_text()
  source=RUNTIME+'\n'+fixture.replace('/* GENERATED_TUPLE_TRACE */',trace)
  with tempfile.TemporaryDirectory(prefix='pytors-tuple-gc-kernel-')as directory:
   path=Path(directory)/'kernel.rs';path.write_text(source)
   for optimized in (False,True):
    binary=Path(directory)/('release'if optimized else'debug')
    build=subprocess.run(['rustc','--edition=2021','--test',*(['-O']if optimized else[]),str(path),'-o',str(binary)],text=True,capture_output=True,timeout=90)
    self.assertEqual(build.returncode,0,build.stderr)
    run=subprocess.run([str(binary),'--test-threads=1'],text=True,capture_output=True,timeout=30)
    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    self.assertIn('4 passed; 0 failed',run.stdout)

if __name__=='__main__':unittest.main()
