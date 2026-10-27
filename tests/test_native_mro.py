"""Native base members participate in explicit attribute and construction MRO."""

import shutil
import textwrap
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeMroTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source, **kwargs):
        source = textwrap.dedent(source)
        return self.run_source(source + "\nexec(" + repr(source) + ", {})\n", **kwargs)

    def test_inherited_new_initialization_and_collections_factory_slot(self):
        self.compare('''
            from collections import defaultdict,Counter,OrderedDict
            for base,argument in [(dict,{'x':3}),(list,[2,3]),(tuple,[2,3]),(set,[7]),
                                  (frozenset,[7]),(str,'text'),(int,'43'),(complex,2)]:
                class Child(base):pass
                value=Child.__new__(Child,argument)
                print(base.__name__,Child.__new__ is base.__new__,type(value) is Child)
                Child.__init__(value,argument)
                print(value,Child.__init__.__objclass__.__name__)
                print(Child(argument))
            for base in [defaultdict,Counter,OrderedDict]:
                value=base.__new__(base)
                print(type(value).__name__,len(value),base.__new__ is dict.__new__)
                if base is defaultdict:print(value.default_factory)
        ''')

    def test_native_definition_precedes_later_python_mixin(self):
        self.compare('''
            events=[]
            class Mixin:
                @staticmethod
                def __new__(cls,*args,**kw):events.append('new');return dict.__new__(cls)
                def __init__(self,*args,**kw):events.append('init')
                def get(self,key,default=None):return 'mixin'
                def append(self,value):return 'mixin append'
            class NativeFirst(dict,Mixin):pass
            class PythonFirst(Mixin,dict):pass
            first=NativeFirst(a=3);second=PythonFirst(a=3)
            print(events,dict(first),dict(second))
            print(first.get('a'),NativeFirst.get(first,'a'),second.get('a'))
            print(first.append(1),NativeFirst.__new__ is dict.__new__,PythonFirst.__new__ is Mixin.__new__)
            print(NativeFirst.__init__.__objclass__ is dict,PythonFirst.__init__ is Mixin.__init__)
            class ListMixin:
                def append(self,value):events.append('mixin append')
                def copy(self):return 'mixin copy'
            class Values(list,ListMixin):pass
            value=Values([2]);value.append(4)
            print(value,value.copy(),Values.append.__objclass__ is list,events)
        ''')

    def test_python_new_descriptor_forms_foreign_returns_and_no_double_init(self):
        self.compare('''
            events=[]
            class Auto(list):
                def __new__(cls,*args,**kw):events.append('auto new');return list.__new__(cls)
                def __init__(self,values):events.append('auto init');super().__init__(values)
            class Static(dict):
                @staticmethod
                def __new__(cls,*args,**kw):events.append('static new');return dict.__new__(cls)
                def __init__(self,*args,**kw):events.append('static init');super().__init__(*args,**kw)
            class ClassNew:
                @classmethod
                def __new__(bound,explicit,value):
                    events.append(('class new',bound is explicit));return object.__new__(explicit)
                def __init__(self,value):events.append(('class init',value))
            a=Auto([1,2]);b=Static(x=7);c=ClassNew(9)
            print(a,b,type(c).__name__,events)
            print(isinstance(Auto.__dict__['__new__'],staticmethod),a.__new__ is Auto.__new__)
            class Foreign:
                def __new__(cls,value):events.append(('foreign new',value));return [value]
                def __init__(self,value):events.append('must not initialize')
            print(Foreign(11),events)
            class Parent:
                def __new__(cls,value):return object.__new__(Child)
                def __init__(self,value):events.append('wrong parent init')
            class Child(Parent):
                def __init__(self,value):events.append(('child init',value))
            print(type(Parent(13)).__name__,events)
            class Generic[T]:
                def __init__(self,value):self.value=value
            value=Generic[int](17)
            print(type(value) is Generic,value.value)
        ''')

    def test_native_descriptors_bind_actual_owner_and_validate_receivers(self):
        self.compare('''
            class D(dict):pass
            class L(list):pass
            d=D(x=7);values=L([1])
            print(D.get.__objclass__ is dict,D.get.__name__,D.get.__qualname__)
            print(d.get.__self__ is d,d.get.__qualname__,d.get('x'))
            print(D.__new__.__self__ is dict,D.__new__.__qualname__)
            print(D.__init__.__objclass__ is dict,d.__init__.__objclass__ is dict)
            function=dict.get.__get__(d,D)
            print(function.__self__ is d,function('x'),dict.get.__get__(None,list) is dict.get)
            list.append.__get__(values,L)(3)
            print(values,list.copy(values))
            print(str.__repr__('é'),int.__repr__(23),dict.__repr__(d))
            class S(set):
                def __repr__(self):return 'custom repr'
            value=S([7]);print(set.__repr__(value),repr(value))
            for owner,name in [(dict,'append'),(list,'get'),(tuple,'copy')]:
                try:getattr(owner,name)
                except Exception as error:print(type(error).__name__)
            for operation in [lambda:dict.get.__get__(values,L),lambda:D.get(values,'x'),
                              lambda:L.append(d,2),lambda:D.__init__(values),
                              lambda:D.__new__(L),lambda:object.__new__(D),
                              lambda:object.__new__(3)]:
                try:operation()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_fromkeys_and_class_getitem_use_accessing_subtype(self):
        self.compare('''
            events=[]
            class D(dict):
                def __init__(self,*a,**kw):events.append('init');super().__init__(*a,**kw)
                def __setitem__(self,key,value):events.append(('set',key));super().__setitem__(key,value)
            value=D.fromkeys('aba',[])
            print(type(value) is D,events,list(value),value['a'] is value['b'])
            print(D.fromkeys.__self__ is D,value.fromkeys.__self__ is D,D.fromkeys.__qualname__)
            for base in [dict,list,tuple,set,frozenset]:
                class Child(base):pass
                alias=Child[int]
                print(alias.__origin__ is Child,alias.__args__)
        ''')

    def test_super_and_metaclass_data_descriptors_respect_mro(self):
        self.compare('''
            events=[]
            class Meta(type):
                @property
                def label(cls):return 'metaclass data'
                def __new__(mcls,name,bases,space):
                    events.append(('meta new',name));return super().__new__(mcls,name,bases,space)
                def __init__(cls,name,bases,space):
                    events.append(('meta init',name));super().__init__(name,bases,space)
            class Mixin:
                def get(self,key,default=None):return 'mixin'
            class D(dict,Mixin,metaclass=Meta):
                label='class value'
                def get(self,key,default=None):return super().get(key,default)
            d=D(x=5)
            print(D.label,d.get('x'),events)
            try:D.label='replacement'
            except Exception as error:print(type(error).__name__)
            print(super(D,d).get.__self__ is d,super(D,d).__new__ is dict.__new__)
            print([value.__name__ for value in type.mro(D)])
            class ReadMeta(type):
                def __getattribute__(cls,name):return type.__getattribute__(cls,name)
            class Values(list,metaclass=ReadMeta):pass
            print(Values.__new__ is list.__new__,Values([2,4]))
        ''')

    def test_native_data_members_precede_instance_dictionary(self):
        self.compare('''
            class Value(complex):pass
            value=Value(2,3)
            value.__dict__['real']=99
            print(value.real,value.imag,Value.real.__objclass__ is complex)
            print(Value.real.__get__(value,Value))
            for operation in [lambda:setattr(value,'real',7),lambda:delattr(value,'real'),
                              lambda:Value.real.__get__([],Value)]:
                try:operation()
                except Exception as error:print(type(error).__name__)
            class Override(complex):
                @property
                def real(self):return 'python property'
            print(Override(2,3).real)
        ''')

    def test_plain_object_constructor_argument_rules(self):
        self.compare('''
            class Plain:pass
            class Init:
                def __init__(self,*args,**kw):pass
            class New:
                def __new__(cls,*args,**kw):return object.__new__(cls)
            class Both(New,Init):pass
            for cls in [object,Plain,Init,New,Both,tuple,list]:
                for mode in ['new','init']:
                    try:
                        if mode=='new':value=object.__new__(cls,5,x=7)
                        else:
                            value=object.__new__(cls) if cls not in [tuple,list] else cls()
                            value=object.__init__(value,5,x=7)
                        print(cls.__name__,mode,'ok')
                    except Exception as error:print(cls.__name__,mode,type(error).__name__)
        ''')



    def test_string_base_slots_preserve_protocols_and_conversion_identity(self):
        self.compare(r'''
            import gc
            base=''.join(['native',' key'])
            events=[]
            class Child(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    events.append('eq');gc.collect();return str.__eq__(self,other)
                def __str__(self):raise AssertionError('override str')
                def __repr__(self):raise AssertionError('override repr')
            child=Child(base)
            print(str.__str__(base) is base,str.__str__(child) is base)
            print(str.__str__(child) is str.__str__(child))
            print(hash(child)==hash(base),str.__hash__.__get__(child,Child)()==hash(base))
            print(str.__eq__(child,base),str.__ne__(child,base))
            print(str.__eq__(child,1) is NotImplemented,str.__ne__(child,1) is NotImplemented)
            mapping={child:7}
            print(mapping[base],events)
            print(str.__repr__(child),str.__str__(child),Child.__hash__ is str.__hash__)
            for action in [lambda:str.__hash__(1),lambda:str.__hash__(base,1),
                           lambda:str.__eq__(base),lambda:str.__ne__(base,base,1),
                           lambda:str.__str__(base,unused=1)]:
                try:action()
                except Exception as error:print(type(error).__name__)
        ''')


if __name__ == '__main__':unittest.main()
