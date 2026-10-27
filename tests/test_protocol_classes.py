"""Class creation callbacks suspend in their caller's heap continuation."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys,gc\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ProtocolClassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-class-protocol-")
        cls.addClassCleanup(cls.directory.cleanup)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = Path(cls.directory.name) / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = source.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=45)
        actual = subprocess.run([str(self.binary)], input=source,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_custom_mro_finite_300_and_infinite_at_limit_3000(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            class Meta(type):
                def mro(cls):
                    depth=cls.__dict__['depth']
                    if depth:Meta('Nested',(),{'depth':depth-1})
                    return type.mro(cls)
            print(Meta('Finite',(),{'depth':300}).depth)
            class Recursive(type):
                def mro(cls):
                    Recursive('Nested',(),{})
                    return type.mro(cls)
            try:Recursive('Infinite',(),{})
            except RecursionError:print('RecursionError')
            print(type('Recovered',(),{}).__name__)
        ''')

    def test_set_name_and_init_subclass_callbacks_recurse_on_heap(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            class Descriptor:
                def __init__(self,depth):self.depth=depth
                def __set_name__(self,owner,name):
                    if self.depth:type('Nested',(),{'field':Descriptor(self.depth-1)})
            print(type('Finite',(),{'field':Descriptor(300)}).__name__)
            class Base:
                def __init_subclass__(cls,depth=0):
                    if depth:type('Nested',(Base,),{},depth=depth-1)
            print(type('Finite',(Base,),{},depth=300).__name__)
            class Recursive:
                def __set_name__(self,owner,name):type('Nested',(),{'field':self})
            try:type('Infinite',(),{'field':Recursive()})
            except RecursionError:print('RecursionError')
        ''')

    def test_instance_new_init_and_metaclass_call_are_queued(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            class New:
                def __new__(cls,depth):
                    if depth:New(depth-1)
                    return object.__new__(cls)
                def __init__(self,depth):self.depth=depth
            print(New(300).depth)
            class Init:
                def __init__(self,depth):
                    self.depth=depth
                    if depth:Init(depth-1)
            print(Init(300).depth)
            class Meta(type):
                def __call__(cls,depth):
                    if depth:cls(depth-1)
                    return type.__call__(cls,depth)
            class Custom(metaclass=Meta):
                def __init__(self,depth):self.depth=depth
            print(Custom(300).depth)
            class Recursive:
                def __init__(self):Recursive()
            try:Recursive()
            except RecursionError:print('RecursionError')
        ''')

    def test_prepare_body_class_cells_hooks_and_gc_keep_order(self):
        self.compare('''
            events=[]
            class Descriptor:
                def __set_name__(self,owner,name):
                    gc.collect();events.append(('name',name,owner.__mro__[0] is owner))
            class Base:
                def __init_subclass__(cls,marker):
                    gc.collect();events.append(('init',marker,cls.field.__class__.__name__))
            class Meta(type):
                @classmethod
                def __prepare__(meta,name,bases,**kw):events.append(('prepare',name));gc.collect();return {}
                def __new__(meta,name,bases,namespace,**kw):
                    events.append(('new',name));return super().__new__(meta,name,bases,namespace,**kw)
                def mro(cls):events.append(('mro',cls.__mro__));gc.collect();return type.mro(cls)
                def __init__(cls,*args,**kw):events.append(('meta init',cls.__name__))
            class Result(Base,metaclass=Meta,marker=7):
                events.append(('body','Result'))
                field=Descriptor()
                def owner(self):return __class__
            print(events,Result().owner() is Result)
        ''')

    def test_base_entries_slots_and_replaced_builder_use_queued_calls(self):
        self.compare('''
            import builtins
            events=[]
            class Base:pass
            class Entry:
                def __mro_entries__(self,bases):gc.collect();events.append('entries');return (Base,)
            class Slots:
                def __iter__(self):events.append('slots');yield 'value'
            class Result(Entry()):__slots__=Slots()
            instance=Result();instance.value=8
            print(events,instance.value,Result.__orig_bases__[0].__class__.__name__)
            original=builtins.__build_class__
            def builder(*args,**kw):gc.collect();events.append('builder');return original(*args,**kw)
            builtins.__build_class__=builder
            try:
                class Replaced:
                    def owner(self):return __class__
            finally:builtins.__build_class__=original
            print(Replaced().owner() is Replaced,events)
        ''')

    def test_constructor_descriptors_foreign_results_and_errors_keep_gc_roots(self):
        self.compare('''
            events=[]
            class NewDescriptor:
                def __get__(self,instance,owner):
                    gc.collect();events.append(('new get',instance is None))
                    def create(cls,value):
                        events.append(('new',value));gc.collect();return object.__new__(cls)
                    return create
            class InitDescriptor:
                def __get__(self,instance,owner):
                    gc.collect();events.append(('init get',type(instance).__name__))
                    def initialize(value):instance.value=value;gc.collect();events.append(('init',value))
                    return initialize
            class Result:
                __new__=NewDescriptor()
                __init__=InitDescriptor()
            print(Result(17).value,events)
            class Foreign:
                def __new__(cls):return 42
                def __init__(self):raise AssertionError('must not initialize a foreign result')
            print(Foreign())
            class Invalid:
                def __init__(self):return 1
            try:Invalid()
            except Exception as error:print(type(error).__name__)
            class Raising:
                def __new__(cls):gc.collect();raise LookupError('new')
            try:Raising()
            except Exception as error:print(type(error).__name__,str(error))
            print(Result(18).value)
        ''')

    def test_set_name_snapshot_and_class_cells_remain_live_on_failure(self):
        self.compare('''
            events=[]
            class Descriptor:
                def __set_name__(self,owner,name):
                    events.append(name)
                    if name=='first':del owner.second;gc.collect()
            class Result:
                first=Descriptor()
                second=Descriptor()
            print(events,hasattr(Result,'second'))
            saved=[]
            class Broken(type):
                def mro(cls):
                    saved.append(cls.__dict__['owner'])
                    gc.collect();raise LookupError('mro')
            try:
                class Failed(metaclass=Broken):
                    def owner(self):return __class__
            except LookupError:print('mro')
            gc.collect()
            cell=saved[0].__closure__[0]
            print(cell.cell_contents.__name__,cell.cell_contents.__mro__)
        ''')

    def test_native_container_initializers_share_callback_queue(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            class Values:
                def __init__(self,depth):self.depth=depth
                def __iter__(self):
                    if self.depth:List(Values(self.depth-1))
                    yield self.depth
            class List(list):pass
            print(List(Values(300)))
            class Pairs:
                def __init__(self,depth):self.depth=depth
                def __iter__(self):
                    if self.depth:Dictionary(Pairs(self.depth-1))
                    yield ('value',self.depth)
            class Dictionary(dict):pass
            print(Dictionary(Pairs(300)))
            class SetValues:
                def __init__(self,depth):self.depth=depth
                def __iter__(self):
                    if self.depth:Set(SetValues(self.depth-1))
                    yield self.depth
            class Set(set):pass
            print(sorted(Set(SetValues(300))))
        ''')

    def test_exception_subclass_initializers_keep_native_exception_identity(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            class Error(Exception):
                def __init__(self,depth):
                    if depth:Error(depth-1)
                    self.depth=depth
                    super().__init__('message',depth)
            value=Error(300)
            print(type(value).__name__,value.depth,value.args,str(value))
            try:raise value
            except Error as caught:print(caught is value)
            class Named(Exception):
                def __init__(self,*,value):self.value=value
            print(Named(value=17).value)
            class Recursive(Exception):
                def __init__(self):Recursive()
            try:Recursive()
            except RecursionError:print('RecursionError')
        ''')

    def test_slots_iterators_bind_and_recurse_without_length_callbacks(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            events=[]
            class Iterator:
                def __init__(self,depth):self.depth=depth;self.done=False
                def __iter__(self):return self
                def __len__(self):raise AssertionError('no len')
                def __length_hint__(self):raise AssertionError('no hint')
                def __next__(self):
                    if self.done:raise StopIteration
                    self.done=True
                    if self.depth:type('Nested',(),{'__slots__':Slots(self.depth-1)})
                    else:gc.collect()
                    return 'value'
            class Bind:
                def __get__(self,instance,owner):
                    gc.collect();return lambda:Iterator(instance.depth)
            class Slots:
                def __init__(self,depth):self.depth=depth
                __iter__=Bind()
                def __len__(self):raise AssertionError('no source len')
            C=type('Finite',(),{'__slots__':Slots(300)})
            value=C();value.value=19;print(value.value)
            print(tuple(Slots(1)))
            class Broken:
                def __iter__(self):gc.collect();raise LookupError('slots')
            try:type('Broken',(),{'__slots__':Broken()})
            except LookupError as error:print(str(error))
            class Recursive:
                def __iter__(self):
                    type('Nested',(),{'__slots__':self})
                    return iter(())
            try:type('Infinite',(),{'__slots__':Recursive()})
            except RecursionError:print('RecursionError')
        ''')

    def test_metaclass_keyword_uses_original_key_equality(self):
        self.compare('''
            events=[]
            class Key(str):
                def __eq__(self,other):
                    events.append('eq');gc.collect();return str.__eq__(self,other)
                __hash__=str.__hash__
            class Result(**{Key('metaclass'):type}):pass
            print(events,Result.__name__)
        ''')

    def test_tuple_conversion_branch_matrix_keeps_iteration_and_ignores_hints(self):
        self.compare('''
            events=[]
            class Hint:
                def __init__(self,label,mode):self.label=label;self.mode=mode
                def __get__(self,instance,owner):
                    events.append(self.label+' lookup')
                    if self.mode=='lookup error':raise LookupError(self.label)
                    def hint():
                        events.append(self.label+' call')
                        if self.mode=='type error':raise TypeError(self.label)
                        if self.mode=='call error':raise LookupError(self.label)
                        if self.mode=='negative':return -1
                        if self.mode=='invalid':return 'bad'
                        return 20
                    return hint
            def iterator_type(mode,count):
                class Iterator:
                    __len__=Hint('iterator len',mode)
                    __length_hint__=Hint('iterator hint',mode)
                    def __init__(self):self.index=0
                    def __iter__(self):events.append('iterator iter');return self
                    def __next__(self):
                        if self.index==count:raise StopIteration
                        value=self.index;self.index+=1;return value
                return Iterator
            for mode in ['normal','lookup error','type error','call error','negative','invalid']:
                for count in [2,17]:
                    Iterator=iterator_type(mode,count)
                    class Source:
                        __len__=Hint('source len',mode)
                        __length_hint__=Hint('source hint',mode)
                        def __iter__(self):events.append('source iter');return Iterator()
                    for source in [Iterator(),Source()]:
                        events.clear();result=tuple(source)
                        print(mode,count,len(result),events)
            class Tuple(tuple):
                __len__=Hint('tuple len','call error')
                __length_hint__=Hint('tuple hint','call error')
                def __iter__(self):events.append('tuple iter');return iter((1,2))
            class List(list):
                __len__=Hint('list len','call error')
                __length_hint__=Hint('list hint','call error')
                def __iter__(self):events.append('list iter');return iter((1,2))
            for source in [(1,2),[1,2],range(17),(x for x in range(17)),Tuple((1,2)),List((1,2))]:
                events.clear();print(tuple(source),events)
            class BrokenIter:
                @property
                def __iter__(self):events.append('iter lookup');raise LookupError('iter')
            class BrokenNext:
                def __iter__(self):return self
                def __next__(self):events.append('next call');raise LookupError('next')
            for source in [BrokenIter(),BrokenNext()]:
                events.clear()
                try:tuple(source)
                except LookupError as error:print(str(error),events)
        ''')

    def test_namespace_copy_callbacks_precede_slots_and_keep_original_snapshot(self):
        self.compare('''
            sys.setrecursionlimit(3000)
            events=[]
            class Namespace(dict):
                def __iter__(self):raise AssertionError('keys method should be used')
                def keys(self):
                    events.append('keys');gc.collect();return super().keys()
                def __getitem__(self,key):
                    events.append(('get',key));gc.collect();return super().__getitem__(key)
            namespace=Namespace(value=7)
            class Slots:
                def __iter__(self):
                    namespace['later']=19;gc.collect();events.append('slots');yield 'field'
            namespace['__slots__']=Slots()
            C=type('Copied',(),namespace)
            print(events,C.value,hasattr(C,'later'),namespace['later'])
            events.clear();print(type('Empty',(),Namespace()).__name__,events)
            for name,bases in [(1,()),('Invalid',[]),('Invalid',(list,dict))]:
                events.clear()
                try:type(name,bases,Namespace(value=1))
                except Exception as error:print(type(error).__name__,events)
            class RecursiveNamespace(dict):
                def __init__(self,depth):super().__init__(value=depth);self.depth=depth
                def __iter__(self):return super().__iter__()
                def keys(self):
                    if self.depth:type('Nested',(),RecursiveNamespace(self.depth-1))
                    return super().keys()
            print(type('Finite',(),RecursiveNamespace(300)).value)
        ''')

    def test_generic_alias_class_calls_and_metadata_setters_are_queued(self):
        self.compare('''
            import types
            sys.setrecursionlimit(3000)
            class Box:
                @classmethod
                def __class_getitem__(cls,item):return types.GenericAlias(cls,item)
                def __init__(self,depth):
                    self.depth=depth
                    if depth:Box[int](depth-1)
            value=Box[int](300)
            print(value.depth,value.__orig_class__.__origin__ is Box)
            print(type.__call__(int,'17'),type.__call__(list,(1,2)))
            def factory(depth):
                if depth:alias(depth-1)
                return Box(0)
            alias=types.GenericAlias(factory,int)
            print(alias(300).__orig_class__ is alias)
            remaining=300
            class Setter:
                @classmethod
                def __class_getitem__(cls,item):return types.GenericAlias(cls,item)
                def __setattr__(self,name,value):
                    global remaining
                    if name=='__orig_class__' and remaining:
                        remaining-=1;Setter[int]()
                    object.__setattr__(self,name,value)
            print(Setter[int]().__orig_class__.__origin__ is Setter,remaining)
            class Rejected:
                def __setattr__(self,name,value):raise LookupError('metadata')
            try:types.GenericAlias(Rejected,int)()
            except LookupError as error:print(str(error))
        ''')

    def test_generic_metadata_attribute_callbacks_use_heap_frames(self):
        self.compare('''
            import typing
            sys.setrecursionlimit(3000)
            T=typing.TypeVar('T')
            class Entry:
                def __init__(self,depth):self.depth=depth
                def __mro_entries__(self,bases):return (typing.Generic,)
                @property
                def __parameters__(self):
                    if self.depth:
                        class Nested(Entry(self.depth-1)):pass
                    else:gc.collect()
                    return (T,)
            class Finite(Entry(300)):pass
            print(Finite.__parameters__==(T,))
            class Recursive:
                def __mro_entries__(self,bases):return (typing.Generic,)
                @property
                def __parameters__(self):
                    class Nested(self):pass
                    return ()
            try:
                class Infinite(Recursive()):pass
            except RecursionError:print('RecursionError')
            class Recovered(typing.Generic[T]):pass
            print(Recovered.__parameters__==(T,))
        ''')

    def test_generic_metadata_alias_scans_cache_parameters_and_preserve_errors(self):
        self.compare('''
            import types,typing
            T=typing.TypeVar('T')
            events=[]
            class Parameter:
                @property
                def __parameters__(self):events.append('parameters');gc.collect();return (T,)
            alias=types.GenericAlias(list,Parameter())
            class C(typing.Generic[T]):__orig_bases__=(alias,typing.Generic[T])
            print(C.__parameters__==(T,),alias.__parameters__==(T,),events)
            class Bad:
                def __mro_entries__(self,bases):return (typing.Generic,)
                @property
                def __parameters__(self):raise LookupError('parameters')
            try:
                class Invalid(Bad()):pass
            except LookupError as error:print(str(error))
        ''')


if __name__ == "__main__":
    unittest.main()
