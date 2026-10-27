"""Bulk set consumers suspend hashing, equality, truth and iterator callbacks."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

WRAPPER = "import sys,gc\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc required")
class ProtocolSetOperationTests(unittest.TestCase):
    maxDiff = None
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-set-operation-")
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

    def test_methods_native_iterable_multiple_sources_and_frozen_results(self):
        self.compare('''
            for factory in [set,frozenset]:
                values=factory([1,2,3])
                for name in ['union','intersection','difference','symmetric_difference']:
                    for source in [[2,4],{2,4},frozenset([2,4])]:
                        result=getattr(values,name)(source)
                        print(factory.__name__,name,sorted(result),type(result).__name__)
                for name in ['issubset','issuperset','isdisjoint']:
                    print(name,*[getattr(values,name)(source)for source in [[],[1,2],[1,2,3,4],{1,2,3},[7]]])
                print(sorted(values.union([4],[5])),sorted(values.intersection([2,3],[1,3])),sorted(values.difference([1],[3])))
            for name in ['difference_update','intersection_update','symmetric_difference_update']:
                values={1,2,3};print(name,getattr(values,name)([2,4]),sorted(values))
            for name in ['intersection','difference','symmetric_difference','issubset','issuperset','isdisjoint','difference_update','intersection_update','symmetric_difference_update']:
                values={frozenset({1})}
                try:getattr(values,name)([{1}])
                except TypeError:print(name,'unhashable')
        ''')

    def test_stored_hashes_key_identity_and_equality_direction(self):
        self.compare('''
            events=[]
            class Key:
                def __init__(self,n):self.n=n
                def __hash__(self):events.append(('hash',self.n));gc.collect();return 1
                def __eq__(self,other):events.append(('eq',self.n,other.n));gc.collect();return True
            for name in ['intersection','difference','symmetric_difference','union','issubset','issuperset','isdisjoint','intersection_update','difference_update','symmetric_difference_update']:
                for native in [False,True]:
                    a={Key('left')};b=[Key('right')]
                    if native:b=set(b)
                    events.clear();result=getattr(a,name)(b)
                    print(name,native,events,[key.n for key in sorted(a if result is None else result,key=lambda x:x.n)] if not isinstance(result,bool)else result)
        ''')

    def test_partial_difference_and_atomic_intersection_on_iterator_failure(self):
        self.compare('''
            for name in ['difference_update','intersection_update','symmetric_difference_update']:
                values={1,2,3};events=[]
                def first():events.append(('first',sorted(values)));yield 1
                def second():events.append(('second',sorted(values)));raise LookupError('source failed');yield 2
                try:
                    if name=='symmetric_difference_update':getattr(values,name)(second())
                    else:getattr(values,name)(first(),second())
                except LookupError as error:print(name,str(error),sorted(values),events)
            events=[]
            def source():
                for value in [1,2,3,4]:events.append(value);yield value
            for name in ['intersection','issubset','issuperset','isdisjoint']:
                events.clear();result=getattr({1,2},name)(source());print(name,sorted(result)if isinstance(result,set)else result,events)
        ''')

    def test_recursive_iterator_hash_and_equality_callbacks(self):
        self.compare('''
            names=['union','intersection','difference','symmetric_difference','issubset','issuperset','isdisjoint','difference_update','intersection_update','symmetric_difference_update']
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for name in names:
                    class Source:
                        def __iter__(self):getattr({1},name)(self);return iter([])
                    try:getattr({1},name)(Source())
                    except RecursionError:print(limit,name,'iter caught')
                for name in ['intersection','difference','symmetric_difference','issubset','issuperset','isdisjoint']:
                    class Key:
                        def __hash__(self):return 1
                        def __eq__(self,other):return bool(getattr(table,name)([other]))
                    left=Key();right=Key();table={left}
                    try:getattr(table,name)([right])
                    except RecursionError:print(limit,name,'eq caught')
                class Key:
                    def __hash__(self):
                        if armed:return len(table.intersection([self]))
                        return 1
                armed=False;key=Key();table={key};armed=True
                try:table.intersection([key])
                except RecursionError:print(limit,'hash caught')
        ''')

    def test_native_copies_skip_equality_and_binary_operators_queue_callbacks(self):
        self.compare('''
            events=[]
            class Key:
                def __init__(self,n):self.n=n
                def __hash__(self):events.append('hash');return 1
                def __eq__(self,other):events.append('eq');return self is other
            values={Key(1),Key(2)};events.clear()
            a=set(values);b=frozenset(values);values.update(values);c=set().union(values)
            print(events,len(a),len(b),len(c))
            for factory in [set,frozenset]:
                for expression in ['left|right','left&right','left-right','left^right']:
                    left=factory([1,2]);right=frozenset([2,3]);result=eval(expression)
                    print(expression,type(result).__name__,sorted(result))
                for statement in ['left|=right','left&=right','left-=right','left^=right']:
                    left=factory([1,2]);right={2,3};scope={'left':left,'right':right}
                    exec(statement,scope);result=scope['left']
                    print(statement,type(result).__name__,sorted(result),result is left)
            class Recursive:
                def __hash__(self):return 1
                def __eq__(self,other):return bool(left&right)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                left={Recursive()};right={Recursive()}
                try:left&right
                except RecursionError:print(limit,'binary caught')
            class S(set):pass
            left=S([1,2]);right=S([2,3])
            print(type(left|right).__name__,sorted(left|right));left|=right;print(type(left).__name__,sorted(left))
            for cls in [set,frozenset]:
                for name in ['__or__','__ror__','__and__','__rand__','__sub__','__rsub__','__xor__','__rxor__']:
                    result=getattr(cls,name)(cls([1,2]),{2,3});print(cls.__name__,name,type(result).__name__,sorted(result))
        ''')

    def test_stream_intersection_observes_owner_growth_in_equality_callback(self):
        self.compare('''
            class Key:
                def __hash__(self):return 1
                def __eq__(self,other):
                    table.add(2)
                    gc.collect();return True
            for name in ['intersection','issubset','intersection_update']:
                left=Key();right=Key();table={left};seen=[]
                def source():
                    for value in [right,2,3]:seen.append(1);yield value
                result=getattr(table,name)(source())
                if isinstance(result,bool):print(name,result,len(table),len(seen))
                else:print(name,len(table if result is None else result),len(table),len(seen))
        ''')

    def test_items_and_values_views_queue_hash_equality_and_native_methods(self):
        self.compare('''
            class Key:
                def __hash__(self):return int((self,1)in items)
            items={}.items()
            class Equal:
                def __eq__(self,other):return other in values
            values={'x':Equal()}.values();query=object()
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('items',lambda:(Key(),1)in items),('items method',lambda:items.__contains__((Key(),1))),('values',lambda:query in values)]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
            print(hasattr(values,'__contains__'))
            events=[]
            class Result:
                def __bool__(self):events.append('truth');gc.collect();return True
            class Value:
                def __eq__(self,other):events.append('eq');gc.collect();return Result()
            view={'x':Value()}.items()
            print(('x',object())in view,events)
            proxy={}.keys().mapping
            for operation in [lambda:proxy.__setitem__('x',1),lambda:proxy.__delitem__('x')]:
                try:operation()
                except AttributeError:print('readonly method absent')
        ''')

    def test_all_integer_modes_debug_release_standalone_protocol_paths(self):
        source=textwrap.dedent('''
            import gc,functools
            class Key:
                def __init__(self,n):self.n=n
                def __hash__(self):gc.collect();return self.n
                def __eq__(self,other):gc.collect();return self.n==other.n
                def __lt__(self,other):gc.collect();return self.n<other.n
            left={Key(1),Key(2)};right={Key(2),Key(3)}
            print(sorted(key.n for key in left|right),sorted(key.n for key in left&right))
            left.symmetric_difference_update(right);print(sorted(key.n for key in left))
            values=[Key(3),Key(1),Key(2)];seen=[]
            def key(value):seen.append(len(values));gc.collect();return value.n
            values.sort(key=key,reverse=True)
            print([value.n for value in values],seen,min(values,key=key).n,max(values,key=key).n)
            print(functools.reduce(lambda a,b:a+b,[1,2,3],initial=4))
            view={'x':Key(2)}.items();print(('x',Key(2))in view)
            class Missing:
                def __get__(self,owner,cls):gc.collect();raise AttributeError('binding')
            class Iterable:
                __contains__=Missing()
                def __iter__(self):return iter([1,2])
            print(2 in Iterable(),3 not in Iterable())
        ''')
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=20)
        self.assertEqual(expected.returncode,0,expected.stderr)
        compiler=shutil.which('rustc')
        for mode in ['i64','i128','bigint']:
            result=transpile(source,TranspileOptions(integer=mode,optimize=False))
            self.assertTrue(result.success,result.diagnostics)
            path=Path(self.directory.name)/(mode+'-standalone.rs');path.write_text(result.rust_source)
            for optimized in [False,True]:
                with self.subTest(integer=mode,optimized=optimized):
                    binary=path.with_suffix('.release'if optimized else'.debug')
                    command=[compiler,'--edition=2021',str(path),'-o',str(binary)]
                    if optimized:command.append('-O')
                    build=subprocess.run(command,capture_output=True,text=True,timeout=150)
                    self.assertEqual(build.returncode,0,build.stderr)
                    environment=os.environ.copy();environment['PATH']='/nonexistent'
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,env=environment,timeout=20)
                    self.assertEqual(actual.returncode,0,actual.stderr)
                    self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
