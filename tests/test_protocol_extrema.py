"""Extrema and reduce keep lazy iteration and Python callbacks on the heap."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

WRAPPER = "import sys,gc,functools\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc required")
class ProtocolFoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-fold-protocol-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        build = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise AssertionError(build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=40)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=40)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_extrema_are_lazy_stable_and_validate_before_iteration(self):
        self.compare('''
            events=[]
            class Source:
                def __iter__(self):
                    events.append('iter')
                    for n in [3,1,2]:events.append(('next',n));yield n
                def __len__(self):raise AssertionError('extrema must not request a hint')
            def key(value):events.append(('key',value));gc.collect();return value
            for operation in [min,max]:
                events.clear();print(operation(Source(),key=key),events)
                events.clear()
                try:operation(Source(),unknown=1)
                except TypeError as error:print(str(error),events)
                first=(1,'a');second=(1,'b')
                print(operation(first,second,key=lambda x:x[0])is first)
                print(operation([],default=None),operation([],default=7,key=3))
                try:operation([])
                except ValueError as error:print(str(error))
                try:operation(1,2,default=3)
                except TypeError as error:print(str(error))
        ''')

    def test_reduce_initial_defaults_empty_and_callable_validation(self):
        self.compare('''
            print(functools.reduce(lambda a,b:a+b,[1,2,3]))
            print(functools.reduce(lambda a,b:a+b,[1,2,3],10))
            print(functools.reduce(lambda a,b:a+b,[1,2,3],initial=20))
            marker=object();print(functools.reduce(None,[],marker)is marker)
            print(functools.reduce(None,[3]))
            for operation in [lambda:functools.reduce(None,[]),lambda:functools.reduce(None,[1,2]),lambda:functools.reduce(None,[],1,initial=2),lambda:functools.reduce(None,[],initializer=3)]:
                try:operation()
                except TypeError as error:print(type(error).__name__,str(error))
            events=[]
            def source():
                for value in [1,2,3]:events.append(('next',value));yield value
            def combine(a,b):events.append(('call',a,b));gc.collect();return a+b
            print(functools.reduce(combine,source()),events)
        ''')

    def test_recursive_key_comparison_truth_iter_and_reduce_callbacks(self):
        self.compare('''
            def key(value):return min([value],key=key)
            def reduce(a,b):return functools.reduce(reduce,[a,b])
            class Item:
                def __lt__(self,other):return min(self,other)is self
            class Truth:
                def __bool__(self):return bool(max([1,2],key=lambda x:Compare()))
            class Compare:
                def __gt__(self,other):return Truth()
            class Source:
                def __iter__(self):return iter(min(self))
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('key',lambda:min([1],key=key)),('lt',lambda:min(Item(),Item())),('truth',lambda:max([1,2],key=lambda x:Compare())),('iter',lambda:min(Source())),('reduce',lambda:functools.reduce(reduce,[1,2]))]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
        ''')

    def test_callback_exceptions_cursor_and_live_accumulator_gc(self):
        self.compare('''
            def stop(*values):raise StopIteration(42)
            for operation in [lambda:min([1],key=stop),lambda:functools.reduce(stop,[1,2])]:
                try:operation()
                except StopIteration as error:print('callback stop',error.value)
            iterator=iter([3,2,1])
            def key(value):
                if value==2:raise LookupError('key failed')
                return value
            try:min(iterator,key=key)
            except LookupError as error:print(str(error),list(iterator))
            released=[]
            class Key:
                def __init__(self,n):self.n=n
                def __lt__(self,other):gc.collect();return self.n<other.n
                def __del__(self):released.append(self.n)
            class Item:
                def __init__(self,n):self.n=n
            def key(value):gc.collect();return Key(value.n)
            result=min((Item(n)for n in [3,1,2]),key=key)
            gc.collect();print(result.n,sorted(released))
            def combine(a,b):gc.collect();return Item(a.n+b.n)
            result=functools.reduce(combine,(Item(n)for n in [1,2,3]))
            gc.collect();print(result.n)
        ''')
