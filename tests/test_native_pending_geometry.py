"""Keep pending tuple facts and real None alternatives distinct."""
import ast
from pathlib import Path
import os,shutil,subprocess,sys,tempfile,unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_pending_value_shapes import deferred
from py2fastrust.native_types import TupleType,ListType,NullableType,UnionType
from py2fastrust.native_classes import Cell,shape,InstanceType,Model
from py2fastrust.native_finite_tuple_unpacking import analyze


class PendingShapeContracts(unittest.TestCase):
    def test_real_none_is_complete_but_compiler_unknown_is_deferred(self):
        self.assertTrue(deferred(TupleType((None,'int'))))
        self.assertTrue(deferred(NullableType(TupleType(('int',None)))))
        self.assertFalse(deferred(TupleType(('none','int'))))
        self.assertFalse(deferred(NullableType(TupleType(('int','none')))))

    def test_mutable_leaf_keeps_existing_live_allocation_route(self):
        self.assertFalse(deferred(TupleType((None,ListType(None)))))
        self.assertFalse(deferred(ListType(None)))

    def test_nested_union_unpack_keeps_each_fixed_position(self):
        class M:
            def __init__(self):self.cells={}
            def cell(self,plan,node,identity=None):return self.cells.setdefault(identity,Cell())
            def contribute(self,destination,source,node):
                from py2fastrust.native_classes import merge
                if source.root().tag is not None:merge(destination,source,node,allow_unresolved=True)
        model=M();target=ast.parse('a,b,c=value').body[0].targets[0]
        item=Cell('object',('Point',))
        source=Cell('union',(Cell('none'),Cell('union',(Cell('tuple',(Cell('int'),item,item)),
                                                   Cell('tuple',(Cell('float'),item,item))))))
        bound=[]
        record=analyze(model,object(),target,source,{},bind_target=lambda node,value:bound.append((node.id,shape(value))))
        self.assertIsNotNone(record)
        self.assertEqual([kind for _,kind in bound[1:]],[InstanceType('Point'),InstanceType('Point')])
        self.assertEqual(len(record.variants),3)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PendingGeometryExecution(unittest.TestCase):
    def check_module(self,module,source,inputs):
        with tempfile.TemporaryDirectory(prefix='pytors-pending-geometry-')as temp:
            folder=Path(temp);(folder/'nodes.py').write_text(module)
            entry=folder/'driver.py';entry.write_text(source)
            expected=[subprocess.run([sys.executable,str(entry)],input=data,capture_output=True,timeout=5)for data in inputs]
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode,filename=str(entry),module_paths=(folder,)))
                self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                rust=folder/(mode+'.rs');rust.write_text(result.rust_source)
                for release in (False,True):
                    binary=folder/(mode+str(release))
                    build=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(rust),'-o',str(binary)],capture_output=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr.decode()[-6000:])
                    for data,reference in zip(inputs,expected):
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,timeout=5,
                                              env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
                        self.assertEqual(actual.stdout,reference.stdout,(mode,actual.stderr,reference.stderr))
                        self.assertEqual(actual.returncode,reference.returncode,(actual.stderr,reference.stderr))
                        if actual.returncode:self.assertEqual(actual.stderr.splitlines()[-1].split(b':')[0],reference.stderr.splitlines()[-1].split(b':')[0])

    def test_imported_nullable_result_keeps_distance_separate_from_points(self):
        module='''class Node:
    def __init__(self,x,y):self.x=x;self.y=y
    def __sub__(self,other):return Node(self.x-other.x,self.y-other.y)
    def norm(self):return self.x*self.x+self.y*self.y
    def distance(self):return self.norm()**0.5

def select(items):
    nodes=[Node(x,y) for x,y in items]
    n=len(nodes)
    if n==0:return None
    if n==1:return 0,nodes[0],nodes[0]
    return (nodes[0]-nodes[1]).distance(),nodes[0],nodes[1]
'''
        source='''from nodes import select
n=int(input())
items=[tuple(map(int,input().split())) for _ in range(n)]
a,p,q=select(items)
print(a,p.x,p.y,q.x,q.y)
'''
        self.check_module(module,source,[b'0\n',b'1\n2 5\n',b'2\n1 2\n4 6\n'])

    def test_pending_none_buffer_waits_for_imported_constructor(self):
        module='''class Node:
    def __init__(self,x,y):self.x=x;self.y=y
    def __sub__(self,other):return Node(self.x-other.x,self.y-other.y)
    def distance(self):return (self.x*self.x+self.y*self.y)**0.5

def select(items):
    nodes=[Node(x,y) for x,y in items]
    if len(nodes)==2:return (nodes[0]-nodes[1]).distance(),nodes[0],nodes[1]
    scratch=[None]*len(nodes)
    for i in range(len(nodes)):scratch[i]=nodes[i]
    for i in range(len(nodes)):nodes[i]=scratch[i]
    return (nodes[0]-nodes[-1]).distance(),nodes[0],nodes[-1]
'''
        source='''from nodes import select
n=int(input())
items=[tuple(map(int,input().split())) for _ in range(n)]
d,p,q=select(items)
print(d,p.x,p.y,q.x,q.y)
'''
        self.check_module(module,source,[b'2\n1 2\n4 6\n',b'3\n1 1\n3 3\n4 5\n'])

    def test_real_none_method_consumer_still_has_positioned_error(self):
        result=transpile('class A:\n def f(self):return None\na=A()\na.f().missing()\n',TranspileOptions(filename='actual_none.py'))
        self.assertFalse(result.success)
        message='\n'.join(map(str,result.diagnostics))
        self.assertIn('actual_none.py:4:',message);self.assertIn('missing',message)
