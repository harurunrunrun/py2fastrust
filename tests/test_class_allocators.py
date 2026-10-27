"""Physical allocation slots, visible constructors, and opaque native payloads."""
import shutil
import subprocess
import tempfile
from pathlib import Path
from py2fastrust import transpile, TranspileOptions
import textwrap
import unittest
import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ClassAllocatorTests(unittest.TestCase):
    maxDiff = None
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source):
        source = textwrap.dedent(source)
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_raw_native_new_preserves_allocator_and_generic_transition(self):
        self.compare('''
            for base in [object,list,dict,set,tuple,frozenset,int,float,str,bytes,bytearray,complex]:
                C=type('C',(base,),{})
                for new in [object.__new__,list.__new__,int.__new__]:
                    C.__new__=new
                    try:print(base.__name__,'raw',type(C()).__name__)
                    except Exception as error:print(base.__name__,'raw',type(error).__name__)
                C.__new__=staticmethod(lambda cls,*args,**kwargs:42)
                print(base.__name__,'python',C())
                C.__new__=object.__new__
                try:print(base.__name__,'replaced',type(C()).__name__)
                except Exception as error:print(base.__name__,'replaced',type(error).__name__)
                del C.__new__
                try:print(base.__name__,'deleted',type(C()).__name__)
                except Exception as error:print(base.__name__,'deleted',type(error).__name__)
            class Slotted:__slots__=('__new__',)
            try:Slotted()
            except Exception as error:print('slotted new',type(error).__name__)
        ''')

    def test_hidden_native_allocator_keeps_argument_rules(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            for base in [object,list,dict,set,tuple,frozenset,int,float,str,bytes,bytearray,complex,Exception]:
                C=M('C',(base,),{})
                print(base.__name__,C.__new__ is object.__new__,C.__init__ is object.__init__)
                for args,kwargs in [((),{}),((1,),{}),((None,),{}),((),{'q':2})]:
                    try:
                        value=C(*args,**kwargs)
                        print(type(value).__name__,bool(value),issubclass(C,base))
                    except Exception as error:print(type(error).__name__)
                for new in [object.__new__,base.__new__]:
                    try:new(C);print('direct ok')
                    except Exception as error:print(type(error).__name__)
            class Plain:pass
            for base in [int,tuple,bytes]:
                for bases in [(base,Plain),(Plain,base)]:
                    C=type('Mixed',bases,{})
                    print(base.__name__,hasattr(C(),'__weakref__'))
                A=M('A',(base,),{});B=M('B',(A,),{})
                print(base.__name__,hasattr(B(),'__weakref__'))
                try:M('Bad',(A,),{'__slots__':('x',)})
                except Exception as error:print(type(error).__name__)
        ''')

    def test_hidden_payloads_preserve_callbacks_and_gc_without_sequence_exposure(self):
        self.compare('''
            import gc
            gc.disable();events=[]
            class M(type):
                def mro(cls):return [cls,object]
            class Item:
                def __del__(self):events.append('deleted')
            class Values:
                def __iter__(self):
                    events.append('iter');yield Item();events.append('yielded')
            for base in [tuple,frozenset]:
                C=M('C',(base,),{})
                value=C(Values());print(events);events.clear()
                for function in [len,iter,tuple,list]:
                    try:function(value);print('sequence ok')
                    except Exception as error:print(type(error).__name__)
                gc.collect();print(events)
                del value;gc.collect();print(events);events.clear()
            gc.enable()
        ''')

    def test_hidden_text_payloads_support_numeric_parsing_without_buffers(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            for base,source in [(str,'12'),(bytes,b'12')]:
                C=M('C',(base,),{});value=C(source)
                print(int(value),float(value),int(value,16),bool(value))
                for function in [len,iter,bytes,bytearray,memoryview]:
                    try:function(value);print('conversion ok')
                    except Exception as error:print(type(error).__name__)
                if base is bytes:print(str(value,encoding='ascii'))
                C.__int__=lambda self:21
                C.__index__=lambda self:22
                print(int(value),int(value,16),float(value))
                C.__float__=lambda self:23.0
                print(float(value))
        ''')

    def test_allocator_updates_propagate_to_existing_descendants(self):
        self.compare('''
            for base in [object,list,int]:
                A=type('A',(base,),{});B=type('B',(A,),{})
                A.__new__=staticmethod(lambda cls,*args,**kwargs:41)
                print(A(),B())
                A.__new__=object.__new__
                for C in [A,B]:
                    try:print(type(C()).__name__)
                    except Exception as error:print(type(error).__name__)
                del A.__new__
                print(type(A()).__name__,type(B()).__name__)
        ''')


    def test_mro_rollback_restores_slots_but_keeps_new_callback_mutations(self):
        self.compare('''
            failing=False;mutate=False
            class A:
                def __new__(cls):return object.__new__(cls)
            class B:pass
            class M(type):
                def mro(cls):
                    if failing and cls.__name__=='Child':
                        if mutate:C.__new__=staticmethod(lambda cls:43)
                        raise LookupError('rollback')
                    return type.mro(cls)
            class C(B,metaclass=M):pass
            class Child(C):pass
            for change in [False,True]:
                mutate=change;failing=True;old=C.__mro__
                try:C.__bases__=(A,)
                except Exception as error:print(type(error).__name__)
                failing=False
                print(C.__mro__ is old,C.__bases__==(B,))
                print(type(C()).__name__ if not change else C())
            del C.__new__
            print(type(C()).__name__,type(Child()).__name__)
        ''')

    def test_hidden_itertools_and_partial_keep_payloads_without_protocol_exposure(self):
        self.compare('''
            import gc,itertools,functools
            events=[]
            class M(type):
                def mro(cls):return [cls,object]
            class Item:
                def __del__(self):events.append('deleted')
            def identity(value):return value
            for base in [itertools.count,itertools.repeat,itertools.batched,itertools.combinations,itertools.combinations_with_replacement,itertools.compress,itertools.permutations,itertools.product,itertools.zip_longest,functools.partial]:
                if base is functools.partial:args=(identity,Item())
                elif base is itertools.count or base is itertools.repeat:args=(1,)
                elif base is itertools.batched or base is itertools.combinations or base is itertools.combinations_with_replacement:args=([1],1)
                elif base is itertools.compress:args=([1],[True])
                else:args=([1],)
                C=M('C',(base,),{})
                try:value=C(*args)
                except Exception as error:
                    del args;print(base.__name__,type(error).__name__);continue
                del args
                print(base.__name__,bool(value))
                for function in [iter,next,lambda obj:obj()]:
                    try:function(value);print('protocol ok')
                    except Exception as error:print(type(error).__name__)
                gc.collect();print(events)
                del value;gc.collect();print(events);events.clear()
        ''')


    def test_missing_native_module_state_raises_instead_of_aborting(self):
        # CPython 3.14.4 segfaults on these malformed custom MROs. Check our
        # defined error policy directly; a host-process crash is no oracle.
        source=textwrap.dedent('''
            import itertools
            class M(type):
                def mro(cls):return [cls,object]
            cases=[(itertools.accumulate,([1],)),(itertools.chain,([1],)),
                   (itertools.cycle,([1],)),(itertools.dropwhile,(bool,[1])),
                   (itertools.filterfalse,(bool,[1])),(itertools.groupby,([1],)),
                   (itertools.islice,([1],1)),(itertools.pairwise,([1],)),
                   (itertools.starmap,(abs,[(-1,)])),(itertools.takewhile,(bool,[1]))]
            for base,args in cases:
                C=M('C',(base,),{})
                try:C(*args);print('unexpected construction')
                except TypeError:print('TypeError')
        ''')
        result=transpile(source,TranspileOptions(filename='case.py',optimize=False))
        self.assertTrue(result.success,'\n'.join(map(str,result.diagnostics)))
        with tempfile.TemporaryDirectory(prefix='pytors-class-alloc-') as directory:
            target=Path(directory)/'main.rs';target.write_text(result.rust_source)
            compiled=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(Path(directory)/'main')],capture_output=True,text=True,timeout=90)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            actual=subprocess.run([str(Path(directory)/'main')],capture_output=True,text=True,timeout=15)
            self.assertEqual(actual.returncode,0,actual.stderr)
            self.assertEqual(actual.stdout,'TypeError\n'*10)


if __name__=='__main__':
    unittest.main()
