"""Immutable sets share cached hashes and Python's set protocols."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from py2fastrust import TranspileOptions,transpile

WRAPPER='''import sys
static=frozenset([1,2])
def aot_union(value):return static|value
exec(sys.stdin.read())
'''
@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrozenSetTests(unittest.TestCase):
    maxDiff=None
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='py2fastrust-frozen-')
        cls.addClassCleanup(cls.directory.cleanup)
        root=Path(cls.directory.name)
        result=transpile(WRAPPER,TranspileOptions(optimize=False,filename='frozen_wrapper.py'))
        if not result.success:raise AssertionError('\n'.join(map(str,result.diagnostics)))
        target=root/'main.rs';target.write_text(result.rust_source,encoding='utf-8');cls.binary=root/'main'
        compiled=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(cls.binary)],capture_output=True,text=True,timeout=120)
        if compiled.returncode:raise AssertionError(compiled.stderr)
    def compare(self,source):
        source=textwrap.dedent(source)
        actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=15)
        expected=subprocess.run([sys.executable,'-I','-c',WRAPPER],input=source,capture_output=True,text=True,timeout=15)
        self.assertEqual(expected.returncode,0,expected.stderr)
        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+expected.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
    def test_construction_identity_methods_metadata_and_generic_aliases(self):
        self.compare('''
            value=frozenset([1,1,2])
            print(type(value).__name__,isinstance(value,frozenset),len(value),bool(value),bool(frozenset()))
            print(frozenset(value) is value,value.copy() is value)
            print(sorted(value),repr(frozenset()),repr(frozenset([1])))
            print(type(frozenset[int]).__name__,frozenset[int].__origin__ is frozenset,
                  frozenset[int].__args__,sorted(frozenset[int]([3,4])))
            print(type(aot_union(value)).__name__,sorted(aot_union(value)))
            for method in ['add','clear','remove','discard','pop','update','difference_update','intersection_update','symmetric_difference_update']:
                print(method,hasattr(value,method))
            for call in [lambda:frozenset(1),lambda:frozenset([[]]),lambda:frozenset(1,2),lambda:frozenset(iterable=[1])]:
                try:call()
                except TypeError as error:print(type(error).__name__)
        ''')
    def test_mixed_set_operators_result_types_and_inplace_rebinding(self):
        self.compare('''
            for left in [frozenset([1,2]),{1,2}]:
                for right in [frozenset([2,3]),{2,3}]:
                    for result in [left|right,left&right,left-right,left^right]:
                        print(type(result).__name__,sorted(result))
            value=frozenset([1,2]);alias=value
            value|={3};value&={2,3};value-={3};value^={4}
            print(sorted(value),sorted(alias),value is alias)
            for method in ['__or__','__ror__','__and__','__rand__','__sub__','__rsub__','__xor__','__rxor__']:
                result=getattr(alias,method)({2,3})
                print(method,type(result).__name__,sorted(result))
            print(alias.__or__([1]) is NotImplemented)
            for call in [lambda:alias|[1],lambda:alias&[1],lambda:{1}|[2]]:
                try:call()
                except TypeError as error:print(type(error).__name__)
        ''')
    def test_iterable_methods_multi_arguments_and_early_consumption(self):
        self.compare('''
            value=frozenset([1,2,3])
            print(sorted(value.union([4],[5,1])),sorted(value.intersection([1,2],[2,3])),
                  sorted(value.difference([1],[3])),sorted(value.symmetric_difference([2,2,4])))
            print(sorted(value.union()),sorted(value.intersection()),sorted(value.difference()))
            for method in ['issubset','issuperset','isdisjoint','intersection','difference','union','symmetric_difference']:
                for own,values in [([1],[1,2]),([1],[2,1]),([],[1,2])]:
                    events=[]
                    def source():
                        for item in values:events.append(item);yield item
                        events.append('end')
                    result=getattr(frozenset(own),method)(source())
                    print(method,sorted(result) if isinstance(result,frozenset) else result,events)
        ''')
    def test_comparisons_containment_nested_sets_and_class_patterns(self):
        self.compare('''
            a=frozenset([1,2]);b={1,2,3}
            print(a=={1,2},a!={1},a<b,a<=b,b>a,b>=a,a==[1,2])
            nested=frozenset([frozenset([1,2])])
            print({1,2} in nested,frozenset([1,2]) in nested,{3} not in nested)
            mutable={frozenset([1,2])}
            mutable.discard({1,2})
            print(mutable)
            for call in [lambda:[] in a,lambda:a<[1],lambda:a.issubset([[]])]:
                try:call()
                except TypeError as error:print(type(error).__name__)
            match a:
                case frozenset(value):print(value is a)
            match a:
                case [x,y]:print('sequence')
                case _:print('not sequence')
        ''')
    def test_numeric_nested_hashes_and_hash_cache(self):
        self.compare('''
            for items in [[],[1],[1,2,3],[-1,2.5,1j],[frozenset([1,2]),frozenset([3])]]:
                print(hash(frozenset(items)))
            print(hash(frozenset([1]))==hash(frozenset([1.0]))==hash(frozenset([1+0j])))
            events=[]
            class Token:
                def __init__(self,value):self.value=value
                def __hash__(self):events.append(('hash',self.value));return self.value
                def __eq__(self,other):events.append('eq');return self is other
            token=Token(1)
            value=frozenset([token]);print(events);events.clear()
            first=hash(value);token.value=20
            print(hash(value)==first,events);events.clear()
            source={token};print(events);events.clear()
            copied=frozenset(source)
            print(events,hash(copied)==hash(frozenset([20])))
            print(len({value:'a',value.copy():'b'}))
            class Integer(int):pass
            class HashSubclass:
                def __hash__(self):return Integer(-1)
            key=HashSubclass()
            print(hash(key),hash(frozenset([key]))==hash(frozenset([-2])))
        ''')
    def test_hash_reuse_set_mutations_and_side_effects(self):
        self.compare('''
            events=[]
            class Token:
                def __init__(self,n):self.n=n
                def __hash__(self):events.append(self.n);return self.n
            a,b,c=Token(1),Token(2),Token(3)
            source={a,b};events.clear()
            source.add(c);print(events);events.clear()
            frozen=frozenset(source);print(events);events.clear()
            print(type(frozen|source).__name__,type(source|frozen).__name__,events)
            source.discard(a);source.remove(b);source.pop();events.clear()
            print(hash(frozenset(source))==hash(frozenset()),events)
            source.update([a,b]);events.clear()
            source&={b,c};source^={a};source|={c};source-={b};events.clear()
            copy=frozenset(source);print(events,len(copy))
            source.clear();events.clear()
            print(len(frozenset(source)),events)
            set.__init__(source,frozen);print(events,len(source));events.clear()
            set.__init__(source);print(len(frozenset(source)),events)
        ''')
    def test_subclasses_overrides_hashing_generic_aliases_and_repr(self):
        self.compare('''
            class Frozen(frozenset):
                def __new__(cls,values=()):
                    obj=super().__new__(cls,values);obj.tag='tag';return obj
                def __init__(self,values=()):self.arguments=list(values)
                def __ror__(self,other):return 'reflected'
            value=Frozen([1])
            print(type(value).__name__,value.tag,value.arguments,repr(value),str(value),value.__repr__())
            print(type(value.copy()).__name__,value.copy() is value,type(frozenset(value)).__name__,frozenset(value) is value)
            print(type(value|{2}).__name__,sorted({2}|value),hash(value)==hash(frozenset([1])))
            print(type(Frozen[int]).__name__,type(Frozen[int]([1])).__name__)
            class Iterated(Frozen):
                def __iter__(self):print('iter override');yield 9
                def __len__(self):return 99
            source=Iterated([1])
            print(list(frozenset.__iter__(source)),frozenset.__len__(source),len(source))
            print(sorted(frozenset(source)),sorted(value.union(source)),value.isdisjoint(source))
            class Slots(frozenset):__slots__=('tag',)
            item=Slots([1]);item.tag=2
            print(item.tag,hasattr(item,'__dict__'))
        ''')
    def test_gc_member_roots_callback_lookup_and_iterator_lifetime(self):
        self.compare('''
            import gc,operator
            events=[]
            class Token:
                def __init__(self,n):self.n=n
                def __hash__(self):gc.collect();return 5
                def __eq__(self,other):gc.collect();return self.n==other.n
                def __del__(self):events.append(self.n)
            value=frozenset([Token(1),Token(2)])
            print(Token(1) in value,len(value))
            iterator=iter(value)
            print(type(iterator).__name__,operator.length_hint(iterator))
            del value
            gc.collect()
            print(sorted(item.n for item in iterator),operator.length_hint(iterator))
            print(next(iterator,None),next(iterator,None))
            gc.collect()
            print(sorted(events))
            class Recursive:
                def __repr__(self):gc.collect();return repr(holder[0])
            holder=[None];holder[0]=frozenset([Recursive()])
            print(holder[0],holder[0].__repr__())
            finished=[]
            class Frozen(frozenset):
                def __del__(self):finished.append('deleted')
            value=Frozen([1]);iterator=iter(value);del value;gc.collect();print(finished)
            print(next(iterator));gc.collect();print(finished)
            print(next(iterator,None));gc.collect();print(finished)
        ''')

    def test_unbound_descriptors_reduce_and_subclass_keyword_initialization(self):
        self.compare('''
            value=frozenset([1])
            print(frozenset.__new__(frozenset,value) is value)
            print(frozenset.__new__(frozenset),frozenset.__init__(value,3,tag=2))
            for method in ['copy','__contains__','__iter__','__repr__','__hash__']:
                try:getattr(frozenset,method)({1},1) if method=='__contains__' else getattr(frozenset,method)({1})
                except TypeError as error:print(method,type(error).__name__)
            for call in [lambda:set.update(value,[2]),lambda:set.__iter__(value),lambda:set.__len__(value)]:
                try:call()
                except TypeError as error:print(type(error).__name__)
            class Frozen(frozenset):
                def __init__(self,values=(),*,tag=None):self.tag=tag
                def __repr__(self):return 'custom'
            value=Frozen([1],tag=2)
            print(value.tag,repr(value),str(value),value.__str__(),frozenset.__str__(value),frozenset.__repr__(value))
            print(type(frozenset.__new__(Frozen,[1],tag=3)).__name__)
            reduced=value.__reduce_ex__(4)
            print(reduced[0] is Frozen,reduced[1],reduced[2])
            reduced[2]['tag']=7;print(value.tag)
            class Protocol:
                def __index__(self):print('index');return 4
            print(value.__reduce_ex__(Protocol())[0] is Frozen)
            try:value.__reduce_ex__('4')
            except TypeError as error:print(type(error).__name__)
        ''')
    def test_mutating_comparison_callbacks_rehash_free_updates_and_gc_reuse(self):
        self.compare('''
            import gc
            events=[]
            class Token:
                def __init__(self,n):self.n=n
                def __hash__(self):events.append(('hash',self.n));gc.collect();return 1
                def __eq__(self,other):
                    events.append(('eq',self.n,other.n));gc.collect()
                    if mutate:source.clear()
                    return True
            a,b=Token(1),Token(2)
            mutate=False
            source={a};other={b};events.clear()
            value=frozenset(source)|other;print(len(value),events);events.clear()
            value=frozenset(source)^other;print(len(value),events);events.clear()
            source.update(other);print(events);events.clear()
            source.intersection_update(other);print(events);events.clear()
            source.difference_update(other);print(events);events.clear()
            mutate=True
            source={a};events.clear();print(b in source,len(source),events)
            source={a};events.clear();print(source.issuperset({b}),len(source),events)
            source={a};events.clear();source.discard(b);print(len(source),events)
            mutate=False
            for index in range(8):
                source={a};old=frozenset(source);del source,old;gc.collect()
                source={b};events.clear();fresh=frozenset(source)
                print(len(fresh),events)
        ''')

    def test_large_frozen_construction_iteration_and_hash_indexed_operations(self):
        self.compare('''
            value=frozenset(range(20000));other=frozenset(range(10000,30000))
            print(len(value),sum(value),19999 in value,20000 in value)
            print(len(value|other),len(value&other),len(value-other),len(value^other))
            print(value==frozenset(range(20000)),value.issubset(value|other))
            print(sum(value.intersection(range(19990,20010))))
        ''')

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrozenSetIntegerModeTests(unittest.TestCase):
    def test_all_integer_modes_normalize_before_hashing_aot_and_dynamic(self):
        numbers=[1,2**61,2**127+2**65+7,2**200+7,-2**200-7]
        body='''value=frozenset(NUMBERS)
print(len(value),hash(value),hash(frozenset([1,True,1.0,1+0j]))==hash(frozenset([1])))
print(value==frozenset(set(value)))
class Hasher:
    def __init__(self,number):self.number=number
    def __hash__(self):return self.number
for number in [-1]+NUMBERS:
    key=Hasher(number)
    print(hash(key),hash(frozenset([key]))==hash(frozenset([number])))
'''
        source=body.replace('NUMBERS',repr(numbers))
        source+='exec('+repr(body.replace('NUMBERS',repr(numbers)))+')\n'
        for mode in ['i64','i128','bigint']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(prefix='py2fastrust-frozen-mode-') as name:
                width={'i64':64,'i128':128}.get(mode)
                normalized=numbers if width is None else [(value+2**(width-1))%2**width-2**(width-1) for value in numbers]
                expected=subprocess.run([sys.executable,'-I','-c',body.replace('NUMBERS',repr(normalized))*2],capture_output=True,text=True,timeout=15)
                self.assertEqual(expected.returncode,0,expected.stderr)
                result=transpile(source,TranspileOptions(integer=mode,optimize=False))
                self.assertTrue(result.success,'\n'.join(map(str,result.diagnostics)))
                directory=Path(name);target=directory/'main.rs';target.write_text(result.rust_source,encoding='utf-8')
                built=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(directory/'main')],capture_output=True,text=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(directory/'main')],capture_output=True,text=True,timeout=15)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout,expected.stdout)
