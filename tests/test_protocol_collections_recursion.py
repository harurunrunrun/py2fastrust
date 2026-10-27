"""Dictionary/set callbacks suspend without changing lookup or mutation order."""
from pathlib import Path
import shutil,subprocess,sys,tempfile,textwrap,unittest
from py2fastrust import TranspileOptions,transpile
WRAPPER='import sys,gc,functools\nexec(sys.stdin.read())\n'
@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ProtocolCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-collection-protocol-');root=Path(cls.directory.name)
        result=transpile(WRAPPER,TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        source=root/'main.rs';source.write_text(result.rust_source);cls.binary=root/'main'
        build=subprocess.run(['rustc','--edition=2021',str(source),'-o',str(cls.binary)],capture_output=True,text=True,timeout=120)
        if build.returncode:raise AssertionError(build.stderr)
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()
    def compare(self,source):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,'-I','-c',WRAPPER],input=source,capture_output=True,text=True,timeout=40)
        actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=40)
        self.assertEqual(expected.returncode,0,expected.stderr);self.assertEqual(actual.returncode,0,actual.stderr);self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
    def test_recursive_hash_literals_lookup_and_set_methods(self):
        self.compare('''
            class Key:
                def __init__(self,mode):self.mode=mode
                def __hash__(self):
                    if self.mode=='dict':return {self:1}[self]
                    if self.mode=='set':return hash(frozenset({self}))
                    if self.mode=='add':
                        values=set();values.add(self);return 1
                    if self.mode=='tuple':return hash((self,))
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for mode in ['dict','set','add','tuple']:
                    try:hash(Key(mode))
                    except RecursionError:print(limit,mode,'caught')
        ''')
    def test_lookup_equal_truth_original_keys_and_mutation_restart(self):
        self.compare('''
            events=[]
            class Result:
                def __bool__(self):events.append('truth');gc.collect();return True
            class Key:
                def __init__(self,label):self.label=label
                def __hash__(self):events.append(('hash',self.label));gc.collect();return 7
                def __eq__(self,other):events.append(('eq',self.label,other.label));gc.collect();return Result()
            first=Key('first');second=Key('second');d={first:1}
            print(d[second],d.get(second),d.setdefault(second,3));d[second]=4
            print(next(iter(d)) is first,d[second],len(d));print(events)
            events.clear();print(d.pop(second));print(len(d));print(events)
            class Changing:
                def __hash__(self):return 1
                def __eq__(self,other):
                    if len(table)==1:table['added']=2
                    return True
            key=Changing();table={key:1};print(table[object_key] if False else table[Changing()],len(table))
        ''')
    def test_recursive_comparison_methods_and_contains(self):
        self.compare('''
            class Equal:
                def __eq__(self,other):return [self].count(other)>0
            class Key:
                def __hash__(self):return 1
                def __eq__(self,other):return table[other]
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                try:[Equal()].index(Equal())
                except RecursionError:print(limit,'list caught')
                table={Key():1}
                try:table[Key()]
                except RecursionError:print(limit,'dict caught')
        ''')
    def test_partial_literal_effects_and_callback_exception_scope(self):
        self.compare('''
            events=[]
            class Key:
                def __init__(self,n):self.n=n
                def __hash__(self):
                    events.append(('hash',self.n))
                    if self.n==2:raise LookupError('hash failure')
                    return 1
                def __eq__(self,other):events.append(('eq',self.n,other.n));return False
            try:result={Key(1):'one',Key(2):'two',Key(3):'three'}
            except LookupError as error:print(str(error),events)
            events.clear();d={Key(1):'one'}
            try:d[Key(2)]='two'
            except LookupError:print(len(d),events)
            class Missing(dict):
                def __missing__(self,key):gc.collect();return ('missing',key)
            m=Missing();print(m['x'],m.get('x'),len(m))
        ''')
    def test_constructor_update_iteration_callbacks_and_pair_consumption(self):
        self.compare('''
            class Source:
                def __iter__(self):return iter(dict(self))
            class SetSource:
                def __iter__(self):return iter(set(self))
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,source,operation in [('dict',Source(),dict),('set',SetSource(),set),('update',Source(),{}.update)]:
                    try:operation(source)
                    except RecursionError:print(limit,label,'caught')
            events=[]
            def pairs():
                events.append('first');yield ['x',1]
                events.append('second');yield ['bad',2,3,4]
                events.append('unreachable')
            target={}
            try:target.update(pairs())
            except ValueError as error:print(str(error),target,events)
            events=[]
            class Mapping:
                def keys(self):events.append('keys');return iter(['a','b'])
                def __getitem__(self,key):events.append(('get',key));gc.collect();return key+'!'
            print(dict(Mapping(),after=3),events)
        ''')
    def test_contains_and_native_method_hash_callback_routes(self):
        self.compare('''
            class Key:
                def __hash__(self):return hash(self)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('get',lambda:{}[Key()]),('contains',lambda:Key() in {}),('setcontains',lambda:Key() in set()),('setdefault',lambda:{}.setdefault(Key(),1)),('update',lambda:{}.update([(Key(),1)]))]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
            class Item:
                def __eq__(self,other):return other in [self]
            try:Item() in [Item()]
            except RecursionError:print('list contains caught')
            frozen=frozenset({1,2});print({1,2} in {frozen});values={frozen};values.remove({1,2});print(values)
        ''')
    def test_copy_reuses_entry_hash_and_exact_frozen_identity(self):
        self.compare('''
            events=[]
            class Key:
                def __hash__(self):events.append('hash');return 7
            key=Key();d={key:1};s={key};f=frozenset(s);events.clear()
            copied=dict(d);updated={};updated.update(d);s2=set(s);s3=set();s3.update(s);f2=frozenset(s)
            print(events,len(copied),len(updated),len(s2),len(s3),len(f2),frozenset(f) is f)
            class S(set):
                def __iter__(self):raise RuntimeError('iter override')
            print(set(S([1,2]))=={1,2})
        ''')
    def test_keyerror_creation_does_not_eagerly_call_key_repr(self):
        self.compare('''
            events=[]
            class Key:
                def __hash__(self):return 7
                def __repr__(self):events.append('repr');return 'key'
            key=Key()
            try:{}[key]
            except KeyError as error:print(events,error.args[0] is key);print(str(error),events)
        ''')
    def test_recursive_dictionary_values_and_set_equality_lookup(self):
        self.compare('''
            class Equal:
                def __eq__(self,other):return {1:self}=={1:other}
            class Key:
                def __hash__(self):return 1
                def __eq__(self,other):return {self}=={other}
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('dict',lambda:{1:Equal()}=={1:Equal()}),('set',lambda:{Key()}<={Key()})]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
            nan=float('nan');print({1:nan}=={1:nan},{1:nan}=={1:float('nan')})
            class Truth:
                def __bool__(self):gc.collect();return True
            class Value:
                def __eq__(self,other):gc.collect();return Truth()
            print({1:Value()}=={1:Value()},{1:Value()}!={1:Value()})
        ''')
    def test_list_tuple_and_truth_consumers_queue_callbacks(self):
        self.compare('''
            class Source:
                def __init__(self,mode):self.mode=mode
                def __iter__(self):return iter(list(self) if self.mode=='list' else tuple(self))
            class Truth:
                def __init__(self,mode):self.mode=mode
                def __bool__(self):return any([self]) if self.mode=='any' else all([self])
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for mode in ['list','tuple']:
                    try:list(Source(mode))
                    except RecursionError:print(limit,mode,'caught')
                for mode in ['any','all']:
                    try:bool(Truth(mode))
                    except RecursionError:print(limit,mode,'caught')
        ''')
    def test_list_length_hints_partial_extend_and_self_extension(self):
        self.compare('''
            events=[]
            class Source:
                def __iter__(self):events.append('iter');return iter([1,2])
                def __len__(self):events.append('len');raise TypeError('ignored length')
                def __length_hint__(self):events.append('hint');gc.collect();return 3
            print(list(Source()),events);events.clear();print(tuple(Source()),events)
            values=[0]
            def source():
                gc.collect();yield 1;gc.collect();yield 2;raise LookupError('partial')
            try:values.extend(source())
            except LookupError:print(values)
            values.extend(values);print(values)
            value=(1,2);print(tuple(value) is value)
            class Hint:
                def __iter__(self):return iter([])
                def __length_hint__(self):return -1
            try:list(Hint())
            except ValueError:print('negative hint caught')
        ''')

    def test_native_iterator_hints_sticky_exhaustion_and_source_release(self):
        self.compare('''
            values=[1,2];iterator=iter(values)
            print(iterator.__length_hint__(),next(iterator),iterator.__length_hint__())
            values.append(3);print(iterator.__length_hint__(),list(iterator),iterator.__length_hint__())
            values.append(4);print(next(iterator,None),iterator.__length_hint__())
            for source in [('a','b'),'雪x',b'xy',range(2,8,2)]:
                iterator=iter(source);print(iterator.__length_hint__(),next(iterator),iterator.__length_hint__());print(list(iterator),iterator.__length_hint__())
            events=[]
            class L(list):
                def __del__(self):events.append('released')
            source=L([1]);iterator=iter(source);del source;gc.collect();print(events)
            print(next(iterator),next(iterator,None));gc.collect();print(events)
        ''')

    def test_contains_binding_failure_falls_back_but_body_errors_propagate(self):
        self.compare('''
            events=[]
            class Broken:
                def __get__(self,owner,cls):events.append('bind');gc.collect();raise AttributeError('binding')
            class Iterable:
                __contains__=Broken()
                def __iter__(self):events.append('iter');gc.collect();return iter([1,2])
            value=Iterable();print(2 in value,3 not in value,events)
            class Body:
                def __contains__(self,key):raise AttributeError('body')
                def __iter__(self):raise AssertionError('body error must propagate')
            try:1 in Body()
            except AttributeError as error:print(str(error))
            class NotIterable:__contains__=Broken()
            try:1 in NotIterable()
            except TypeError:print('not iterable')
        ''')
