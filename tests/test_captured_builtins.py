"""Captured function/frame builtins, replacement, callback roots and class timing."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

DRIVER = '''\
import sys
def aot_read():
    return len([1, 2, 3])
def aot_make():
    def child():
        return len([1, 2, 3])
    return child
exec(sys.stdin.read())
'''

@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class CapturedBuiltinsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='pytors-builtins-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.binary = cls.build(DRIVER, 'driver')

    @classmethod
    def build(cls, source, name):
        result = transpile(source, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        path = cls.root / (name + '.rs')
        path.write_text(result.rust_source)
        binary = cls.root / name
        built = subprocess.run(['rustc', '--edition=2021', str(path), '-o', str(binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)
        return binary

    def compare(self, source, *, aot=False):
        source = textwrap.dedent(source)
        binary = self.build(source, 'aot') if aot else self.binary
        expected = subprocess.run([sys.executable, '-I', '-c', source if aot else DRIVER],
                                  input='' if aot else source, capture_output=True,
                                  text=True, timeout=20)
        actual = subprocess.run([str(binary)], input='' if aot else source,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_function_snapshot_and_dictionary_mutation(self):
        self.compare(r'''
            import builtins
            old={'tag':'old'}; new={'tag':'new'}
            space={'__builtins__':old,'new':new}
            exec('def first():return tag\n__builtins__=new\ndef second():return tag',space)
            first=space['first']; second=space['second']
            print(first(),second(),first.__builtins__ is old,second.__builtins__ is new)
            old['tag']='mutated'; del space['__builtins__']
            print(first(),second())
            old.clear()
            try:first()
            except NameError:print('missing')
            old['tag']='restored';print(first())
        ''')

    def test_active_frames_and_new_exec_capture_different_mappings(self):
        self.compare(r'''
            import builtins
            old=dict(vars(builtins)); new=dict(old)
            old['marker']='old';new['marker']='new'
            space={'__builtins__':old,'new':new}
            exec(''' + repr('def outer():\n    globals()["__builtins__"]=new\n    print(marker)\n    print(eval("marker"))\n    def child():return marker\n    return child\n') + ''',space)
            child=space['outer']()
            print(child(),child.__builtins__ is new)
            exec('print(marker)',space)
        ''')

    def test_missing_builtins_uses_current_captured_mapping(self):
        self.compare(r'''
            import builtins
            old=dict(vars(builtins)); old['marker']='old'
            space={'__builtins__':old,'other':{}}
            exec(''' + repr('del globals()["__builtins__"]\ndef first():return marker\nexec("def second():return marker",other)') + ''',space)
            print(space['first'].__builtins__ is old,space['first']())
            print(space['other']['__builtins__'] is old,space['other']['second']())
        ''')

    def test_module_normalization_arbitrary_values_and_readonly_attribute(self):
        self.compare(r'''
            import builtins
            for value in [builtins,None,1,'abc',[]]:
                space={'__builtins__':value}
                exec('def f():return missing',space)
                f=space['f']
                print(f.__builtins__ is (vars(builtins) if value is builtins else value))
                try:f()
                except Exception as error:print(type(error).__name__)
                f.__dict__['__builtins__']='shadow'
                print(f.__builtins__ is (vars(builtins) if value is builtins else value))
                for action in [lambda:setattr(f,'__builtins__',{}),lambda:delattr(f,'__builtins__')]:
                    try:action()
                    except Exception as error:print(type(error).__name__,str(error))
        ''')

    def test_builtin_mapping_subclass_and_non_dict_mapping(self):
        self.compare(r'''
            class Space(dict):
                def __getitem__(self,key):
                    print('builtin',key)
                    return super().__getitem__(key)
            class Mapping:
                def __getitem__(self,key):
                    print('mapping',key)
                    if key=='value':return 19
                    raise KeyError(key)
            for mapping in [Space(value=7),Mapping()]:
                space={'__builtins__':mapping}
                exec('def f():return value',space)
                f=space['f'];space['__builtins__']={}
                print(f.__builtins__ is mapping,f())
        ''')

    def test_generator_frame_retains_original_builtins_across_suspension_gc(self):
        self.compare(r'''
            import builtins,gc
            old=dict(vars(builtins));old['marker']='old'
            space={'__builtins__':old}
            exec('def generator():\n yield marker\n yield marker',space)
            g=space['generator']();del space['generator']
            space['__builtins__']={};old=None;gc.collect()
            print(next(g));gc.collect();print(next(g))
            try:next(g)
            except StopIteration:print('done')
        ''')

    def test_function_creation_roots_defaults_and_module_during_key_callbacks(self):
        self.compare(r'''
            import builtins,gc
            events=[]
            class Token:
                def __init__(self,value):self.value=value
                def __del__(self):events.append(self.value)
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    gc.collect()
                    return str.__eq__(self,other)
            class Globals(dict):
                def __getitem__(self,key):
                    if key in ('__name__','__builtins__'):raise RuntimeError('override')
                    return super().__getitem__(key)
            old=dict(vars(builtins));old['marker']=23
            space=Globals({Key('__builtins__'):old,Key('__name__'):'module', 'Token':Token})
            exec('def f(a=Token(1),*,b=Token(2)):\n return a.value,b.value,marker',space)
            f=dict.__getitem__(space,'f')
            print(f(),f.__module__,f.__builtins__ is old,events)
            space.clear();old=None;gc.collect();print(f(),events)
        ''')

    def test_module_object_and_popped_defaults_survive_capture_callback_gc(self):
        self.compare(r'''
            import builtins,gc
            events=[];armed=[False];space={}
            class Token:
                def __init__(self,value):self.value=value
                def __del__(self):events.append(self.value)
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    if armed[0] and other=='__builtins__':
                        armed[0]=False
                        del space[name_key]
                    gc.collect()
                    return str.__eq__(self,other)
            def default(value):
                armed[0]=True
                return Token(value)
            name_key=Key('__name__')
            space={name_key:Token(3),Key('__builtins__'):dict(vars(builtins)), 'default':default}
            exec('def f(a=default(1),*,b=default(2)):return a.value,b.value',space)
            f=space['f'];gc.collect()
            print(f(),f.__module__.value,events)
        ''')

    def test_class_body_capture_precedes_base_prepare_and_mro_callbacks(self):
        self.compare(r'''
            import builtins
            for mode in ['base','mro','prepare']:
                old=dict(vars(builtins));new=dict(old)
                old['stamp']=lambda:'old';new['stamp']=lambda:'new'
                space={'__builtins__':old,'new':new,'mode':mode}
                exec(''' + repr('def swap():\n globals()["__builtins__"]=new\n return object\nclass Base:\n def __mro_entries__(self,bases):return (swap(),)\nclass Meta(type):\n @classmethod\n def __prepare__(cls,name,bases):\n  swap()\n  return {}\nif mode=="base":\n class C(swap()):\n  mark=stamp()\n  def f(self):return stamp()\nelif mode=="mro":\n class C(Base()):\n  mark=stamp()\n  def f(self):return stamp()\nelse:\n class C(metaclass=Meta):\n  mark=stamp()\n  def f(self):return stamp()') + ''',space)
                C=space['C'];print(mode,C.mark,C().f(),C.f.__builtins__ is new)
        ''')

    def test_generic_and_expanded_class_capture(self):
        self.compare(r'''
            import builtins
            old=dict(vars(builtins));new=dict(old)
            old['stamp']=lambda:'old';new['stamp']=lambda:'new'
            space={'__builtins__':old,'new':new}
            exec(''' + repr('def bases():\n globals()["__builtins__"]=new\n return ()\nclass C[T](*bases(),**{}):\n mark=stamp()\n def f(self):return stamp()') + ''',space)
            C=space['C'];print(C.mark,C().f(),C.f.__builtins__ is new)
        ''')

    def test_aot_functions_and_classes_capture_independently(self):
        self.compare(r'''
            import builtins
            old=globals()['__builtins__']
            new=dict(vars(builtins));new['len']=lambda value:73
            before=aot_make()
            globals()['__builtins__']=new
            after=aot_make()
            print(aot_read(),before(),after(),after.__builtins__ is new)
            globals()['__builtins__']=old
        ''')
        self.compare(r'''
            import builtins
            old=dict(vars(builtins));new=dict(old)
            old['stamp']=lambda:'old';new['stamp']=lambda:'new'
            globals()['__builtins__']=old
            def swap():
                globals()['__builtins__']=new
                return object
            class C(swap()):
                mark=stamp()
                def f(self):return stamp()
            print(C.mark,C().f(),C.f.__builtins__ is new)
        ''',aot=True)

    def test_implicit_local_snapshot_survives_builtins_key_collection(self):
        self.compare(r'''
            import builtins,gc
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    gc.collect()
                    return str.__eq__(self,other)
            space={Key('__builtins__'):dict(vars(builtins))}
            exec('def f():\n hidden=[17,23]\n return eval("hidden[0]+hidden[1]")',space)
            print(space['f']())
        ''')

    def test_execution_phase_callbacks_validation_and_snapshot_before_module_lookup(self):
        self.compare(r'''
            import builtins,gc
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    events.append(str.__str__(self))
                    gc.collect()
                    return str.__eq__(self,other)
            def outer():
                cell=1
                def inner():return cell
                return inner
            for operation in [exec,eval]:
                for kind in ['string','bytes','code','syntax','null','type','frees','params']:
                    mode='exec' if operation is exec else 'eval'
                    source={'string':'42','bytes':b'42','code':compile('42','x',mode),
                            'syntax':'!','null':'\0','type':42,
                            'frees':outer().__code__,'params':(lambda arg:arg).__code__}[kind]
                    space={Key('__builtins__'):dict(vars(builtins)),Key('__name__'):'module'}
                    events.clear()
                    try:operation(source,space);status='ok'
                    except Exception as error:status=type(error).__name__
                    print(operation.__name__,kind,status,events)
            for is_code in [False,True]:
                old=dict(vars(builtins));new=dict(old)
                old['marker']='old';new['marker']='new';space={}
                class SwappingKey(str):
                    __hash__=str.__hash__
                    def __eq__(self,other):
                        if other=='__name__':space[builtin_key]=new
                        gc.collect()
                        return str.__eq__(self,other)
                builtin_key=SwappingKey('__builtins__')
                space={builtin_key:old,SwappingKey('__name__'):'module'}
                source=compile('answer=marker','x','exec') if is_code else 'answer=marker'
                exec(source,space)
                print(is_code,space['answer'],eval('marker',space))
        ''')

    def test_suspended_generator_keeps_function_and_internal_module_metadata(self):
        self.compare(r'''
            import builtins,gc
            events=[]
            class Token:
                def __init__(self,name):self.name=name
                def __del__(self):events.append(self.name)
            def source():yield 7
            source.saved=Token('function')
            g=source();del source;gc.collect();print(events)
            print(next(g));gc.collect();print(events)
            del g;gc.collect();print(events)
            events.clear()
            source=(lambda:(yield 11)).__code__
            old=dict(vars(builtins));space={};armed=[True]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    if armed[0] and other=='__name__':
                        armed[0]=False
                        space.clear()
                    gc.collect()
                    return str.__eq__(self,other)
            # The callback must retain its entry for lookup to succeed; replacing
            # builtins from __name__ exercises the captured value across GC.
            space={Key('__name__'):Token('module'),'__builtins__':old}
            armed[0]=False
            g=eval(source,space);space.clear();gc.collect();print(events)
            print(next(g));del g;gc.collect();print(events)
        ''')

    def test_precompiled_function_and_module_code_captures_new_exec_builtins(self):
        self.compare(r'''
            import builtins
            old=dict(vars(builtins));new=dict(old)
            old['marker']='old';new['marker']='new'
            space={'__builtins__':old}
            exec('def f():return marker\ndef g():yield marker',space)
            f=space['f'];g=space['g'];space['__builtins__']=new
            print(f(),eval(f.__code__,space),next(g()),next(eval(g.__code__,space)))
            print(eval(compile('marker','x','eval'),space))
        ''')
