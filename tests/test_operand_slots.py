"""Native and Python operands preserve reflected-slot order and side effects."""
import shutil
import textwrap
import unittest

import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class OperandSlotTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source, **options):
        source = textwrap.dedent(source)
        self.maxDiff = None
        return self.run_source(source + '\nexec(' + repr(source) + ', {})\n', **options)

    def test_unrelated_integer_subclasses_accept_left_native_before_right_python(self):
        self.compare('''
            events=[]
            class Mixin:
                def __eq__(self,other):events.append('eq');return False
                def __gt__(self,other):events.append('gt');return False
                def __radd__(self,other):events.append('radd');return 99
                def __rsub__(self,other):events.append('rsub');return 99
                def __rmul__(self,other):events.append('rmul');return 99
                def __rpow__(self,other):events.append('rpow');return 99
            class Native(int):pass
            class Python(Mixin,int):pass
            for expression in [lambda:Native(1)==Python(1),lambda:Native(1)<Python(2),
                               lambda:Native(7)+Python(2),lambda:Native(7)-Python(2),
                               lambda:Native(7)*Python(2),lambda:Native(7)**Python(2)]:
                events.clear();print(expression(),events)
        ''')

    def test_subtype_priority_distinguishes_changed_and_inherited_reflected_slots(self):
        self.compare('''
            events=[]
            class Base:
                def __add__(self,other):events.append('base add');return NotImplemented
                def __radd__(self,other):events.append('base radd');return 5
            class Inherited(Base):pass
            class Changed(Base):
                def __radd__(self,other):events.append('changed radd');return 6
            class Alias(Base):__radd__=Base.__radd__
            for cls in [Inherited,Changed,Alias]:
                events.clear();print(Base()+cls(),events)
            class IntBase(int):
                def __add__(self,other):events.append('int add');return 7
            class IntInherited(IntBase):pass
            class IntChanged(IntBase):
                def __radd__(self,other):events.append('int radd');return 8
            for cls in [IntInherited,IntChanged]:
                events.clear();print(IntBase(1)+cls(2),events)
        ''')

    def test_same_type_skips_reflected_and_notimplemented_calls_once(self):
        self.compare('''
            events=[]
            class Left:
                def __add__(self,other):events.append('left');return NotImplemented
                def __radd__(self,other):events.append('left reflected');return 7
            class Right:
                def __radd__(self,other):events.append('right');return NotImplemented
            for other in [Left(),Right()]:
                events.clear()
                try:print(Left()+other)
                except TypeError:print('type error',events)
            class Int(int):
                def __radd__(self,other):events.append('custom');return NotImplemented
            events.clear();print(3+Int(4),events)
            class Same(int):
                def __add__(self,other):events.append('same add');return NotImplemented
                def __radd__(self,other):events.append('same radd');return 77
            events.clear()
            try:print(Same(1)+Same(2))
            except TypeError:print('same type error',events)
        ''')

    def test_float_complex_and_mixed_native_acceptance_ignores_unrelated_reflection(self):
        self.compare('''
            events=[]
            class Integer(int):
                def __radd__(self,other):events.append('radd');return 99
                def __rsub__(self,other):events.append('rsub');return 99
                def __rtruediv__(self,other):events.append('rdiv');return 99
                def __eq__(self,other):events.append('eq');return False
            class NativeComplex(complex):pass
            for value in [3.0,3+0j,NativeComplex(3)]:
                events.clear();print(value+Integer(2),value-Integer(2),value/Integer(2),value==Integer(3),events)
            class NativeInteger(int):pass
            print(NativeInteger(3)+0.5,NativeInteger(3)==3.0,NativeInteger(3)<3.5)
        ''')

    def test_sequence_concat_repeat_and_string_mod_have_distinct_fallback_order(self):
        self.compare('''
            events=[]
            class Left(list):pass
            class Right(list):
                def __radd__(self,other):events.append('radd');return 77
                def __rmul__(self,other):events.append('rmul');return 78
            events.clear();print(Left([1])+Right([2]),events)
            class Index:
                def __index__(self):events.append('index');return 2
                def __rmul__(self,other):events.append('reflected');return NotImplemented
            for sequence in [Left([3]),'a',(3,)]:
                events.clear();print(sequence*Index(),events)
            class Text(str):pass
            class Other:
                def __rmod__(self,other):events.append('rmod');return 99
                def __str__(self):events.append('str');return 'value'
            events.clear();print(Text('%s')%Other(),events)
            class Number(int):
                def __str__(self):events.append('number str');return 'number'
            events.clear();print(Text('%s')%Number(4),events)
            class Tuple(tuple):pass
            print(Tuple([1])+Tuple([2]),Tuple([1])*2,2*Tuple([1]))
        ''')

    def test_inplace_notimplemented_falls_to_normal_slots_without_mutating_old_alias(self):
        self.compare('''
            events=[]
            class List(list):
                def __iadd__(self,other):events.append('iadd');return NotImplemented
                def __add__(self,other):events.append('add');return list.__add__(self,other)
            value=List([1]);alias=value;value += [2]
            print(value,alias,value is alias,type(value).__name__,events)
            class Integer(int):
                def __iadd__(self,other):events.append('integer iadd');return NotImplemented
            events.clear();value=Integer(3);alias=value;value+=2
            print(value,alias,value is alias,type(value).__name__,events)
            class Mixin:
                def __iadd__(self,other):events.append('late iadd');return 99
            class NativeFirst(list,Mixin):pass
            events.clear();value=NativeFirst([1]);alias=value;value += [2]
            print(value,alias,value is alias,type(value).__name__,events)
        ''')

    def test_native_inplace_list_streams_partial_mutations_and_self_alias(self):
        self.compare('''
            events=[]
            class List(list):
                def __iter__(self):events.append('iter');return iter([8])
                def __len__(self):events.append('len');return 9
            value=List([1]);value+=value;print(value,events)
            events.clear();value+=List([2]);print(value,events)
            class Native(list):pass
            value=Native([0]);alias=value
            def source():
                yield 1
                print('during',value)
                yield 2
                raise ValueError('stop')
            try:value += source()
            except ValueError:print(value,alias,value is alias)
            value *= 2;print(value,alias,value is alias)
        ''')

    def test_dictionary_and_set_reflection_inplace_and_shared_identity(self):
        self.compare('''
            events=[]
            class Dict(dict):pass
            class Other(dict):
                def __ror__(self,other):events.append('ror');return {'override':1}
            events.clear();print(Dict(a=1)|Other(b=2),events)
            class Derived(Dict):
                def __ror__(self,other):events.append('derived');return {'derived':1}
            events.clear();print(Dict(a=1)|Derived(b=2),events)
            value=Dict(a=1);alias=value;value |= [('b',2)]
            print(value,alias,value is alias,type(value).__name__)
            class Set(set):pass
            class SetOther(set):
                def __ror__(self,other):events.append('set reflected');return {99}
            events.clear();print(sorted(Set([1])|SetOther([2])),events)
            value=Set([1]);alias=value;value|=SetOther([2]);value&={2};value^={3}
            print(sorted(value),sorted(alias),value is alias,type(value).__name__)
        ''')

    def test_native_rich_comparisons_precede_unrelated_python_right(self):
        self.compare('''
            events=[]
            class Mixin:
                def __eq__(self,other):events.append('eq');return False
                def __ne__(self,other):events.append('ne');return True
                def __gt__(self,other):events.append('gt');return False
            for base,left,right in [(int,1,2),(str,'a','b'),(list,[1],[2]),(tuple,(1,),(2,)),(set,{1},{1,2}),(frozenset,{1},{1,2})]:
                A=type('A',(base,),{});B=type('B',(Mixin,base),{})
                events.clear();print(base.__name__,A(left)==B(left),A(left)!=B(left),A(left)<B(right),events)
                events.clear();print(base.__name__,base(left)==B(left),events)
            class Mapping(dict):pass
            class Other(Mixin,dict):pass
            events.clear();print(Mapping(a=1)==Other(a=1),Mapping(a=1)!=Other(a=1),events)
        ''')

    def test_object_ne_delegates_own_eq_and_comparison_subtypes_have_priority(self):
        self.compare('''
            events=[]
            class Left:
                def __eq__(self,other):events.append('left eq');return False
            class Right:
                def __ne__(self,other):events.append('right ne');return False
            print(Left()!=Right(),events)
            class Base:
                def __lt__(self,other):events.append('lt');return True
                def __gt__(self,other):events.append('gt');return False
            class Sub(Base):pass
            events.clear();print(Base()<Sub(),events)
            class Declined:
                def __eq__(self,other):events.append('declined');return NotImplemented
            value=Declined();events.clear();print(value==value,value!=value,events)
        ''')

    def test_descriptor_lookup_and_function_body_exceptions_are_distinct(self):
        self.compare('''
            events=[]
            class Descriptor:
                def __get__(self,obj,owner):events.append('binding');raise AttributeError('missing')
            class Left:
                __add__=Descriptor()
                __eq__=Descriptor()
            class Right:
                def __radd__(self,other):events.append('right');return 7
                def __eq__(self,other):events.append('right eq');return True
            events.clear();print(Left()+Right(),events)
            events.clear();print(Left()==Right(),events)
            class Raises:
                def __add__(self,other):events.append('body');raise AttributeError('body')
            events.clear()
            try:Raises()+Right()
            except AttributeError:print(events)
            class Static:
                __add__=staticmethod(lambda other: ('static',type(other).__name__))
            class Class:
                __radd__=classmethod(lambda cls,other: ('class',cls.__name__))
            print(Static()+Right(),1+Class())
        ''')

    def test_reflected_native_alias_uses_descriptor_operation_and_receiver(self):
        self.compare('''
            class Left(int):pass
            class Alias(int):
                __rsub__=int.__sub__
            print(Left(10)-Alias(3))
            class Normal:
                def __add__(self,other):return NotImplemented
            class Right(int):__radd__=int.__add__
            try:Normal()+Right(3)
            except TypeError as error:print(type(error).__name__)
        ''')

    def test_mutated_methods_are_resolved_at_the_next_call_and_declines_do_not_unwrap(self):
        self.compare('''
            events=[]
            class Left:
                def __add__(self,other):
                    events.append('left');Right.__radd__=lambda self,other:('new',11)
                    return NotImplemented
            class Right:
                def __radd__(self,other):return 'old'
            print(Left()+Right(),events)
            class Base:
                def __add__(self,other):return 'old add'
            class Sub(Base):
                def __radd__(self,other):
                    Base.__add__=lambda self,other:'new add'
                    return NotImplemented
            print(Base()+Sub())
            class Declined(list):
                def __mul__(self,other):events.append('mul');return NotImplemented
                def __rmul__(self,other):events.append('rmul');return NotImplemented
            for operation in [lambda:Declined([1])*2,lambda:2*Declined([1])]:
                events.clear()
                try:operation()
                except TypeError:print(events)
            class Number(int):
                def __eq__(self,other):return NotImplemented
                def __lt__(self,other):return NotImplemented
                def __gt__(self,other):return NotImplemented
            print(Number(3)==Number(3))
            try:Number(1)<Number(2)
            except TypeError:print('no ordering')
            import sys
            sys.setrecursionlimit(40)
            class Recursive:__eq__=object.__ne__
            try:Recursive()==Recursive()
            except RecursionError:print('comparison recursion')
        ''')

    def test_gc_during_native_sequence_comparison_and_inplace_iteration(self):
        self.compare('''
            import gc
            class List(list):pass
            class Number(int):pass
            class Element:
                def __eq__(self,other):gc.collect();return True
            left,right=List([Element()]),List([Element()])
            print(left==right)
            value=List([])
            def values():
                for number in range(4):
                    gc.collect();yield [Number(number)]
            value+=values();gc.collect();print(value)
            class Removes:
                def __eq__(self,other):left.pop();gc.collect();return True
            left,right=List([Removes(),Element()]),List([0,Element()])
            print(left==right,len(left))
            class Ordered:
                def __eq__(self,other):return False
                def __lt__(self,other):return ['ordered']
            print(List([Ordered()])<List([Ordered()]))
            events=[]
            class Equal:
                def __eq__(self,other):events.append('eq');return True
            class Tuple(tuple):pass
            print(Tuple([Equal()])==(0,1),events)
        ''',integer='bigint')

    def test_wide_native_and_reflected_fixed_width_operations(self):
        self.compare('''
            class Number(int):pass
            class Other(int):
                def __radd__(self,other):return -1
            number=Number(1<<90)
            print(number+Other(3),number<<2,number>>2,number-Other(3),number//Other(3),number%Other(3))
        ''',integer='i128')


if __name__=='__main__':unittest.main()
