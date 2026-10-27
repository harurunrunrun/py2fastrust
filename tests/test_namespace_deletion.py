"""Deletion opcodes distinguish missing names from dictionary callback errors."""

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
def aot_delete_unbound():
    del local
def aot_delete_global():
    global aot_victim
    del aot_victim
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NamespaceDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-namespace-deletion-")
        cls.addClassCleanup(cls.directory.cleanup)
        result = transpile(DRIVER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = Path(cls.directory.name, "main.rs")
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = source.with_suffix("")
        compiled = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", DRIVER], input=source,
                                  capture_output=True, text=True, timeout=20)
        actual = subprocess.run([str(self.binary)], input=source,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_global_deletion_preserves_key_errors_in_all_owning_scopes(self):
        self.compare('''
            import gc
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    events.append(other)
                    gc.collect()
                    raise failure('key callback')
            for failure in (KeyError,ValueError,RuntimeError,KeyboardInterrupt):
                for command in ('global victim; del victim',
                                'del victim',
                                'class C:\\n global victim\\n del victim'):
                    events=[]
                    key=Key('victim')
                    space={key:17}
                    try:exec(command,space)
                    except BaseException as error:
                        print(failure.__name__,type(error).__name__,space[key],events)
        ''')

    def test_aot_deletion_uses_the_original_dictionary_and_local_classification(self):
        self.compare('''
            import gc
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    gc.collect()
                    raise KeyError('aot callback')
            key=Key('aot_victim')
            globals()[key]=29
            try:aot_delete_global()
            except BaseException as error:print(type(error).__name__,globals()[key])
            del globals()[key]
            try:aot_delete_global()
            except BaseException as error:print(type(error).__name__)
            try:aot_delete_unbound()
            except BaseException as error:print(type(error).__name__)
        ''')

    def test_module_attribute_deletion_only_converts_key_errors(self):
        self.compare('''
            import gc
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    gc.collect()
                    events.append(other)
                    raise failure('key callback')
            for failure in (KeyError,ValueError,RuntimeError,KeyboardInterrupt):
                key=Key('namespace_deletion_probe')
                sys.__dict__[key]=23
                events=[]
                try:delattr(sys,'namespace_deletion_probe')
                except BaseException as error:
                    print(failure.__name__,type(error).__name__,sys.__dict__[key],events)
                del sys.__dict__[key]
            try:delattr(sys,'namespace_deletion_probe')
            except BaseException as error:print('missing',type(error).__name__)
        ''')

    def test_unbound_fast_and_free_deletions_are_distinct(self):
        self.compare('''
            def attempt(function):
                try:function()
                except BaseException as error:print(type(error).__name__)
            def unbound():
                del local
            def twice():
                local=7
                del local
                del local
            def parameter(local):
                del local
                del local
            def outer():
                def inner():
                    nonlocal local
                    del local
                if False:local=1
                return inner
            attempt(unbound)
            attempt(twice)
            attempt(lambda:parameter(3))
            attempt(outer())
            attempt(lambda:exec('del absent',{}))
            attempt(lambda:exec('global absent; del absent',{}))
        ''')

    def test_module_annotation_assignment_precedes_cache_deletion_errors(self):
        self.compare('''
            import gc
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    gc.collect()
                    raise failure('annotation callback')
            old=lambda format:{'old':format}
            new=lambda format:{'new':format}
            for failure in (KeyError,ValueError):
                key=Key('__annotations__')
                sys.__dict__.pop('__annotations__',None)
                sys.__dict__['__annotate__']=old
                sys.__dict__[key]={}
                try:sys.__annotate__=new
                except BaseException as error:
                    print(type(error).__name__,sys.__dict__['__annotate__'] is new)
                del sys.__dict__[key]
                del sys.__dict__['__annotate__']
        ''')

    def test_successful_global_removal_updates_views_and_stored_hashes(self):
        self.compare('''
            events=[]
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    events.append(other)
                    return str.__eq__(self,other)
            key=Key('victim')
            space={key:31,'keep':9}
            view=space.keys()
            exec('global victim; del victim',space)
            print(events,list(view),space['keep'])
            space['victim']=41
            print(list(reversed(space)),space['victim'])
            try:exec('global victim; del victim; del victim',space)
            except BaseException as error:print(type(error).__name__)
        ''')
