"""Caller continuations for hash, string conversion, and iterator creation."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER="import sys,gc,functools\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ProtocolBuiltinRecursionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="py2fastrust-protocol-builtins-")
        root=Path(cls.directory.name)
        result=transpile(WRAPPER,TranspileOptions(optimize=False,integer="bigint"))
        if not result.success:raise AssertionError(result.diagnostics)
        source=root/"main.rs"
        source.write_text(result.rust_source,encoding="utf-8")
        cls.binary=root/"main"
        compiled=subprocess.run(["rustc","--edition=2021",str(source),"-o",str(cls.binary)],capture_output=True,text=True,timeout=120)
        if compiled.returncode:raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def compare(self,source):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,"-I","-c",WRAPPER],input=source,capture_output=True,text=True,timeout=30)
        actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=30)
        self.assertEqual(expected.returncode,0,expected.stderr)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)

    def test_recursive_builtins_at_low_default_high_limits(self):
        self.compare('''
            calls=0
            class Hash:
                def __hash__(self):
                    global calls
                    calls+=1
                    return hash(self)
            class Repr:
                def __repr__(self):
                    global calls
                    calls+=1
                    return repr(self)
            class Str:
                def __str__(self):
                    global calls
                    calls+=1
                    return str(self)
            class Iter:
                def __iter__(self):
                    global calls
                    calls+=1
                    return iter(self)
            for requested in [None,50,1000,3000]:
                if requested is not None:sys.setrecursionlimit(requested)
                for cls,operation in [(Hash,hash),(Repr,repr),(Str,str),(Iter,iter)]:
                    calls=0
                    try:operation(cls())
                    except RecursionError:print(sys.getrecursionlimit(),cls.__name__,calls)
        ''')

    def test_descriptor_and_property_binding_recursion(self):
        self.compare('''
            sys.setrecursionlimit(1000)
            class Descriptor:
                def __init__(self,operation):self.operation=operation
                def __get__(self,obj,owner):return lambda:self.operation(obj)
            class Hash:__hash__=Descriptor(hash)
            class Repr:__repr__=Descriptor(repr)
            class Str:__str__=Descriptor(str)
            class Iter:__iter__=Descriptor(iter)
            class Property:
                @property
                def __repr__(self):return lambda:repr(self)
            for cls,operation in [(Hash,hash),(Repr,repr),(Str,str),(Iter,iter),(Property,repr)]:
                try:operation(cls())
                except RecursionError:print('caught',cls.__name__)
        ''')

    def test_binding_recovery_and_body_attributeerror_are_distinct(self):
        self.compare('''
            events=[]
            class Missing:
                def __get__(self,obj,owner):
                    events.append(('bind',sys.exception() is outer))
                    gc.collect()
                    raise AttributeError('binding')
            class Hash:__hash__=Missing()
            class Repr:__repr__=Missing()
            class Str:__str__=Missing()
            class Iter:
                __iter__=Missing()
                def __getitem__(self,key):
                    events.append(('item',key,sys.exception() is outer))
                    if key==2:raise IndexError
                    return key+1
            for cls,operation in [(Hash,hash),(Repr,repr),(Str,str),(Iter,iter)]:
                try:raise LookupError('outer')
                except LookupError as outer:
                    events.clear()
                    try:
                        value=operation(cls())
                        print(cls.__name__,'ok',list(value) if cls is Iter else type(value).__name__)
                    except Exception as error:print(cls.__name__,type(error).__name__,error.__context__ is outer)
                    print(events,sys.exception() is outer)
            for name,operation in [('__hash__',hash),('__repr__',repr),('__str__',str),('__iter__',iter)]:
                class Body:pass
                def method(self):raise AttributeError('body')
                setattr(Body,name,method)
                try:operation(Body())
                except AttributeError as error:print(name,str(error))
            class Other:
                def __get__(self,obj,owner):raise RuntimeError('binding')
            for name,operation in [('__hash__',hash),('__repr__',repr),('__str__',str),('__iter__',iter)]:
                class Body:pass
                setattr(Body,name,Other())
                try:operation(Body())
                except RuntimeError as error:print(name,str(error))
        ''')

    def test_return_validation_uses_caller_exception_scope(self):
        self.compare('''
            for name,operation in [('__hash__',hash),('__repr__',repr),('__str__',str),('__iter__',iter)]:
                class Bad:pass
                def method(self):
                    try:return 1.5
                    except TypeError:print('callee must not catch')
                    finally:print('finally',name)
                setattr(Bad,name,method)
                try:raise LookupError('outer')
                except LookupError as outer:
                    try:operation(Bad())
                    except TypeError as error:
                        names=[];tb=error.__traceback__
                        while tb:
                            names.append(tb.tb_frame.f_code.co_name);tb=tb.tb_next
                        print(name,type(error).__name__,error.__context__ is outer,names)
            class Integer(int):
                def __int__(self):raise RuntimeError('must not convert')
                def __index__(self):raise RuntimeError('must not index')
            for result in [-1,-2,2**63-1,2**63,2**100,-2**100,Integer(12),True]:
                class Hash:
                    def __hash__(self):return result
                print(type(result).__name__,hash(Hash()))
            class Index:
                def __index__(self):print('must not index');return 3
            class Hash:
                def __hash__(self):return Index()
            try:hash(Hash())
            except TypeError:print('hash requires int')
        ''')

    def test_nested_callable_descriptor_preserves_outer_binding_recovery(self):
        self.compare('''
            events=[]
            class Missing:
                def __get__(self,obj,owner):
                    events.append('inner bind');gc.collect()
                    raise AttributeError('inner binding')
            class Callable:__call__=Missing()
            class Outer:__get__=Callable()
            class Hash:__hash__=Outer()
            class Repr:__repr__=Outer()
            class Iter:
                __iter__=Outer()
                def __getitem__(self,key):
                    if key==1:raise IndexError
                    return 3
            for cls,operation in [(Hash,hash),(Repr,repr),(Iter,iter)]:
                events.clear()
                try:
                    value=operation(cls())
                    print(cls.__name__,'ok',list(value) if cls is Iter else type(value).__name__)
                except Exception as error:print(cls.__name__,type(error).__name__)
                print(events)
            class CallableBody:
                def __call__(self):raise AttributeError('actual body')
            class Descriptor:
                def __get__(self,obj,owner):return CallableBody()
            class Repr:__repr__=Descriptor()
            try:repr(Repr())
            except AttributeError as error:print(str(error))
        ''')

    def test_string_subclass_result_identity_and_native_precedence(self):
        self.compare('''
            class Text(str):pass
            text=Text('result')
            class Repr:
                def __repr__(self):gc.collect();return text
            class Str:
                def __str__(self):gc.collect();return text
            class Both:
                def __str__(self):return text
                def __repr__(self):return text
            for value in [Repr(),Str(),Both()]:
                for operation in [repr,str]:
                    result=operation(value)
                    print(type(value).__name__,operation.__name__,type(result).__name__,result is text)
            class Native(str):
                def __repr__(self):return text
            value=Native('original')
            print(str(value),type(str(value)).__name__,repr(value)is text)
            class Override(str):
                def __str__(self):return text
            print(str(Override('other'))is text)
            class Recursive:
                def __repr__(self):return str(self)
            try:str(Recursive())
            except RecursionError:print('inherited object str recurses safely')
        ''')

    def test_iter_result_requires_type_slot_but_does_not_bind_next(self):
        self.compare('''
            class Returns:
                def __init__(self,value):self.value=value
                def __iter__(self):return self.value
            class Absent:
                def __getattr__(self,name):print('must not getattr');return lambda:9
            class NoneNext:__next__=None
            class Descriptor:
                def __get__(self,obj,owner):print('next binding');raise AttributeError('next binding')
            class BindingNext:__next__=Descriptor()
            class BodyNext:
                def __next__(self):print('next body');raise AttributeError('next body')
            class Bypass:
                def __getattribute__(self,name):print('must not lookup',name);raise AttributeError
                def __next__(self):return 8
            for cls in [Absent,NoneNext,BindingNext,BodyNext,Bypass]:
                value=cls()
                try:
                    result=iter(Returns(value))
                    print(cls.__name__,'accepted',result is value)
                    try:print('next',next(result))
                    except Exception as error:print('next error',type(error).__name__)
                except TypeError:print(cls.__name__,'not an iterator')
            class Disabled:
                __iter__=None
                def __getitem__(self,key):print('must not getitem');return 1
            try:iter(Disabled())
            except TypeError:print('explicit None disables iteration')
            for value in [iter([1]),(x for x in [1])]:
                result=iter(Returns(value));print(result is value,next(result))
        ''')

    def test_partial_cached_wrappers_and_suspended_callback_roots(self):
        self.compare('''
            events=[]
            cached=functools.cache(str)
            wrapped=functools.partial(cached)
            class Text:
                def __init__(self,n):self.n=n
                def __str__(self):
                    events.append(self.n);gc.collect()
                    return wrapped(Text(self.n-1)) if self.n else 'done'
            value=Text(15)
            print(wrapped(value),wrapped(value),events,cached.cache_info().currsize)
            released=[]
            class Callable:
                def __init__(self,obj):self.obj=obj
                def __call__(self):gc.collect();return 'kept'
                def __del__(self):released.append('callable')
            class Descriptor:
                def __get__(self,obj,owner):gc.collect();return Callable(obj)
            class Text:__str__=Descriptor()
            print(str(Text()));gc.collect();print(released)
            exec('class Dynamic:\\n def __iter__(self):return iter(self)')
            try:iter(Dynamic())
            except RecursionError:print('dynamic iterator recursion')
        ''')


if __name__=="__main__":unittest.main()
