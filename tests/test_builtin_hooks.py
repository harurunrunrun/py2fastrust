"""Class and fixed-import hooks use the captured builtins and ordinary calls."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

DRIVER='import sys\nexec(sys.stdin.read())\n'

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class BuiltinHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-builtin-hooks-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root=Path(cls.directory.name)
        cls.binary=cls.build(DRIVER,'driver')
    @classmethod
    def build(cls,source,name,module_paths=(),integer='i64'):
        result=transpile(source,TranspileOptions(optimize=False,module_paths=module_paths,integer=integer))
        if not result.success:raise AssertionError(result.diagnostics)
        path=cls.root/(name+'.rs');path.write_text(result.rust_source)
        binary=cls.root/name
        result=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
        if result.returncode:raise AssertionError(result.stderr)
        return binary
    def compare(self,source,*,aot=False,module_paths=()):
        source=textwrap.dedent(source)
        binary=self.build(source,'aot',module_paths) if aot else self.binary
        # Ignore installed site-package import hooks; compare the standard runtime.
        expected=subprocess.run([sys.executable,'-S','-c',source if aot else DRIVER],input='' if aot else source,capture_output=True,text=True,timeout=20,env=None if not module_paths else dict(os.environ,PYTHONPATH=str(module_paths[0])))
        actual=subprocess.run([str(binary)],input='' if aot else source,capture_output=True,text=True,timeout=20)
        self.assertEqual(expected.returncode,0,expected.stderr)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)

    def test_class_hook_receives_function_keywords_and_arbitrary_result(self):
        self.compare(r'''
            import builtins
            events=[]
            def decorator():
                events.append('decorator')
                def apply(value):events.append(('apply',value));return value
                return apply
            def base():events.append('base');return object
            def keywords():events.append('keywords');return {'value':7}
            def builder(body,name,*bases,**kwargs):
                events.append((body.__name__,name,len(bases),kwargs,body.__builtins__ is old))
                return 23
            old=dict(vars(builtins));old['__build_class__']=builder
            space={'__builtins__':old,'decorator':decorator,'base':base,'keywords':keywords}
            exec('@decorator()\nclass C(base(),**keywords()):\n print("never")',space)
            print(space['C'],events)
        ''')

    def test_class_builder_capture_and_live_dictionary_mutation(self):
        self.compare(r'''
            import builtins
            old=dict(vars(builtins));old['__build_class__']=lambda *args,**kwargs:11
            new=dict(old);new['__build_class__']=lambda *args,**kwargs:22
            space={'__builtins__':old}
            exec('def first():\n class C:pass\n return C',space)
            first=space['first'];space['__builtins__']=new
            exec('def second():\n class C:pass\n return C',space)
            print(first(),space['second']())
            old['__build_class__']=new['__build_class__'];print(first())
        ''')

    def test_class_hook_body_can_run_now_or_be_retained_and_delegated(self):
        self.compare(r'''
            import builtins,gc
            original=builtins.__build_class__;saved=[]
            def builder(body,name,*bases,**kwargs):
                print('body',body.__name__,name)
                saved.append(body)
                print(body())
                return 31
            old=dict(vars(builtins));old['__build_class__']=builder
            space={'__builtins__':old,'print':print}
            exec('class C:\n x=4\n print("inside",locals() is globals())',space)
            print(space['C'],space['x'])
            space['__builtins__']={};gc.collect()
            C=original(saved[0],'Other')
            print(C.__name__,C.x)
        ''')

    def test_class_builder_lookup_before_body_metadata_and_base_expressions(self):
        self.compare(r'''
            import builtins,gc
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):events.append(('lookup',other));gc.collect();return str.__eq__(self,other)
            old=dict(vars(builtins));del old['__build_class__']
            old[Key('__build_class__')]=lambda *args,**kwargs:13
            def base():events.append('base');return object
            space={'__builtins__':old,'base':base}
            exec('class C(base()):pass',space)
            print(space['C'],events)
            for mapping in [None,{}, {'__build_class__':None}]:
                try:exec('class Missing:pass',{'__builtins__':mapping})
                except Exception as error:print(type(error).__name__)
        ''')

    def test_class_hook_standard_delegation_generic_closure_gc_and_aot(self):
        source=r'''
            import builtins,gc,typing
            original=builtins.__build_class__
            def builder(body,name,*bases,**kwargs):
                gc.collect()
                result=original(body,name,*bases,**kwargs)
                print('built',name)
                return result
            builtins.__build_class__=builder
            def outer(value):
                class C[T](**{}):
                    member=value
                    def read(self):return value
                return C
            C=outer(19);gc.collect();print(C.member,C().read(),len(C.__type_params__))
            builtins.__build_class__=original
        '''
        self.compare(source)
        self.compare(source,aot=True)

    def test_selected_builder_survives_globals_key_callback_removal_and_gc(self):
        self.compare(r'''
            import builtins,gc
            original=builtins.__build_class__;armed=[False];events=[]
            class Builder:
                def __call__(self,body,name,*bases,**kwargs):
                    gc.collect();events.append('call')
                    return original(body,name,*bases,**kwargs)
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    if armed[0] and other=='__builtins__':
                        armed[0]=False
                        del old['__build_class__']
                    gc.collect()
                    return str.__eq__(self,other)
            def arm():
                armed[0]=True
                return lambda value:value
            old=dict(vars(builtins));old['__build_class__']=Builder()
            space={Key('__builtins__'):old,'arm':arm}
            exec('@arm()\nclass C:\n value=19',space)
            print(space['C'].value,events)
        ''')

    def test_builder_descriptor_lookup_and_future_callback_values_stay_rooted(self):
        self.compare(r'''
            import gc
            events=[];namespace={}
            class Meta(type):
                @classmethod
                def __prepare__(cls,name,bases):return namespace
            class Descriptor:
                def __init__(self,name):self.name=name
                def __set_name__(self,owner,name):
                    events.append(('set',name))
                    if name=='first':
                        namespace.clear()
                        del owner.second
                    gc.collect()
                def __del__(self):events.append(('del',self.name))
            def function():pass
            function.__set_name__=lambda *args:events.append('must ignore')
            class C(metaclass=Meta):
                first=Descriptor('first')
                second=Descriptor('second')
                member=function
            gc.collect();print(events)
        ''')

    def test_prepare_callback_can_replace_body_code_before_common_call(self):
        self.compare(r'''
            import builtins,gc
            original=builtins.__build_class__;saved=[]
            def replacement():print('replacement')
            class Meta(type):
                @classmethod
                def __prepare__(cls,name,bases):
                    saved[0].__code__=replacement.__code__
                    gc.collect()
                    return {}
            def builder(body,name,*bases,**kwargs):
                saved.append(body)
                return original(body,name,*bases,**kwargs)
            old=dict(vars(builtins));old['__build_class__']=builder
            space={'__builtins__':old,'Meta':Meta}
            exec('class C(metaclass=Meta):print("must not run")',space)
            print(space['C'].__name__)
        ''')

    def test_default_builder_validates_inputs_and_reuses_function_binding(self):
        self.compare(r'''
            import builtins
            def required(value):pass
            def body():return 42
            for args in [(),(1,), (1,'X'), (body,1), (required,'X')]:
                try:builtins.__build_class__(*args)
                except Exception as error:print(type(error).__name__)
            C=builtins.__build_class__(body,'X');print(C.__name__)
            def generator():
                print('must not run')
                yield 1
            C=builtins.__build_class__(generator,'Y');print(C.__name__)
        ''')

    def test_import_hook_signature_aliases_and_original_namespace(self):
        self.compare(r'''
            import builtins
            class Module:pass
            module=Module();module.pi=17;module.templatelib='child'
            def importer(name,global_space,local_space,fromlist,level):
                print(name,global_space is space,local_space is space,fromlist,level)
                return module
            old=dict(vars(builtins));old['__import__']=importer
            space={'__builtins__':old}
            exec('import math as m\nfrom math import pi as p\nimport string.templatelib as t',space)
            print(space['m'] is module,space['p'],space['t'])
        ''')

    def test_import_function_locals_are_none_class_and_module_mappings_live(self):
        self.compare(r'''
            import builtins
            original=builtins.__import__
            def importer(name,g,l,fromlist,level):
                print(name,type(l).__name__,l is g)
                if l is not None and 'local' in l:l['local']=99
                return original(name,g,l,fromlist,level)
            old=dict(vars(builtins));old['__import__']=importer
            space={'__builtins__':old}
            exec('local=3\nimport math\nprint(local)\ndef f():\n local=7\n import math\n locals()\n import math\n print(local)\nf()\nclass C:\n local=8\n import math\n print(local)',space)
        ''')

    def test_captured_importer_replacement_live_mutation_and_tuple_identity(self):
        self.compare(r'''
            import builtins,gc
            import math
            seen=[]
            def first(name,g,l,fromlist,level):
                gc.collect()
                print('first',fromlist is seen[-1] if seen else False)
                seen.append(fromlist)
                return math
            def second(*args):print('second');return math
            old=dict(vars(builtins));old['__import__']=first
            new=dict(old);new['__import__']=second
            space={'__builtins__':old}
            exec('def f():\n for i in range(3):\n  from math import pi\n return pi',space)
            f=space['f'];space['__builtins__']=new
            print(f()>3)
            old['__import__']=second
            print(f()>3)
        ''')

    def test_import_private_names_and_qualified_alias_components(self):
        self.compare(r'''
            import builtins
            class Module:
                def __getattr__(self,name):print('attribute',name);return self
            module=Module()
            def importer(name,g,l,fromlist,level):
                print('import',name,fromlist,level)
                return module
            old=dict(vars(builtins));old['__import__']=importer
            for statement in ['import __a','import __a.b','import a.__b as x','from a import __b','from __a.b import __c']:
                exec('class C:\n '+statement,{'__builtins__':old})
        ''')

    def test_import_lookup_errors_and_from_error_types(self):
        self.compare(r'''
            import builtins
            for mapping in [None,{}, {'__import__':None}]:
                try:exec('import math',{'__builtins__':mapping})
                except Exception as error:print(type(error).__name__)
            class Missing:
                def __getattr__(self,name):
                    if name=='__name__':return 'fake'
                    raise AttributeError(name)
            old=dict(vars(builtins));old['__import__']=lambda *args:Missing()
            for source in ['from math import missing','import string.templatelib as child']:
                try:exec(source,{'__builtins__':old})
                except Exception as error:print(type(error).__name__)
        ''')

    def test_import_star_sequence_protocol_and_original_string_keys(self):
        self.compare(r'''
            import builtins,gc
            events=[]
            class Key(str):__hash__=str.__hash__
            key=Key('pi')
            class Names:
                def __iter__(self):raise RuntimeError('must index')
                def __getitem__(self,index):
                    gc.collect();events.append(index)
                    if index==0:return key
                    raise IndexError(index)
            class Module:pass
            module=Module();module.__all__=Names();module.pi=23
            old=dict(vars(builtins));old['__import__']=lambda *args:module
            space={'__builtins__':old};local={}
            exec('from math import *',space,local)
            print(local['pi'],next(iter(local)) is key,events)
            del module.__all__;module._private=7
            exec('from math import *',space,local)
            print('_private' in local)
        ''')

    def test_default_import_validation_native_strings_and_relative_metadata(self):
        self.compare(r'''
            import builtins
            class Text(str):
                def __str__(self):raise RuntimeError('must bypass')
            class Spec:
                def __init__(self,parent):self.parent=parent
            print(__import__(Text('math')).sqrt(9))
            for args in [(),(1,),('',),('math',None,None,None,-1),('math',None,None,None,1.0),('templatelib',{'__package__':1},None,('Template',),1)]:
                try:__import__(*args)
                except Exception as error:print(type(error).__name__)
            for space in [{'__package__':Text('string')},{'__package__':None,'__spec__':Spec(Text('string'))},{'__name__':'string','__path__':[]}]:
                print(__import__('templatelib',space,None,('Template',),1).__name__)
        ''')

    def test_single_file_all_integer_modes_without_python_on_path(self):
        source=textwrap.dedent('''
            import builtins
            original=builtins.__build_class__
            def builder(body,name,*bases,**kwargs):return original(body,name,*bases,**kwargs)
            builtins.__build_class__=builder
            class C:
                value=7
            from math import sqrt
            print(C.value,sqrt(9))
        ''')
        for integer in ['i64','i128','bigint']:
            with self.subTest(integer=integer):
                binary=self.build(source,'standalone-'+integer,integer=integer)
                result=subprocess.run([str(binary)],input='',capture_output=True,text=True,timeout=20,env=dict(os.environ,PATH=''))
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,'7 3.0\n')

    def test_package_star_import_loads_bundled_all_submodules(self):
        package=self.root/'modules'/'exports'
        package.mkdir(parents=True,exist_ok=True)
        (package/'__init__.py').write_text("__all__=['child']\n")
        (package/'child.py').write_text('value=41\n')
        self.compare(r'''
            if False:import exports.child
            from exports import *
            print(child.value)
        ''',aot=True,module_paths=(package.parent,))

    def test_aot_import_hooks_and_relative_bundled_packages(self):
        package=self.root/'modules'/'sample'
        package.mkdir(parents=True,exist_ok=True)
        (package/'__init__.py').write_text('from . import child\nvalue=child.value\n')
        (package/'child.py').write_text('from .leaf import value\n')
        (package/'leaf.py').write_text('value=37\n')
        self.compare(r'''
            import builtins
            original=builtins.__import__
            def importer(name,g,l,fromlist,level):
                if name.startswith('sample') or level:print('import',name,g['__name__'],fromlist,level)
                return original(name,g,l,fromlist,level)
            builtins.__import__=importer
            import sample.child as alias
            from sample import value
            print(alias.value,value)
            builtins.__import__=original
        ''',aot=True,module_paths=(package.parent,))
