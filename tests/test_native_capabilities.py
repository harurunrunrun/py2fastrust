"""Native operand acceptance remains separate from custom-MRO method lookup."""
import shutil
import textwrap
import unittest
import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class NativeCapabilityTests(unittest.TestCase):
    maxDiff = None
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source):
        source=textwrap.dedent(source)
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_primitive_numeric_slots_accept_long_capability_without_methods(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            class C(int,metaclass=M):pass
            value=C(3)
            operations=[lambda a,b:a+b,lambda a,b:a-b,lambda a,b:a*b,
                        lambda a,b:a//b,lambda a,b:a%b,lambda a,b:a**b,
                        lambda a,b:a<<b,lambda a,b:a>>b,
                        lambda a,b:a&b,lambda a,b:a|b,lambda a,b:a^b]
            for function in operations:
                print(function(2,value),function(value,2))
                try:function(value,value)
                except Exception as error:print(type(error).__name__)
            print(2.0+value,value+2.0,complex(2,1)+value,value+complex(2,1))
            print(value==3,3==value,value<4,2<value,bool(C(0)))
            print(int.__add__(2,value),int.__rsub__(2,value))
            for function in [int,float,lambda obj:int.__add__(obj,2)]:
                try:function(value);print('unexpected conversion')
                except Exception as error:print(type(error).__name__)
        ''')

    def test_sequence_and_mapping_native_inputs_use_capabilities(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            for base,source in [(str,'b'),(bytes,b'b'),(tuple,(2,)),(list,[2]),(dict,{'a':2})]:
                C=M('C',(base,),{});value=C(source)
                primitive=source if base is not list and base is not dict else base()
                print(base.__name__,primitive==value,value==primitive)
                for function in [lambda obj:primitive+obj,lambda obj:obj+primitive,lambda obj:obj+obj]:
                    try:print(function(value))
                    except Exception as error:print(type(error).__name__)
                if base is dict:
                    for function in [lambda obj:{'x':1}|obj,lambda obj:obj|{'x':1},lambda obj:dict.__or__({},obj),lambda obj:dict.__ror__({},obj)]:
                        try:print(function(value))
                        except Exception as error:print(type(error).__name__)
                    print(dict.__eq__({},value))
                elif base is not bytes:
                    print(base.__add__(primitive,value))
                for function in [len,iter,lambda obj:base.__len__(obj)]:
                    try:function(value);print('unexpected method')
                    except Exception as error:print(type(error).__name__)
        ''')

    def test_capabilities_follow_parent_mro_at_creation_not_physical_ancestry(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            for base,source in [(int,3),(str,'12'),(bytes,b'12'),(tuple,(3,))]:
                A=M('A',(base,),{});B=M('B',(A,),{})
                first=A(source);second=B(source)
                for value in [first,second]:
                    for function in [lambda obj:2+obj,lambda obj:'x'+obj,lambda obj:(1,)+obj,
                                     lambda obj:int(obj),lambda obj:float(obj),lambda obj:[0,1,2,3][obj]]:
                        try:print(function(value))
                        except Exception as error:print(type(error).__name__)
        ''')

    def test_hidden_unicode_encoding_does_not_expose_buffers(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            class S(str,metaclass=M):
                def __str__(self):return 'ignored'
            class B(bytes,metaclass=M):pass
            source=S('日本語')
            print(bytes(source,'utf-8'),bytearray(source,'utf-8'))
            print(bytes(source,encoding='utf-8',errors='strict'))
            for value in [source,B(b'12')]:
                for function in [bytes,bytearray,memoryview]:
                    try:function(value);print('unexpected buffer')
                    except Exception as error:print(type(error).__name__)
            class T(S):pass
            try:bytes(T('12'),'ascii')
            except Exception as error:print(type(error).__name__)
        ''')

    def test_existing_instances_keep_caps_and_change_visible_methods_on_rebase(self):
        self.compare('''
            class M(type):
                def mro(cls):return [cls,object]
            class Visible(int):pass
            class Hidden(int,metaclass=M):pass
            class C(Visible):pass
            value=C(3);C.__bases__=(Hidden,)
            print(2+value,value+2,value==3,bool(C(0)))
            for function in [int,float,lambda obj:int.__add__(obj,2)]:
                try:function(value);print('unexpected method')
                except Exception as error:print(type(error).__name__)
            C.__bases__=(Visible,)
            print(int(value),value+2,bool(C(0)))
            class D(Hidden):pass
            second=D(3);D.__bases__=(Visible,)
            try:print(2+second)
            except Exception as error:print(type(error).__name__)
        ''')

    def test_python_overrides_and_explicit_native_dispatch_keep_their_order(self):
        self.compare('''
            import gc
            events=[]
            class M(type):
                def mro(cls):return [cls,object]
            class C(int,metaclass=M):
                def __radd__(self,value):events.append('reflected');gc.collect();return 99
                def __eq__(self,value):events.append('equal');return 'custom'
            value=C(3)
            print(2+value,int.__add__(2,value),3==value,value==3,events)
            class S(str,metaclass=M):
                def __radd__(self,value):events.append('str reflected');return 'custom'
            print('x'+S('b'),events)
            print(list(range(C(3))))
            for function in [lambda obj:[0,1,2,3][obj],lambda obj:(1,)*obj]:
                try:print(function(value))
                except Exception as error:print(type(error).__name__)
        ''')


    def test_flagged_dictionary_union_preserves_queued_rhs_mapping_callbacks(self):
        self.compare('''
            import gc,sys
            sys.setrecursionlimit(3000)
            remaining=240;events=[]
            class M(type):
                def mro(cls):return [cls,object]
            class D(dict,metaclass=M):
                def keys(self):
                    global remaining
                    if remaining:
                        remaining-=1
                        nested={'base':1}|self
                        if nested['custom']!=42:raise ValueError('lost value')
                    gc.collect();events.append('keys');return ['custom']
                def __getitem__(self,key):events.append(key);return 42
            value=D()
            print({'base':1}|value,remaining,len(events),events[-1])
            print(value|{'base':1})
            print(dict.__or__({'base':1},value))
            print(dict.__ror__({'base':1},value))
        ''')

    def test_dictionary_union_left_copy_preserves_subclass_mapping_and_empty_paths(self):
        self.compare('''
            import gc
            events=[]
            class D(dict):
                def __iter__(self):events.append('iter');return iter(['custom'])
                def keys(self):events.append('keys');gc.collect();return ['custom']
                def __getitem__(self,key):events.append(('get',key));gc.collect();return 42
            for occupied in (False,True):
                value=D()
                if occupied:dict.__setitem__(value,'stored',7)
                for function in [lambda:value|{'base':1},
                                 lambda:dict.__or__(value,{'base':1}),
                                 lambda:dict.__ror__({'base':1},value)]:
                    events.clear();print(occupied,function(),events)
            class Fast(dict):
                def keys(self):raise AssertionError('native copy must retain stored hashes')
                def __getitem__(self,key):raise AssertionError('native copy must retain entries')
            print(Fast(stored=7)|{'base':1})
            class M(type):
                def mro(cls):return [cls,object]
            class Hidden(dict,metaclass=M):pass
            class Visible(dict):pass
            class Rebased(Visible):
                def __iter__(self):events.append('iter');return iter(['custom'])
                def keys(self):events.append('keys');gc.collect();return ['custom']
                def __getitem__(self,key):events.append(('get',key));return 42
            value=Rebased(stored=7);Rebased.__bases__=(Hidden,)
            events.clear();print(value|{'base':1},events)
        ''')

    def test_flagged_dictionary_comparison_keeps_recursive_values_in_heap_frames(self):
        self.compare('''
            import gc,sys
            sys.setrecursionlimit(3000);remaining=240
            class V:
                def __eq__(self,other):
                    global remaining
                    if remaining:
                        remaining-=1;gc.collect();return {'nested':self}=={'nested':other}
                    return True
            class M(type):
                def mro(cls):return [cls,object]
            class Hidden(dict,metaclass=M):pass
            class Visible(dict):pass
            class C(Visible):pass
            left=C(k=V());right={'k':V()};C.__bases__=(Hidden,)
            print(left==right,remaining,right==left,dict.__eq__(right,left))
            try:left['k']
            except Exception as error:print(type(error).__name__)
            C.__bases__=(Visible,)
            print(left==right,list(left),len(left))
        ''')


if __name__=='__main__':
    unittest.main()
