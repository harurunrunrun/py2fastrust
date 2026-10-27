"""Python slot callbacks and their caller-owned return conversions use VM frames."""
import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ProtocolRecursionTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_recursive_length_bool_index_at_configured_limits(self):
        self.run_source('''
            import sys
            calls=0
            class Length:
                def __len__(self):
                    global calls
                    calls+=1
                    return len(self)
            class Truth:
                def __bool__(self):
                    global calls
                    calls+=1
                    return bool(self)
            class Index:
                def __index__(self):
                    global calls
                    calls+=1
                    return int(self)
            for requested in [None,50,1000,3000]:
                if requested is not None:sys.setrecursionlimit(requested)
                limit=sys.getrecursionlimit()
                for cls,operation in [(Length,len),(Truth,bool),(Index,int)]:
                    calls=0
                    try:operation(cls())
                    except RecursionError:print(limit,cls.__name__,calls)
        ''')

    def test_truth_jumps_and_not_keep_values_and_exception_handlers(self):
        self.run_source('''
            import sys
            sys.setrecursionlimit(1000)
            class Test:
                def __init__(self,n):self.n=n
                def __bool__(self):
                    if self.n==0:return False
                    return not Test(self.n-1)
            for n in [0,1,2,15]:
                value=Test(n)
                print(bool(value),not value,(value or 7) is value,(value and 7) is value)
                if value:print('yes')
                else:print('no')
            class Loop:
                def __bool__(self):
                    if self:return True
                    return False
            try:
                if Loop():print('unreachable')
            except RecursionError:print('caught branch recursion')
        ''')

    def test_descriptor_property_and_callable_binding_use_heap_frames(self):
        self.run_source('''
            import sys
            sys.setrecursionlimit(1000)
            events=[]
            class Descriptor:
                def __get__(self,obj,owner):
                    return lambda:len(obj)
            class Length:__len__=Descriptor()
            class Truth:
                @property
                def __bool__(self):return lambda:bool(self)
            class Callable:
                def __call__(self):return len(value)
            class Indirect:__len__=Callable()
            value=Indirect()
            for obj,op in [(Length(),len),(Truth(),bool),(value,len)]:
                try:op(obj)
                except RecursionError:print('caught',type(obj).__name__)
            class Getter:
                def __get__(self,obj,owner):return len(obj)
            class Bound:__len__=Getter()
            try:len(Bound())
            except RecursionError:print('caught binding recursion')
        ''')

    def test_return_validation_runs_in_suspended_caller_scope(self):
        self.run_source('''
            import sys
            class BadLength:
                def __len__(self):
                    try:return 'wrong'
                    except TypeError:print('wrong callee caught')
                    finally:print('length finally')
            class BadBool:
                def __bool__(self):
                    try:return 1
                    except TypeError:print('wrong callee caught')
                    finally:print('bool finally')
            for obj,operation in [(BadLength(),len),(BadBool(),bool)]:
                try:operation(obj)
                except TypeError as error:
                    names=[];tb=error.__traceback__
                    while tb:
                        names.append(tb.tb_frame.f_code.co_name);tb=tb.tb_next
                    print(type(error).__name__,names)
            class Integer:
                def __index__(self):return 4
            class Length:
                def __len__(self):return Integer()
            print(len(Length()),bool(Length()))
        ''')

    def test_binding_attributeerror_fallback_does_not_swallow_body_error(self):
        self.run_source('''
            events=[]
            class Missing:
                def __get__(self,obj,owner):events.append('bind');raise AttributeError('missing')
            class Fallback:
                __bool__=Missing()
                def __len__(self):events.append('len');return 3
            class Default:__bool__=Missing()
            class Body:
                def __bool__(self):raise AttributeError('body')
            class MissingLength:__len__=Missing()
            for obj in [Fallback(),Default(),Body(),MissingLength()]:
                events.clear()
                try:print(bool(obj),events)
                except AttributeError as error:print(str(error),events)
        ''')

    def test_cached_partial_slots_and_dynamic_frames_keep_effect_order(self):
        self.run_source('''
            import functools,gc,sys
            sys.setrecursionlimit(1000)
            events=[]
            cached=functools.lru_cache(None)(len)
            wrapped=functools.partial(cached)
            class Length:
                def __init__(self,n):self.n=n
                def __len__(self):
                    events.append(self.n)
                    if self.n%5==0:gc.collect()
                    if self.n==0:return 2
                    return wrapped(Length(self.n-1))
            value=Length(15)
            print(wrapped(value),wrapped(value),events)
            print(cached.cache_info())
            exec('class Dynamic:\\n def __bool__(self):return bool(self)')
            try:bool(Dynamic())
            except RecursionError:print('dynamic recursion')
        ''')

    def test_native_mro_and_returned_index_callbacks(self):
        self.run_source('''
            import sys,gc
            sys.setrecursionlimit(1000)
            class RecursiveInt(int):
                def __int__(self):return int(self)
            try:int(RecursiveInt(2))
            except RecursionError:print('recursive int subclass')
            events=[]
            class Index:
                def __index__(self):events.append('index');gc.collect();return 5
            class Length:
                def __len__(self):return Index()
            print(len(Length()),bool(Length()),events)
            class Native(int):
                def __index__(self):return int(self)
            print(int(Native(7)))
            class BadIndex:
                def __index__(self):
                    try:return 2.5
                    except TypeError:print('wrong index catch')
            class BadLength:
                def __len__(self):return BadIndex()
            try:len(BadLength())
            except TypeError:print('caller catches bad index')
            class IntDescriptor:
                def __get__(self,obj,owner):return lambda:int(obj)
            class Recur:__int__=IntDescriptor()
            try:int(Recur())
            except RecursionError:print('recursive int descriptor')
        ''')

    def test_finite_depth_gc_and_caller_exception_context(self):
        self.run_source('''
            import gc,sys
            sys.setrecursionlimit(3000)
            events=[]
            class Node:
                def __init__(self,n):self.n=n
                def __len__(self):
                    try:
                        if self.n==0:
                            gc.collect()
                            return 7
                        return len(Node(self.n-1))
                    finally:
                        if self.n<3:events.append(self.n)
            print(len(Node(1200)),events)
            class Bad:
                def __bool__(self):return 3
            try:
                raise ValueError('outer')
            except ValueError as original:
                try:bool(Bad())
                except TypeError as error:print(error.__context__ is original)
            class Recover:
                def __len__(self):
                    try:return len(self)
                    except RecursionError:return 2
            sys.setrecursionlimit(50)
            print(len(Recover()))
        ''')

    def test_slot_binding_kinds_and_cached_fallback_gc(self):
        self.run_source('''
            import functools,gc
            events=[]
            class Missing:
                def __get__(self,obj,owner):events.append('bind');gc.collect();raise AttributeError('binding')
            class Fallback:
                __bool__=Missing()
                @staticmethod
                def __len__():events.append('len');return 4
            value=Fallback()
            operation=functools.cache(bool)
            print(operation(value),operation(value),events,operation.cache_info())
            class ClassLength:
                size=7
                @classmethod
                def __len__(cls):return cls.size
            print(len(ClassLength()),bool(ClassLength()))
            class Callable:
                def __call__(self,*args,**kwargs):return 9
            class Descriptor:
                def __get__(self,obj,owner):return Callable()
            class HasCallable:__len__=Descriptor()
            print(len(HasCallable()))
        ''', integer='bigint')
