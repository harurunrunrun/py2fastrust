"""Access and operator callbacks suspend on heap frames, including their fallbacks."""
import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ProtocolAccessTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_recursive_getitem_getattribute_getattr_and_properties(self):
        self.run_source('''
            import sys
            calls=0
            class Item:
                def __getitem__(self,key):
                    global calls
                    calls+=1
                    return self[key]
            class Attribute:
                def __getattribute__(self,name):
                    global calls
                    calls+=1
                    return getattr(self,name)
            class Fallback:
                def __getattr__(self,name):
                    global calls
                    calls+=1
                    return self.missing
            class Property:
                @property
                def x(self):
                    global calls
                    calls+=1
                    return self.x
            for limit in [50,1000,2000]:
                sys.setrecursionlimit(limit)
                for cls in [Item,Attribute,Fallback,Property]:
                    value=cls();calls=0
                    try:
                        if cls is Item:value[0]
                        else:value.x
                    except RecursionError:print(limit,cls.__name__,calls>=limit-1)
        ''')

    def test_recursive_binary_reflected_inplace_and_comparison(self):
        self.run_source('''
            import sys
            calls=0
            class Binary:
                def __add__(self,other):
                    global calls
                    calls+=1
                    return self+other
            class Reflected:
                def __rsub__(self,other):
                    global calls
                    calls+=1
                    return other-self
            class Inplace:
                def __iadd__(self,other):
                    global calls
                    calls+=1
                    self+=other
                    return self
            class Compare:
                def __eq__(self,other):
                    global calls
                    calls+=1
                    return self==other
            for limit in [50,1000,2000]:
                sys.setrecursionlimit(limit)
                for cls in [Binary,Reflected,Inplace,Compare]:
                    value=cls();calls=0
                    try:
                        if cls is Binary:value+1
                        elif cls is Reflected:1-value
                        elif cls is Inplace:value+=1
                        else:value==1
                    except RecursionError:print(limit,cls.__name__,calls)
        ''')

    def test_attribute_fallback_preserves_context_default_and_binding(self):
        self.run_source('''
            import sys,gc
            events=[]
            class Missing:
                def __get__(self,obj,owner):events.append('descriptor');raise AttributeError('primary')
            class Value:
                item=Missing()
                def __getattr__(self,name):
                    events.append(('fallback',name,type(sys.exception()).__name__))
                    gc.collect()
                    if name=='item':return 7
                    raise AttributeError('fallback')
            value=Value()
            try:raise ValueError('outer')
            except ValueError as original:
                print(value.item,events)
                print(getattr(value,'absent',9))
                try:value.absent
                except AttributeError as error:print(error.__context__ is original)
            class Custom:
                def __getattribute__(self,name):raise AttributeError('primary')
                def __getattr__(self,name):raise RuntimeError('fallback')
            try:getattr(Custom(),'x',9)
            except RuntimeError:print('runtime not suppressed')
            class Meta(type):
                @property
                def attr(cls):return cls.__name__
                def __getattr__(cls,name):return ('meta',name)
            class Type(metaclass=Meta):pass
            print(Type.attr,Type.unknown)
        ''')

    def test_default_ne_uses_eq_truth_and_arbitrary_compare_result(self):
        self.run_source('''
            events=[]
            class Truth:
                def __bool__(self):events.append('truth');return True
            result=Truth()
            class Left:
                def __eq__(self,other):events.append('eq');return result
            value=Left()
            print((value==1) is result,events)
            events.clear();print(value!=1,events)
            class RecTruth:
                def __bool__(self):return bool(self)
            class Recursive:
                def __eq__(self,other):return RecTruth()
            try:Recursive()!=1
            except RecursionError:print('recursive inequality truth')
            class Missing:
                def __get__(self,obj,owner):raise AttributeError('binding')
            class Declines:__eq__=Missing()
            value=Declines()
            print(value==value,value==1,value!=1)
        ''')

    def test_mutated_slots_and_subclass_reflection_keep_order(self):
        self.run_source('''
            events=[]
            class Left:
                def __add__(self,other):events.append('forward');return 5
                def __radd__(self,other):events.append('left reverse');return 3
            class Right(Left):
                def __radd__(self,other):events.append('right reverse');return NotImplemented
            print(Left()+Right(),events)
            events.clear()
            class Other:
                def __radd__(self,other):events.append('new reverse');return 7
            def forward(self,other):
                events.append('mutate')
                Other.__radd__=lambda self,other:8
                return NotImplemented
            Left.__add__=forward
            print(Left()+Other(),events)
            class Inplace:
                def __iadd__(self,other):
                    events.append('inplace')
                    Inplace.__add__=lambda self,other:11
                    return NotImplemented
            events.clear();value=Inplace();value+=1
            print(value,events)
        ''')

    def test_recursive_setitem_delitem_setattr_and_delattr(self):
        self.run_source('''
            import sys
            sys.setrecursionlimit(1000)
            class SetItem:
                def __setitem__(self,key,value):self[key]=value
            class DelItem:
                def __delitem__(self,key):del self[key]
            class SetAttr:
                def __setattr__(self,name,value):setattr(self,name,value)
            class DelAttr:
                def __delattr__(self,name):delattr(self,name)
            for operation in [lambda:SetItem().__setitem__(0,1),lambda:DelItem().__delitem__(0),lambda:setattr(SetAttr(),'x',1),lambda:delattr(DelAttr(),'x')]:
                try:operation()
                except RecursionError:print('caught mutation')
        ''')

    def test_dynamic_crossing_nested_gc_and_caller_scope(self):
        self.run_source('''
            import gc,sys
            sys.setrecursionlimit(3000)
            exec('class Dynamic:\\n def __getitem__(self,key):\\n  if key==0:return 7\\n  return self[key-1]')
            value=Dynamic()
            print(value[1200])
            calls=0
            class Descriptor:
                def __get__(self,obj,owner):
                    global calls
                    calls+=1
                    if calls%100==0:gc.collect()
                    return lambda key:obj[key]
            class Recursive:__getitem__=Descriptor()
            try:Recursive()[1]
            except RecursionError:print('descriptor item recursion')
            class Binary:
                def __add__(self,other):
                    try:return NotImplemented
                    except TypeError:print('wrong handler')
            try:Binary()+1
            except TypeError as error:
                names=[];tb=error.__traceback__
                while tb:names.append(tb.tb_frame.f_code.co_name);tb=tb.tb_next
                print(names)
        ''')

    def test_explicit_native_access_and_missing_dict_stay_on_heap(self):
        self.run_source('''
            import sys
            sys.setrecursionlimit(1000)
            class Property:
                @property
                def x(self):return object.__getattribute__(self,'x')
            class Missing(dict):
                def __missing__(self,key):return dict.__getitem__(self,key)
            class ClassItem:
                @classmethod
                def __class_getitem__(cls,key):return cls[key]
            for operation in [lambda:Property().x,lambda:Missing()['x'],lambda:ClassItem[1]]:
                try:operation()
                except RecursionError:print('caught native access')
            events=[]
            class Lookup:
                def __getattr__(self,name):events.append(name);return 7
            try:object.__getattribute__(Lookup(),'missing')
            except AttributeError:print('bypass',events)
            class Set:
                @property
                def x(self):return 1
                @x.setter
                def x(self,value):object.__setattr__(self,'x',value)
            try:Set().x=1
            except RecursionError:print('caught native setter')
        ''')

    def test_explicit_attribute_keys_preserve_subclass_identity(self):
        self.run_source('''
            import functools,gc
            events=[]
            class Key(str):
                def __str__(self):events.append('wrong str');return 'wrong'
            key=Key('name')
            class Value:
                def __getattribute__(self,name):
                    print('get',type(name).__name__,name is key)
                    raise AttributeError('missing')
                def __getattr__(self,name):gc.collect();return name
                def __setattr__(self,name,value):print('set',type(name).__name__,name is key)
                def __delattr__(self,name):print('del',type(name).__name__,name is key)
            value=Value()
            print(getattr(value,key) is key)
            setattr(value,key,7);delattr(value,key)
            operation=functools.partial(getattr,value)
            print(operation(key) is key,events)
        ''')
