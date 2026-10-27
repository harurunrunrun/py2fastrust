"""Python dictionary protocols at module, global, and built-in boundaries."""

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
def aot_get():
    return dynamic_value
def aot_set(value):
    global dynamic_value
    dynamic_value = value
def aot_delete():
    global dynamic_value
    del dynamic_value
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class GlobalMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-globals-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile(DRIVER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        result = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", DRIVER], input=source,
                                  capture_output=True, text=True, timeout=20)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_globals_accept_arbitrary_hashable_keys_and_retain_references(self):
        self.compare('''
            import gc
            space=globals()
            space[1]={'retained':[7]}
            space[(2,3)]='tuple'
            space[frozenset({4})]='frozen'
            gc.collect()
            print(space[1],space[(2,3)],space[frozenset({4})])
            del space[1]
            print(1 in space,(2,3) in space)
            try:space[[]]=1
            except Exception as error:print(type(error).__name__)
        ''')

    def test_string_subclass_keys_retain_identity_hashes_and_comparison_effects(self):
        self.compare('''
            import gc
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    gc.collect()
                    events.append((str.__str__(self),other))
                    return str.__eq__(self,other)
            key=Key('x')
            space={key:7}
            exec('global x; print(x); x=9',space)
            print(next(iter(space)) is key,space[key])
            exec('global x; del x',space)
            print(events,'x' in space)
        ''')

    def test_aot_functions_use_the_original_module_dictionary(self):
        self.compare('''
            class Key(str):
                __hash__=str.__hash__
                __eq__=str.__eq__
            key=Key('dynamic_value')
            globals()[key]=11
            print(aot_get())
            aot_set(23)
            print(globals()[key],next(k for k in globals() if k=='dynamic_value') is key)
            aot_delete()
            print('dynamic_value' in globals())
        ''')

    def test_global_reads_and_name_fallback_respect_dictionary_subclass(self):
        self.compare('''
            class Space(dict):
                reject=False
                def __getitem__(self,key):
                    print('get',key)
                    if self.reject:raise KeyError(key)
                    return super().__getitem__(key)
                def __setitem__(self,key,value):
                    print('set',key)
                    return super().__setitem__(key,value)
                def __delitem__(self,key):raise RuntimeError('must bypass')
            space=Space(x=7)
            exec('print(x)',space)
            exec('global x; print(x); x=8',space)
            exec('def read(): return x',space)
            print(space['read']())
            read=space['read']
            space.reject=True
            exec('print(x)',space)
            for action in [lambda:read(),lambda:exec('global x; print(x)',space)]:
                try:action()
                except Exception as error:print(type(error).__name__)
            exec('global x; del x',space)
            print('x' in space)
        ''')

    def test_builtin_dictionaries_accept_subclass_keys_and_custom_mappings(self):
        self.compare('''
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):print('eq',other);return str.__eq__(self,other)
            print(eval('answer',{'__builtins__':{Key('answer'):31}}))
            class Builtins(dict):
                def __getitem__(self,key):print('builtin',key);return super().__getitem__(key)
            print(eval('answer',{'__builtins__':Builtins(answer=37)}))
            class Mapping:
                def __getitem__(self,key):
                    if key=='answer':return 41
                    raise KeyError(key)
            print(eval('answer',{'__builtins__':Mapping()}))
            for value in [42,[],{}]:
                try:eval('missing',{'__builtins__':value})
                except Exception as error:print(type(error).__name__)
        ''')

    def test_builtins_module_and_dictionary_share_mutations(self):
        self.compare('''
            import builtins
            print(__builtins__ is builtins,vars(builtins) is builtins.__dict__)
            builtins.transpiler_answer=43
            print(transpiler_answer)
            vars(builtins)[1]=['retained']
            print(vars(builtins)[1])
            del builtins.transpiler_answer
            try:transpiler_answer
            except Exception as error:print(type(error).__name__)
        ''')

    def test_lookup_keyerrors_and_comparison_exceptions_are_distinct(self):
        self.compare('''
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):raise KeyError('comparison')
            for source in ['print(x)','global x; print(x)','def read(): return x\\nread()']:
                try:exec(source,{Key('x'):7})
                except Exception as error:print(type(error).__name__)
        ''')

    def test_module_attribute_operations_share_original_dictionary_keys(self):
        self.compare('''
            import builtins
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    events.append(other)
                    return str.__eq__(self,other)
            key=Key('pytors_module_answer')
            space=vars(builtins)
            space[key]=53
            print(getattr(builtins,'pytors_module_answer'))
            setattr(builtins,'pytors_module_answer',59)
            print(next(k for k in space if k=='pytors_module_answer') is key)
            delattr(builtins,'pytors_module_answer')
            print(events,'pytors_module_answer' in space)
            for action in [lambda:setattr(builtins,'__dict__',{}),
                           lambda:delattr(builtins,'__dict__')]:
                try:action()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_identifier_keys_and_custom_mapping_names_keep_interned_identity(self):
        self.compare('''
            only_name=7
            print(next(k for k in globals() if k=='only_name') is 'only_name')
            def snapshot(x):
                first=locals();second=locals()
                print(next(iter(first)) is next(iter(second)),next(iter(first)) is 'x')
            snapshot(1)
            class Mapping:
                def __getitem__(self,key):
                    print(key is 'wanted')
                    if key=='wanted':return 47
                    raise KeyError(key)
            print(eval('wanted',{},Mapping()))
        ''')
