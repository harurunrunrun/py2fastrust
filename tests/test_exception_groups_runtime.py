"""Exception-group trees preserve public metadata across user callbacks."""
import shutil
import unittest
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExceptionGroupRuntimeTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_native_exception_fields_are_independent_of_args_and_instance_dict(self):
        self.run_source('''
            import gc
            class Stop(StopIteration):pass
            class Exit(SystemExit):pass
            for cls,base,field in [(StopIteration,StopIteration,"value"),(Stop,StopIteration,"value"),
                                   (SystemExit,SystemExit,"code"),(Exit,SystemExit,"code")]:
                payload=[1]
                error=cls(payload)
                print(type(error).__name__,getattr(error,field) is payload,error.args[0] is payload)
                setattr(error,field,3)
                error.args=(4,)
                error.__dict__[field]=99
                gc.collect()
                print(getattr(error,field),error.args,error.__dict__)
                delattr(error,field)
                print(getattr(error,field),error.__dict__)
                base.__init__(error,8,9)
                print(getattr(error,field),error.args)
                BaseException.__init__(error,10)
                print(getattr(error,field),error.args)
        ''')

    def test_system_exit_subclasses_use_the_builtin_exit_status(self):
        self.run_source('''
            class Exit(SystemExit):pass
            error=Exit(7)
            error.code=9
            error.args=(11,)
            raise error
        ''')

    def test_construction_downcast_sequence_identity_and_readonly_fields(self):
        self.run_source('''
            errors=[ValueError('v'),TypeError('t')]
            group=BaseExceptionGroup('message',errors)
            print(type(group).__name__,isinstance(group,Exception),isinstance(group,BaseExceptionGroup))
            print(str(group),repr(group),group.args[1] is errors,group.exceptions is group.exceptions)
            errors.append(KeyError('late'))
            print(repr(group),group.exceptions)
            original=group.exceptions
            group.args=('changed',[])
            print(group.message,group.exceptions is original,str(group),repr(group))
            frozen=(ValueError(),)
            print(ExceptionGroup('x',frozen).exceptions is frozen)
            base=BaseExceptionGroup('base',[SystemExit(2),group])
            print(type(base).__name__,isinstance(base,Exception),base.exceptions)
            for attr in ['message','exceptions']:
                try:setattr(group,attr,None)
                except AttributeError:print('readonly',attr)
            for args in [(),('m',),('m',[]),(1,[ValueError()]),('m',[1]),('m',iter([ValueError()])),('m',{1:ValueError()})]:
                try:ExceptionGroup(*args)
                except (ValueError,TypeError) as e:print(type(e).__name__)
            try:ExceptionGroup('x',[SystemExit()])
            except TypeError as e:print(type(e).__name__)
            class Message(str):
                def __str__(self):
                    print('str message')
                    return 'formatted'
            message=Message('raw')
            group=ExceptionGroup(message,[ValueError()])
            print('constructed',group.message is message)
            try:raise group
            except ExceptionGroup:print('caught')
            print(str(group))
        ''')

    def test_split_subgroup_predicate_order_nested_trees_and_derive(self):
        self.run_source('''
            leaf=ValueError('v')
            nested=ExceptionGroup('inner',[leaf,TypeError('t')])
            group=ExceptionGroup('outer',[nested,OSError('o')])
            events=[]
            def condition(e):
                events.append(type(e).__name__)
                return isinstance(e,ValueError)
            matched,remaining=group.split(condition)
            print(events,repr(matched),repr(remaining))
            print(matched.exceptions[0].exceptions[0] is leaf,
                  group.subgroup(BaseExceptionGroup) is group,
                  group.subgroup(lambda e:False))
            print(repr(group.derive((KeyError('k'),))),group.derive((KeyError(),)).__traceback__)
            for condition in [1,int,(ValueError,1),((ValueError,),)]:
                try:group.split(condition)
                except TypeError as e:print(type(e).__name__)
            try:group.split(lambda e:(_ for _ in ()).throw(RuntimeError('predicate')))
            except RuntimeError as e:print(str(e))
        ''')

    def test_custom_subclasses_derive_gc_and_default_downcast(self):
        self.run_source('''
            import gc
            class Group(ExceptionGroup):
                def __new__(cls,message,exceptions,code):
                    result=super().__new__(cls,message,exceptions)
                    result.code=code
                    return result
                def derive(self,exceptions):
                    gc.collect()
                    print('derive',type(exceptions).__name__,self.code)
                    return Group(self.message,exceptions,self.code)
            group=Group('custom',[ValueError('v'),TypeError('t')],17)
            print(type(group).__name__,group.code,group.args,repr(group))
            group.add_note('note')
            a,b=group.split(ValueError)
            print(type(a).__name__,a.code,type(b).__name__,b.code,a.__notes__)
            class Plain(BaseExceptionGroup):pass
            group=Plain('plain',[ValueError(),SystemExit()])
            print(type(group).__name__)
            a,b=group.split(Exception)
            print(type(a).__name__,type(b).__name__)
            class Bad(ExceptionGroup):
                def derive(self,errors):return ValueError('bad')
            try:Bad('x',[ValueError(),TypeError()]).split(ValueError)
            except TypeError as e:print(type(e).__name__)
        ''')

    def test_notes_cause_context_traceback_and_metadata_copy(self):
        self.run_source('''
            import sys,gc
            group=ExceptionGroup('g',[ValueError(),TypeError()])
            group.add_note('first')
            group.__cause__=KeyError('cause')
            group.__context__=OSError('context')
            try:raise group
            except ExceptionGroup as caught:
                print(sys.exception() is caught,sys.exc_info()[0] is ExceptionGroup,
                      sys.exc_info()[1] is caught,sys.exc_info()[2] is caught.__traceback__)
                a,b=caught.split(ValueError)
                print(a.__traceback__ is caught.__traceback__,b.__traceback__ is caught.__traceback__,
                      a.__cause__ is caught.__cause__,a.__context__ is caught.__context__,
                      a.__suppress_context__,a.__notes__ is caught.__notes__)
                a.__notes__.append('second')
                print(a.__notes__,caught.__notes__)
                gc.collect()
                print(a.exceptions,b.exceptions)
            print(sys.exception(),sys.exc_info())
            print(group.with_traceback(None) is group,group.__traceback__)
            for value in [1,None,[]]:
                try:group.add_note(value)
                except TypeError as e:print(type(e).__name__)
            for notes in [1,'hi',('a','b'),None,[],{'a':1}]:
                group.__notes__=notes
                a,b=group.split(ValueError)
                print(repr(getattr(a,'__notes__','absent')))
            del group.__notes__
            print(hasattr(group,'__notes__'))
        ''')

    def test_called_helpers_and_generator_resume_inherit_active_exception(self):
        self.run_source('''
            import sys
            def current():
                return sys.exception()
            def reraise():
                raise
            def generator():
                yield current()
                try:
                    raise OSError('inside')
                except OSError as caught:
                    yield current() is caught
                yield current()
            try:raise ValueError('creation')
            except ValueError:
                iterator=generator()
            print(next(iterator))
            try:raise TypeError('resume')
            except TypeError as caught:
                print(next(iterator),next(iterator) is caught,current() is caught)
                try:reraise()
                except TypeError as again:print(again is caught)
            print(sys.exception())
            def second():
                yield current()
                yield current()
            iterator=second()
            try:raise KeyError('first resume')
            except KeyError as caught:
                print(next(iterator) is caught)
            print(next(iterator),sys.exception())
        ''')

    def test_ordinary_custom_exception_dictionary_descriptors_slots_and_super(self):
        self.run_source('''
            import gc
            class Descriptor:
                def __get__(self,obj,cls):return obj._stored*2
                def __set__(self,obj,value):obj._stored=value
                def __delete__(self,obj):del obj._stored
            class Custom(ValueError):
                __slots__=('slot',)
                doubled=Descriptor()
                def __init__(self,message):
                    super().__init__(message)
                    self.extra='field'
                    self.slot='slot'
                def __str__(self):return 'custom:'+super().__str__()
                def __repr__(self):return 'repr:'+super().__repr__()
                def __getattr__(self,name):
                    if name=='fallback':return 'fallback'
                    raise AttributeError(name)
            e=Custom('message')
            print(type(e).__name__,isinstance(e,ValueError),e.args,str(e),repr(e))
            dictionary=e.__dict__
            print(dictionary is vars(e),dictionary,e.slot,e.fallback)
            dictionary['extra']='changed'
            e.extra2='second'
            print(e.extra,e.__dict__)
            e.doubled=7
            print(e.doubled,vars(e))
            del e.doubled
            print(hasattr(e,'_stored'))
            del e.slot
            print(hasattr(e,'slot'))
            del e.extra
            print('extra' in dictionary)
            replacement={'x':1}
            e.__dict__=replacement
            print(e.x,e.__dict__ is replacement)
            e.add_note('note')
            print(replacement,e.__notes__ is replacement['__notes__'])
            gc.collect()
            try:raise e
            except ValueError as caught:
                print(caught is e,type(caught).__name__,caught.x)
            class Hook(Exception):
                def __getattribute__(self,name):return super().__getattribute__(name)
                def __setattr__(self,name,value):super().__setattr__(name,value)
                def __delattr__(self,name):super().__delattr__(name)
            other=Hook('hook')
            other.value=3
            print(other.args,other.value,vars(other))
            del other.value
            print(hasattr(other,'value'))
            class Argument:
                def __str__(self):
                    print('argument str')
                    return 'argument'
            argument=Argument()
            other=Hook(argument)
            print('created')
            try:raise other
            except Hook:print('caught')
            print(str(other))
            class Hidden(BaseException):
                def __getattribute__(self,name):
                    if name=='__class__':raise RuntimeError('must use actual type')
                    return super().__getattribute__(name)
            hidden=Hidden('hidden')
            try:BaseExceptionGroup('base',[hidden,ValueError()])
            except RuntimeError as error:print(str(error))
            try:raise hidden
            except Hidden as caught:print(caught is hidden)
        ''')
