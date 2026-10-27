"""Range containment and list self-alias fast paths retain Python protocols."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions,transpile

WRAPPER='import sys,gc\nexec(sys.argv[1])\n'

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ProtocolRangeAliasTests(unittest.TestCase):
    maxDiff=None
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-range-alias-');cls.addClassCleanup(cls.directory.cleanup)
        result=transpile(WRAPPER,TranspileOptions(optimize=False,integer='bigint'))
        if not result.success:raise AssertionError(result.diagnostics)
        path=Path(cls.directory.name)/'main.rs';path.write_text(result.rust_source,encoding='utf-8');cls.binary=path.with_suffix('')
        built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(cls.binary)],capture_output=True,text=True,timeout=150)
        if built.returncode:raise AssertionError(built.stderr)
    def compare(self,source,*,timeout=30):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,'-I','-c',WRAPPER,source],capture_output=True,text=True,timeout=timeout)
        actual=subprocess.run([str(self.binary),source],capture_output=True,text=True,timeout=timeout)
        self.assertEqual(expected.returncode,0,expected.stderr);self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
    def test_enormous_integer_range_membership_uses_exact_arithmetic(self):
        self.compare('''
            n=10**100
            for value in [-n,-n+1,0,1,2,3,n-1,n,n+1,True,False]:
                for current in [range(-n,n,3),range(n,-n,-7),range(n,n),range(-n,n)]:
                    print(value in current,value not in current)
            print(0.0 in range(n),True in range(n),False not in range(n))
        ''',timeout=5)
    def test_range_custom_equality_and_truth_callbacks_remain_queued(self):
        self.compare('''
            events=[]
            class Truth:
                def __bool__(self):events.append('truth');gc.collect();return True
            class Equal:
                def __eq__(self,other):events.append(('eq',other));return Truth()
            class Integer(int):
                def __eq__(self,other):events.append(('int eq',other));return other==2
            class Float(float):
                def __eq__(self,other):events.append(('float eq',other));return other==2
            for key in [Equal(),Integer(0),Float(0)]:
                events.clear();print(key in range(4),events)
            class Query:
                def __init__(self,remaining):self.remaining=remaining
                def __eq__(self,other):
                    if self.remaining==0:gc.collect();return True
                    return Query(self.remaining-1) in range(1)
            sys.setrecursionlimit(3000)
            print('finite',Query(300) in range(1))
            class Infinite:
                def __eq__(self,other):return self in range(1)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                try:Infinite() in range(1);result='unexpected return'
                except RecursionError:result='caught'
                print(limit,result)
        ''')
    def test_list_subclass_self_alias_skips_iteration_and_length(self):
        self.compare('''
            events=[]
            class List(list):
                def __iter__(self):events.append('iter');return iter([8])
                def __len__(self):events.append('len');return 9
            for method in ['operator','iadd','extend','bound']:
                value=List([1]);alias=value;events.clear()
                if method=='operator':value+=value;result=value
                elif method=='iadd':result=list.__iadd__(value,value)
                elif method=='extend':result=list.extend(value,value)
                else:result=value.__iadd__(value)
                print(method,value,value is alias,result is value,result is None,events)
            value=List([1]);events.clear();value+=List([2]);print(value,events)
            child=[];value=List([child]);value+=value;value[0].append(7)
            print(value,value[0]is value[1])
            value=[];value.append(value);value+=value
            print(value,value[0]is value,value[1]is value)
        ''')
    def test_empty_sort_storage_self_extension_does_not_invoke_callbacks(self):
        self.compare('''
            events=[]
            class List(list):
                def __iter__(self):events.append('iter');raise AssertionError('iter')
                def __len__(self):events.append('len');raise AssertionError('len')
            value=List([3,1,2])
            def key(item):
                value.extend(value);gc.collect();return item
            value.sort(key=key)
            print(value,events)
        ''')
