"""Implicit Python slot inheritance stops at an earlier native defining base."""

import shutil
import textwrap
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ImplicitSlotTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source, **kwargs):
        source = textwrap.dedent(source)
        return self.run_source(source + "\nexec(" + repr(source) + ", {})\n", **kwargs)

    def test_sequence_length_iteration_getitem_contains_and_reverse_mro(self):
        self.compare('''
            events=[]
            class Mixin:
                def __len__(self):events.append('len');return 9
                def __iter__(self):events.append('iter');return iter([8,9])
                def __getitem__(self,k):events.append(('get',k));return 77
                def __contains__(self,k):events.append(('contains',k));return False
                def __reversed__(self):events.append('reverse');return iter([6,5])
            class NativeFirst(list,Mixin):pass
            class PythonFirst(Mixin,list):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls([1,2]);events.clear()
                print(cls.__name__,len(value),bool(value),list(value),value[0],1 in value,list(reversed(value)),events)
            class NativeTuple(tuple,Mixin):pass
            value=NativeTuple([1,2]);events.clear()
            print(len(value),list(value),value[0],2 in value,events)
            print(list(reversed(value)))
        ''')

    def test_mapping_copy_fast_path_retains_native_hashes_and_lookup_order(self):
        self.compare('''
            events=[]
            class Key:
                def __hash__(self):events.append('hash');return 17
                def __repr__(self):return 'key'
            key=Key()
            class Mixin:
                def __iter__(self):events.append('iter');return iter(['virtual'])
                def keys(self):events.append('keys');return ['virtual']
                def __getitem__(self,key):events.append('getitem');return 55
                def __contains__(self,key):events.append('contains');return False
                def __len__(self):events.append('len');return 5
            class NativeFirst(dict,Mixin):pass
            class PythonFirst(Mixin,dict):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls();dict.__setitem__(value,key,7);events.clear()
                copied=dict.copy(value)
                print(cls.__name__,len(copied),events)
                events.clear();print(len(value),value[key],key in value,list(value),events)
                print(next(iter(dict.keys(value))) is key)
        ''')

    def test_setitem_delitem_inplace_alias_and_side_effect_order(self):
        self.compare('''
            events=[]
            class Mixin:
                def __setitem__(self,key,value):events.append(('set',key,value))
                def __delitem__(self,key):events.append(('del',key))
                def __iadd__(self,value):events.append('iadd');return ['replacement']
            class NativeFirst(list,Mixin):pass
            class PythonFirst(Mixin,list):pass
            def target(value):events.append('target');return value
            def key():events.append('key');return 0
            def rhs():events.append('rhs');return 8
            for cls in [NativeFirst,PythonFirst]:
                value=cls([1,2]);alias=value;events.clear()
                target(value)[key()]=rhs()
                del target(value)[key()]
                value += [4]
                print(cls.__name__,value,alias,value is alias,events)
        ''')

    def test_numeric_truth_conversion_unary_and_binary_mro(self):
        self.compare('''
            events=[]
            class Mixin:
                def __bool__(self):events.append('bool');return True
                def __len__(self):events.append('len');return 7
                def __neg__(self):events.append('neg');return 101
                def __abs__(self):events.append('abs');return 102
                def __add__(self,value):events.append('add');return 103
                def __radd__(self,value):events.append('radd');return 104
                def __int__(self):events.append('int');return 105
                def __float__(self):events.append('float');return 106.0
                def __index__(self):events.append('index');return 107
                def __round__(self,n=None):events.append('round');return 108
                def __hash__(self):events.append('hash');return 109
            class NativeFirst(int,Mixin):pass
            class PythonFirst(Mixin,int):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls(0);events.clear()
                print(cls.__name__,bool(value),-value,abs(value),value+3,3+value,int(value),float(value),round(value),hash(value),events)
                events.clear();print([4,5,6][value],bin(value),events)
        ''')

    def test_reflected_notimplemented_is_called_once_and_subclass_priority(self):
        self.compare('''
            events=[]
            class Mixin:
                def __radd__(self,other):events.append('radd');return NotImplemented
                def __rsub__(self,other):events.append('rsub');return 77
            class NativeFirst(int,Mixin):pass
            class PythonFirst(Mixin,int):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls(3);events.clear()
                print(cls.__name__,7+value,7-value,events)
            class Other:
                def __radd__(self,other):events.append('other radd');return 99
            events.clear();print(NativeFirst(2)+Other(),events)
        ''')

    def test_hash_none_native_tuple_and_hash_descriptor_binding(self):
        self.compare('''
            events=[]
            class Mixin:
                def __hash__(self):events.append('hash');return 77
            class NativeFirst(list,Mixin):pass
            class PythonFirst(Mixin,list):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls([1]);events.clear()
                try:print(hash(value),events)
                except Exception as error:print(type(error).__name__,events)
            class NativeTuple(tuple,Mixin):pass
            events.clear();print(hash(NativeTuple([1,2]))==hash((1,2)),events)
            class Descriptor:
                def __get__(self,obj,owner):events.append('get hash');return lambda:41
            class Hashed:
                __hash__=Descriptor()
            events.clear();print(hash(Hashed()),events)
            class Disabled(int):__hash__=None
            try:hash(Disabled(3))
            except Exception as error:print(type(error).__name__)
        ''')

    def test_native_contains_ignores_iteration_override_and_str_owns_str(self):
        self.compare('''
            events=[]
            class Mixin:
                def __iter__(self):events.append('iter');return iter([8])
                def __contains__(self,key):events.append('contains');return False
                def __str__(self):events.append('str');return 'python str'
                def __repr__(self):events.append('repr');return 'python repr'
            class NativeList(list,Mixin):pass
            class NativeString(str,Mixin):pass
            class PythonString(Mixin,str):pass
            class IterFirst(Mixin,list):
                __contains__=list.__contains__
            for value in [NativeList([1,2]),IterFirst([1,2])]:
                events.clear();print(2 in value,list(value),events)
            for cls in [NativeString,PythonString]:
                value=cls('abcd');events.clear()
                print(cls.__name__,'bc' in value,str(value),repr(value),events)
            class OwnRepr(str):
                def __repr__(self):return 'own repr'
            print(str(OwnRepr('abcd')),repr(OwnRepr('abcd')))
        ''')

    def test_native_index_value_and_custom_index_result_validation(self):
        self.compare('''
            events=[]
            class Native(int):
                def __index__(self):events.append('ignored index');return 0
            value=Native(2)
            print([10,20,30][value],bin(value),1<<value,events)
            class Index:
                def __index__(self):events.append('index');return 1
            print([10,20][Index()],events)
            class Bad:
                def __index__(self):return 1.5
            try:[1,2][Bad()]
            except Exception as error:print(type(error).__name__)
        ''')

    def test_length_errors_and_truth_share_checked_structural_conversion(self):
        self.compare('''
            events=[]
            class Index:
                def __index__(self):events.append('index');return 2
            for result in [-1,1.5,True,Index()]:
                class Length:
                    def __len__(self):events.append('len');return result
                value=Length()
                for operation in [lambda:len(value),lambda:bool(value)]:
                    events.clear()
                    try:print(operation(),events)
                    except Exception as error:print(type(error).__name__,events)
            class Negative:
                def __len__(self):return -1
            class NativeFirst(list,Negative):pass
            class PythonFirst(Negative,list):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls([1])
                for operation in [lambda:len(value),lambda:bool(value)]:
                    try:print(operation())
                    except Exception as error:print(type(error).__name__)
        ''')

    def test_binding_descriptor_errors_follow_each_protocol_fallback(self):
        self.compare('''
            events=[]
            class Broken:
                def __get__(self,obj,owner):events.append('bind');raise AttributeError('from descriptor')
            for name in ['__len__','__bool__','__contains__','__iter__','__neg__','__abs__','__round__','__add__','__hash__']:
                Mixin=type('Mixin',(),{name:Broken()})
                NativeFirst=type('NativeFirst',(int,Mixin),{})
                PythonFirst=type('PythonFirst',(Mixin,int),{})
                for cls in [NativeFirst,PythonFirst]:
                    value=cls(2);events.clear()
                    operation=(lambda:len(value)) if name=='__len__' else (lambda:bool(value)) if name=='__bool__' else (lambda:1 in value) if name=='__contains__' else (lambda:iter(value)) if name=='__iter__' else (lambda:-value) if name=='__neg__' else (lambda:abs(value)) if name=='__abs__' else (lambda:round(value)) if name=='__round__' else (lambda:value+1) if name=='__add__' else (lambda:hash(value))
                    try:result=operation();print(name,cls.__name__,'ok',events)
                    except Exception as error:print(name,cls.__name__,type(error).__name__,events)
            class Sequence:
                __iter__=Broken()
                def __getitem__(self,index):return index
            try:iter(Sequence())
            except Exception as error:print(type(error).__name__,events)
        ''')

    def test_none_special_methods_block_native_fallbacks(self):
        self.compare('''
            for name in ['__iter__','__len__','__contains__','__getitem__','__setitem__','__delitem__']:
                Disabled=type('Disabled',(list,),{name:None})
                value=Disabled([1,2])
                try:
                    if name=='__iter__':iter(value)
                    elif name=='__len__':len(value)
                    elif name=='__contains__':1 in value
                    elif name=='__getitem__':value[0]
                    elif name=='__setitem__':value[0]=7
                    else:del value[0]
                except Exception as error:print(name,type(error).__name__,list.copy(value))
            class NoBool(int):__bool__=None
            try:bool(NoBool(3))
            except Exception as error:print(type(error).__name__)
            class NativeIndex(int):__index__=None
            print([4,5][NativeIndex(1)])
        ''')

    def test_native_iterators_keep_owner_and_gc_cycles_alive(self):
        self.compare('''
            import gc
            events=[]
            class Mixin:
                def __iter__(self):events.append('wrong iter');return iter([])
                def __reversed__(self):events.append('wrong reverse');return iter([])
                def __del__(self):events.append('deleted')
            class Values(list,Mixin):pass
            for reverse in [False,True]:
                value=Values([1,2]);value.cycle=value
                iterator=reversed(value) if reverse else iter(value)
                del value;gc.collect();print(list(iterator),events)
                del iterator;gc.collect();print(events)
        ''',integer='bigint')

    def test_rich_comparison_set_frozen_and_complex_inheritance(self):
        self.compare('''
            events=[]
            class Mixin:
                def __eq__(self,other):events.append('eq');return False
                def __lt__(self,other):events.append('lt');return True
                def __len__(self):events.append('len');return 7
                def __iter__(self):events.append('iter');return iter([9])
                def __contains__(self,key):events.append('contains');return False
                def __neg__(self):events.append('neg');return 99
            for base,argument in [(int,3),(list,[3]),(set,[3]),(frozenset,[3]),(complex,3)]:
                NativeFirst=type('NativeFirst',(base,Mixin),{})
                PythonFirst=type('PythonFirst',(Mixin,base),{})
                for cls in [NativeFirst,PythonFirst]:
                    value=cls(argument);events.clear()
                    print(base.__name__,cls.__name__,value==base(argument),events)
                    if base in [set,frozenset]:
                        events.clear();print(len(value),3 in value,sorted(value),events)
                    if base is complex:
                        events.clear();print(-value,events)
                    elif base is not complex:
                        events.clear();print(value<base(argument),events)
        ''')

    def test_slot_updates_are_observed_after_exec_and_own_override_deletion(self):
        self.compare('''
            class Mixin:
                def __len__(self):return 9
                def __iter__(self):return iter([7])
            class NativeFirst(list,Mixin):pass
            class PythonFirst(Mixin,list):pass
            native,python=NativeFirst([1,2]),PythonFirst([1,2])
            print(len(native),len(python),list(native),list(python))
            exec('Mixin.__len__=lambda self:11; Mixin.__iter__=lambda self:iter([8])')
            print(len(native),len(python),list(native),list(python))
            NativeFirst.__len__=lambda self:13
            NativeFirst.__iter__=lambda self:iter([6])
            print(len(native),list(native))
            del NativeFirst.__len__;del NativeFirst.__iter__
            print(len(native),list(native))
        ''')

    def test_native_contains_checks_type_and_observes_live_list_mutation(self):
        self.compare('''
            class Text(str):pass
            print(Text('bc') in Text('abcd'))
            try:1 in Text('abcd')
            except Exception as error:print(type(error).__name__)
            class Values(list):pass
            events=[]
            class First:
                def __eq__(self,other):events.append('eq');values.append(9);return False
            values=Values([First()])
            print(9 in values,events,len(values))
            class Group(set):pass
            class Key:
                def __hash__(self):events.append('hash');return 17
            key=Key();group=Group([key]);events.clear()
            print(key in group,events)
            try:[] in group
            except Exception as error:print(type(error).__name__)
        ''')

    def test_wide_native_slots_and_overflowing_python_length(self):
        self.compare('''
            class Mixin:
                def __len__(self):return 1<<100
                def __add__(self,other):return -7
                def __hash__(self):return 33
            class NativeFirst(int,Mixin):pass
            class PythonFirst(Mixin,int):pass
            for cls in [NativeFirst,PythonFirst]:
                value=cls(1<<90)
                print(cls.__name__,value+3,hash(value)==hash(1<<90) if cls is NativeFirst else hash(value)==33)
                try:len(value)
                except Exception as error:print(type(error).__name__)
        ''',integer='i128')


if __name__ == '__main__':unittest.main()
