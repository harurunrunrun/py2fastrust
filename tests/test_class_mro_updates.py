"""Custom MRO callbacks and transactional class hierarchy changes."""

import shutil
import textwrap
import unittest
import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ClassMroUpdateTests(unittest.TestCase):
    maxDiff = None
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source):
        source = textwrap.dedent(source)
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_custom_mro_special_lookup_order_and_default_c3(self):
        self.compare('''
            import gc
            events=[]
            class A:
                def value(self):return 'A'
            class B:
                def value(self):return 'B'
            class M(type):
                def __getattribute__(cls,name):
                    if name=='mro':events.append('ordinary getattr')
                    return super().__getattribute__(name)
                def mro(cls):
                    events.append((cls.__name__,cls.__mro__ is None))
                    gc.collect();return [cls,B,A,object]
            class C(A,B,metaclass=M):
                def mro(self):raise LookupError('class attribute must not run')
            print(events,C().value())
            print([c.__name__ for c in C.__mro__],[c.__name__ for c in type.mro(C)])
            print(C.__mro__ is C.__mro__,issubclass(C,A),issubclass(C,B))
            class Descriptor:
                def __get__(self,instance,owner):
                    events.append((instance.__name__,owner.__name__))
                    return lambda:[instance,A,object]
            class N(type):mro=Descriptor()
            class D(A,metaclass=N):pass
            print(D.__mro__==(D,A,object),events[-1])
        ''')

    def test_creation_timing_layout_validation_and_custom_sequences(self):
        self.compare('''
            events=[]
            class M(type):
                def mro(cls):
                    events.append(('mro',cls.__mro__ is None,'x' in cls.__dict__,cls.__dict__['f'].__closure__[0].cell_contents is cls,'__doc__' in cls.__dict__))
                    try:cls()
                    except Exception as error:events.append(type(error).__name__)
                    return type.mro(cls)
            class C(metaclass=M):
                __slots__=('x',)
                def f(self):return __class__
            print(events,'x' in C.__dict__)
            class T(tuple):
                def __iter__(self):events.append('iter tuple');return super().__iter__()
            class N(type):
                def mro(cls):return T((cls,object))
            class D(metaclass=N):pass
            print(type(D.__mro__) is tuple,events[-1])
            for which in range(5):
                class Broken(type):
                    def mro(cls):
                        if which==0:return []
                        if which==1:return [cls,1]
                        if which==2:return [cls,int,object]
                        if which==3:raise LookupError('mro failure')
                        return [cls]
                try:
                    class E(metaclass=Broken):pass
                    print(issubclass(E,object))
                    try:E()
                    except Exception as error:print(type(error).__name__)
                except Exception as error:print(type(error).__name__)
            class Native(type):
                def mro(cls):return [cls,object]
            class F(list,metaclass=Native):pass
            print(type(F()) is F,issubclass(F,list))
            class Omit(type):
                def mro(cls):return [cls]
            class Slotted(metaclass=Omit):__slots__=('x',)
            class Include(Omit):
                def mro(cls):return [cls,object]
            try:
                class Invalid(Slotted,metaclass=Include):pass
            except Exception as error:print(type(error).__name__)
        ''')

    def test_base_updates_propagate_lookup_slots_super_and_subclass_registry(self):
        self.compare('''
            class A:
                def value(self):return 'A'
                def __len__(self):return 1
            class B:
                def value(self):return 'B'
                def __len__(self):return 2
            class C(A):
                def value(self):return super().value()+'C'
            class D(C):pass
            obj=D();old=C.__mro__;child_old=D.__mro__;bases=(B,)
            C.__bases__=bases
            print(obj.value(),len(obj),issubclass(D,B),issubclass(D,A))
            print(C.__bases__ is bases,C.__mro__ is old,D.__mro__ is child_old,C.__base__ is B)
            print(C in B.__subclasses__(),C in A.__subclasses__())
            class E(B):pass
            print([x.__name__ for x in B.__subclasses__()])
            C.__bases__=bases
            print([x.__name__ for x in B.__subclasses__()])
            type.__setattr__(C,'__bases__',(A,))
            print(obj.value(),len(obj),C in A.__subclasses__(),C in B.__subclasses__(),C.__base__ is A)
        ''')

    def test_compatible_slot_rebasing_preserves_existing_instance_storage(self):
        self.compare('''
            class A:__slots__=('x','y')
            class B:__slots__=('y','x')
            class C(A):__slots__=('z',)
            class D(C):__slots__=('w',)
            c=C();c.x=1;c.y=2;c.z=3
            d=D();d.x=4;d.y=5;d.z=6;d.w=7
            C.__bases__=(B,)
            print(c.x,c.y,c.z,d.x,d.y,d.z,d.w)
            try:A.x.__get__(c)
            except Exception as error:print(type(error).__name__)
            C.__bases__=(A,);print(c.x,c.y,c.z,d.x,d.y,d.z,d.w)
            del A.x;del B.x
            C.__bases__=(B,);print(c.y,c.z,d.y,d.z,d.w)
            class E:__slots__=()
            class F:__slots__=()
            class G(E):pass
            G.__bases__=(F,);print(G.__bases__==(F,))
            # Even an inherited type.mro is a custom invocation when the
            # metaclass is a heap subtype, so its result is layout-checked.
            class M(type):pass
            class H(A,metaclass=M):__slots__=('z',)
            before=H.__mro__;before_bases=H.__bases__
            try:H.__bases__=(B,)
            except Exception as error:print(type(error).__name__,H.__mro__ is before,H.__bases__ is before_bases)
        ''')

    def test_mro_update_failure_rolls_back_parent_and_changed_descendants(self):
        self.compare('''
            events=[];failing=False
            class A:pass
            class B:pass
            class M(type):
                def mro(cls):
                    events.append(cls.__name__)
                    if failing and cls.__name__=='Child':raise LookupError('child fails')
                    return type.mro(cls)
            class C(A,metaclass=M):pass
            class Child(C):pass
            before=C.__mro__;child_before=Child.__mro__;old_bases=C.__bases__
            events.clear();failing=True
            try:C.__bases__=(B,)
            except Exception as error:print(type(error).__name__,str(error))
            print(events,C.__mro__ is before,Child.__mro__ is child_before,C.__bases__ is old_bases)
            print(C in A.__subclasses__(),C in B.__subclasses__())
            failing=False;C.__bases__=(B,);print(issubclass(Child,B))
            for bases in [(),[],(1,),(C,),(object,), (A,A)]:
                old=C.__bases__;mro=C.__mro__
                try:C.__bases__=bases
                except Exception as error:print(type(error).__name__,C.__bases__ is old,C.__mro__ is mro)
            for name in ('__bases__','__mro__'):
                try:delattr(C,name)
                except Exception as error:print(type(error).__name__)
            try:C.__mro__=()
            except Exception as error:print(type(error).__name__)
        ''')

    def test_reentrant_base_updates_keep_inner_mro_and_callback_effects(self):
        self.compare('''
            import gc
            events=[];active=False;replace=False
            class A:pass
            class B:pass
            class Z:pass
            class M(type):
                def mro(cls):
                    global active,replace
                    events.append((cls.__name__,cls.__bases__[0].__name__))
                    if replace and not active:
                        active=True;cls.__bases__=(Z,);active=False
                    gc.collect();return type.mro(cls)
            class C(A,metaclass=M):pass
            class D(C):pass
            events.clear();replace=True;C.__bases__=(B,);replace=False
            print(events,C.__bases__==(Z,),issubclass(D,Z),C in Z.__subclasses__(),C in B.__subclasses__())
            print(C.__mro__==(C,Z,object),D.__mro__==(D,C,Z,object))
        ''')

    def test_recursive_class_creation_raises_python_exception_and_recovers(self):
        self.compare('''
            import sys
            sys.setrecursionlimit(80)
            remaining=3
            class M(type):
                def mro(cls):
                    global remaining
                    if remaining:
                        remaining-=1;type.__new__(M,'Nested',(),{})
                    return type.mro(cls)
            class C(metaclass=M):pass
            print(remaining,C.__mro__==(C,object))
            recurse=True
            class N(type):
                def mro(cls):
                    if recurse:type.__new__(N,'Recursive',(),{})
                    return type.mro(cls)
            try:type.__new__(N,'Start',(),{})
            except RecursionError:print('recursion error')
            recurse=False;D=type.__new__(N,'Recovered',(),{})
            print(D.__mro__==(D,object))
        ''')

    def test_subclass_snapshots_survive_gc_and_diamond_children_recompute_twice(self):
        self.compare('''
            import gc
            events=[];enabled=False
            class A:pass
            class B:pass
            children=[]
            class M(type):
                def mro(cls):
                    if enabled:
                        events.append(cls.__name__)
                        if cls.__name__=='Left':children.clear();gc.collect()
                    return type.mro(cls)
            class C(A,metaclass=M):pass
            children.extend([M('Left',(C,),{}),M('Right',(C,),{})])
            enabled=True;C.__bases__=(B,);enabled=False
            print(events)
            class L(C):pass
            class R(C):pass
            class D(L,R):pass
            events.clear();enabled=True;C.__bases__=(A,);enabled=False
            print(events,issubclass(D,A),not issubclass(D,B))
        ''')

    def test_slot_side_effects_survive_rollback_and_descriptor_reentry(self):
        self.compare('''
            import gc
            failing=False
            class A:__slots__=('x',)
            class B:__slots__=('x',)
            class M(type):
                def mro(cls):
                    if failing and cls.__name__=='Child':
                        c.x=90;d.x=91;gc.collect();raise LookupError('rollback')
                    return type.mro(cls)
            class C(A,metaclass=M):pass
            class Child(C):pass
            c=C();d=Child();c.x=1;d.x=2;before=C.__mro__;child_before=Child.__mro__
            failing=True
            try:C.__bases__=(B,)
            except Exception as error:print(type(error).__name__)
            print(c.x,d.x,C.__mro__ is before,Child.__mro__ is child_before)
            enabled=False;busy=False
            class Z:__slots__=('x',)
            class Descriptor:
                def __get__(self,cls,owner):
                    global busy
                    if enabled and not busy and cls.__name__=='E':
                        busy=True;cls.__bases__=(Z,);busy=False;gc.collect()
                    return lambda:type.mro(cls)
            class N(type):mro=Descriptor()
            class E(A,metaclass=N):pass
            class F(E):pass
            obj=F();obj.x=7;enabled=True;E.__bases__=(B,);enabled=False
            print(E.__bases__==(Z,),issubclass(F,Z),obj.x)
        ''')

    def test_heap_base_layout_compatibility_matrix(self):
        self.compare('''
            pairs=[(None,None),((),()),(('x',),('x',)),(('x',),('y',)),
                   (None,()),(('__dict__',),('__dict__',)),
                   (('__weakref__',),('__weakref__',)),(None,('__dict__','__weakref__'))]
            for base in [object,list,dict,tuple,int,float,complex,bytes,bytearray,set,frozenset,Exception,ValueError,OSError]:
                for a,b in pairs:
                    first={} if a is None else {'__slots__':a}
                    second={} if b is None else {'__slots__':b}
                    try:A=type('A',(base,),first);B=type('B',(base,),second);C=type('C',(A,),{})
                    except Exception as error:print(base.__name__,a,b,'create',type(error).__name__);continue
                    old=C.__bases__;old_mro=C.__mro__
                    try:C.__bases__=(B,);print(base.__name__,a,b,'ok')
                    except Exception as error:print(base.__name__,a,b,type(error).__name__,C.__bases__ is old,C.__mro__ is old_mro)
        ''')

    def test_deep_heap_hierarchies_use_cached_parent_linearizations(self):
        self.compare('''
            base=object
            for index in range(350):base=type('Deep'+str(index),(base,),{})
            print(len(base.__mro__),base.__mro__[0] is base,base.__mro__[-1] is object)
            print(issubclass(base,object),len(type.mro(base)))
        ''')


if __name__=='__main__':
    unittest.main()
