"""Native sequence lexicographic comparison suspends around Python callbacks."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER="import sys,gc\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ProtocolSequenceRecursionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="py2fastrust-sequence-protocol-")
        root=Path(cls.directory.name)
        result=transpile(WRAPPER,TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        source=root/"main.rs";source.write_text(result.rust_source,encoding="utf-8")
        cls.binary=root/"main"
        compiled=subprocess.run(["rustc","--edition=2021",str(source),"-o",str(cls.binary)],capture_output=True,text=True,timeout=120)
        if compiled.returncode:raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def compare(self,source):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,"-I","-c",WRAPPER],input=source,capture_output=True,text=True,timeout=45)
        actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=45)
        self.assertEqual(expected.returncode,0,expected.stderr)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)

    def test_recursive_element_equality_order_and_truth(self):
        self.compare('''
            calls=0
            class Equal:
                def __eq__(self,other):
                    global calls
                    calls+=1
                    return wrap([self])==wrap([other])
            class Order:
                def __eq__(self,other):return False
                def __lt__(self,other):
                    global calls
                    calls+=1
                    return wrap([self])<wrap([other])
            class Result:
                def __init__(self,left,right):self.left=left;self.right=right
                def __bool__(self):
                    global calls
                    calls+=1
                    return wrap([self.left])==wrap([self.right])
            class Truth:
                def __eq__(self,other):return Result(self,other)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for wrap in [list,tuple]:
                    for cls,op in [(Equal,'=='),(Order,'<'),(Truth,'==')]:
                        calls=0
                        try:eval('wrap([cls()])'+op+'wrap([cls()])')
                        except RecursionError:print(limit,wrap.__name__,cls.__name__,calls>0)
        ''')

    def test_finite_deep_and_cyclic_native_containers(self):
        self.compare('''
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for wrap in [list,tuple]:
                    left,right=0,1
                    for i in range(10):left=wrap([left]);right=wrap([right])
                    print(limit,wrap.__name__,left<right,left==right)
                    for i in range(limit*2):left=wrap([left]);right=wrap([right])
                    print('deep finite',left==right)
                left=[];right=[];left.append(left);right.append(right)
                print(left==left,left<left)
                for op in ['==','!=','<','<=','>','>=']:
                    try:eval('left'+op+'right')
                    except RecursionError:print('cycle caught',op)
        ''')

    def test_stateful_cyclic_prefix_can_converge(self):
        self.compare('''
            calls=0;left=[];right=[]
            class Element:
                def __eq__(self,other):
                    global calls
                    calls+=1
                    if calls==3:left[1]=right[1]
                    return True
            left.extend([Element(),left]);right.extend([Element(),right])
            print(left==right,calls)
            class Integer(int):pass
            left=[];right=[]
            left.extend([Integer(1),left]);right.extend([Integer(1),right])
            try:left==right
            except RecursionError:print('native subclass prefix cycle')
            calls=0
            class Recursive:
                def __eq__(self,other):
                    global calls
                    calls+=1
                    return True if calls==3 else [self]==[other]
            print([Recursive()]==[Recursive()],calls)
        ''')

    def test_mutation_after_false_equality_refetches_lengths_and_items(self):
        self.compare('''
            events=[]
            class Element:
                def __eq__(self,other):
                    events.append('eq')
                    if mutation=='replace':left[0]=10;right[0]=20
                    elif mutation=='clear':left.clear();right.clear()
                    elif mutation=='shorten':left.clear()
                    elif mutation=='grow':left.append(1)
                    gc.collect()
                    return False
                def __lt__(self,other):events.append('old lt');return 'LT'
                def __le__(self,other):events.append('old le');return 'LE'
                def __gt__(self,other):events.append('old gt');return 'GT'
                def __ge__(self,other):events.append('old ge');return 'GE'
            for op in ['==','!=','<','<=','>','>=']:
                for mutation in ['replace','clear','shorten','grow']:
                    events.clear();left=[Element()];right=[Element()]
                    print(op,mutation,eval('left'+op+'right'),events)
        ''')

    def test_truth_mutation_and_length_early_exit(self):
        self.compare('''
            events=[]
            class Result:
                def __bool__(self):
                    events.append('truth')
                    if mutation=='replace':left[0]=1;right[0]=2
                    elif mutation=='clear':left.clear();right.clear()
                    return False
            class Element:
                def __eq__(self,other):events.append('eq');return Result()
                def __lt__(self,other):events.append('old lt');return 'old'
            for mutation in ['replace','clear']:
                for op in ['==','!=','<','<=','>','>=']:
                    events.clear();left=[Element()];right=[Element()]
                    print(mutation,op,eval('left'+op+'right'),events)
            class Equal:
                def __eq__(self,other):events.append('eq');return True
            for wrap in [list,tuple]:
                for op in ['==','!=']:
                    events.clear();left=wrap([Equal()]);right=wrap([Equal(),2])
                    print(wrap.__name__,op,eval('left'+op+'right'),events)
            events.clear();left=[Equal(),1];right=[Equal(),2]
            print(left<right,events)
        ''')

    def test_identity_shortcut_nan_and_arbitrary_ordering_results(self):
        self.compare('''
            first=float('nan');second=float('nan')
            for wrap in [list,tuple]:
                for left,right in [(first,first),(first,second)]:
                    print(wrap.__name__,wrap([left])==wrap([right]),wrap([left])!=wrap([right]),wrap([left])<wrap([right]),wrap([left])<=wrap([right]))
            class Marker:
                def __bool__(self):raise RuntimeError('ordering must not convert truth')
            marker=Marker();events=[]
            class Element:
                def __eq__(self,other):events.append('eq');return False
                def __lt__(self,other):events.append('lt');return marker
            for wrap in [list,tuple]:
                events.clear();value=wrap([Element()])<wrap([Element()])
                print(value is marker,events)
            class Never:
                def __eq__(self,other):raise RuntimeError('identical elements skip equality')
            value=Never()
            print([value]==[value],(value,)==(value,),[value]<[value])
        ''')

    def test_pending_elements_and_native_subclass_owners_are_gc_roots(self):
        self.compare('''
            released=[]
            class Result:
                def __bool__(self):
                    gc.collect();print('truth alive',released)
                    return False
            class Element:
                def __init__(self,name):self.name=name
                def __eq__(self,other):
                    left.clear();right.clear();gc.collect()
                    print('eq alive',released)
                    return Result()
                def __del__(self):released.append(self.name)
            left=[Element('left')];right=[Element('right')]
            print(left==right);gc.collect();print(sorted(released))
            released.clear()
            class Item:
                def __eq__(self,other):gc.collect();print('owners alive',released);return True
            class Child(list):
                def __init__(self,value,name):super().__init__(value);self.name=name
                def __del__(self):released.append(self.name)
            print(Child([Item()],'left')==Child([Item()],'right'))
            gc.collect();print(sorted(released))
        ''')

    def test_scalar_subtype_reflection_and_sequence_override_precedence(self):
        self.compare('''
            events=[]
            class Integer(int):
                def __eq__(self,other):events.append('int eq');return NotImplemented
                def __lt__(self,other):events.append('int lt');return NotImplemented
            print([Integer(1)]==[1],[Integer(1)]<[2],events)
            events.clear()
            class Text(str):
                def __eq__(self,other):events.append('str eq');return NotImplemented
                def __gt__(self,other):events.append('str gt');return 'reflected'
            result=['a']<[Text('b')]
            print(result,events)
            class Override(list):
                def __eq__(self,other):return 'override'
            print(Override([1])==[2],[2]==Override([1]))
            class Tuple(tuple):pass
            print(Tuple([1,2])==(1,2),Tuple([1,2])<(1,3))
        ''')


if __name__=="__main__":unittest.main()
