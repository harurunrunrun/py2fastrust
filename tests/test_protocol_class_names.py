"""Class namespace callbacks suspend in the executing class body's frame."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

WRAPPER = "import sys\nexec(sys.stdin.read())\n"

PLAIN_MAPPING = '''
class Space:
    def __init__(self,depth=0):self.depth=depth;self.data={}
    def keys(self):return self.data.keys()
    def __getitem__(self,key):
        if mode=='get' and key=='marker':reenter(self.depth)
        return self.data[key]
    def __setitem__(self,key,value):
        if mode=='set' and key=='value':reenter(self.depth)
        self.data[key]=value
    def __delitem__(self,key):
        if mode=='delete' and key=='gone':reenter(self.depth)
        del self.data[key]
'''

DICT_MAPPING = '''
class Space(dict):
    def __init__(self,depth=0):self.depth=depth
    def __getitem__(self,key):
        if mode=='get' and key=='marker':reenter(self.depth)
        return dict.__getitem__(self,key)
    def __setitem__(self,key,value):
        if mode=='set' and key=='value':reenter(self.depth)
        dict.__setitem__(self,key,value)
    def __delitem__(self,key):
        if mode=='delete' and key=='gone':reenter(self.depth)
        dict.__delitem__(self,key)
'''

RECURSIVE_NAMES = '''
marker=23
stack=[]
mode='get'
def reenter(depth):
    if depth:
        if depth in (300,1):gc.collect()
        make(depth-1 if depth>0 else depth)
class Meta(type):
    @classmethod
    def __prepare__(meta,name,bases):return Space(stack[-1])
    def __new__(meta,name,bases,namespace):
        return super().__new__(meta,name,bases,dict(namespace))
def make(depth):
    stack.append(depth)
    try:
        class Result(metaclass=Meta):
            value=marker
            gone=1
            del gone
        return Result
    finally:stack.pop()
for mode in ('get','set','delete'):
    print(mode,make(300).value)
    try:make(-1)
    except BaseException as error:print(mode,type(error).__name__)
print(stack)
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ProtocolClassNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-class-names-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        target = root / "main.rs"
        target.write_text(result.rust_source)
        cls.binary = target.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=180)
        if built.returncode:
            raise AssertionError(built.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=60)
        actual = subprocess.run([str(self.binary)], input=source,
                                capture_output=True, text=True, timeout=60,
                                env={"PATH": "/nonexistent"})
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_plain_mapping_name_callbacks_finite_300_and_infinite_limit_3000(self):
        self.compare("import sys,gc\nsys.setrecursionlimit(3000)\n"
                     + PLAIN_MAPPING + RECURSIVE_NAMES)

    def test_dict_subclass_name_callbacks_finite_300_and_infinite_limit_3000(self):
        self.compare("import sys,gc\nsys.setrecursionlimit(3000)\n"
                     + DICT_MAPPING + RECURSIVE_NAMES)

    def test_local_keyerror_falls_back_once_to_closure_globals_and_builtins(self):
        self.compare('''
            events=[]
            module_value=77
            tracked=('closed','module_value','len','local','not_defined')
            class Plain:
                def __init__(self):self.data={'local':99}
                def __getitem__(self,key):
                    if key in tracked:events.append(key)
                    return self.data[key]
                def __setitem__(self,key,value):self.data[key]=value
                def __delitem__(self,key):del self.data[key]
            class Derived(dict):
                def __getitem__(self,key):
                    if key in tracked:events.append(key)
                    return dict.__getitem__(self,key)
            def outer(closed,plain):
                class Meta(type):
                    @classmethod
                    def __prepare__(meta,name,bases):
                        return Plain() if plain else Derived(local=99)
                    def __new__(meta,name,bases,namespace):
                        data=namespace.data.copy() if plain else dict.copy(namespace)
                        return super().__new__(meta,name,bases,data)
                class Result(metaclass=Meta):
                    values=(closed,module_value,len([1,2]),local)
                    try:not_defined
                    except NameError:missing=True
                return Result
            for plain in (True,False):
                events.clear();result=outer(31,plain)
                print(result.values,result.missing,events)
        ''')

    def test_delete_name_masks_mapping_exceptions_and_delete_global_preserves_them(self):
        self.compare('''
            import gc
            failure=KeyError
            class Space(dict):
                def __delitem__(self,key):
                    gc.collect();raise failure('namespace deletion')
            class Meta(type):
                @classmethod
                def __prepare__(meta,name,bases):return Space()
            for failure in (KeyError,LookupError,RuntimeError,SystemExit,KeyboardInterrupt,GeneratorExit):
                try:
                    class Result(metaclass=Meta):
                        victim=1
                        del victim
                except BaseException as error:print(failure.__name__,type(error).__name__)
            enabled=False
            class Key(str):
                def __hash__(self):return str.__hash__(self)
                def __eq__(self,other):
                    if enabled:raise LookupError('global key comparison')
                    return str.__eq__(self,other)
            key=Key('victim');namespace={key:41}
            enabled=True
            try:exec('global victim\\ndel victim',namespace)
            except BaseException as error:print('global',type(error).__name__)
        ''')

    def test_setup_annotations_get_missing_then_set_and_existing_mapping(self):
        self.compare('''
            from __future__ import annotations
            import gc
            events=[]
            existing=False
            class Space(dict):
                def __getitem__(self,key):
                    if key=='__annotations__':events.append('get');gc.collect()
                    return dict.__getitem__(self,key)
                def __setitem__(self,key,value):
                    if key=='__annotations__':events.append('set');gc.collect()
                    dict.__setitem__(self,key,value)
            class Meta(type):
                @classmethod
                def __prepare__(meta,name,bases):
                    space=Space()
                    if existing:dict.__setitem__(space,'__annotations__',{'seed':'kept'})
                    return space
            for existing in (False,True):
                events.clear()
                class Result(metaclass=Meta):value:int
                print(events,Result.__annotations__)
            class Broken(Space):
                def __getitem__(self,key):
                    if key=='__annotations__':raise LookupError('annotation lookup')
                    return dict.__getitem__(self,key)
            class Bad(type):
                @classmethod
                def __prepare__(meta,name,bases):return Broken()
            try:
                class Invalid(metaclass=Bad):value:int
            except Exception as error:print(type(error).__name__)
        ''')

    def test_setup_annotations_and_classcell_writes_recurse_through_mapping(self):
        self.compare('''
            from __future__ import annotations
            import sys,gc
            sys.setrecursionlimit(3000)
            stack=[]
            phase='annotations'
            class Space(dict):
                def __init__(self,depth):self.depth=depth
                def __getitem__(self,key):
                    if phase=='annotations' and key=='__annotations__' and key not in self and self.depth:
                        make(self.depth-1)
                    return dict.__getitem__(self,key)
                def __setitem__(self,key,value):
                    if phase=='cell' and key=='__classcell__' and self.depth:make(self.depth-1)
                    if key in ('__annotations__','__classcell__') and self.depth in (0,300):gc.collect()
                    dict.__setitem__(self,key,value)
            class Meta(type):
                @classmethod
                def __prepare__(meta,name,bases):return Space(stack[-1])
            def make(depth):
                stack.append(depth)
                try:
                    class Result(metaclass=Meta):
                        value:int
                        def owner(self):return __class__
                    return Result
                finally:stack.pop()
            for phase in ('annotations','cell'):
                result=make(300)
                print(phase,result().owner() is result,result.__annotations__,stack)
        ''')

    def test_classdict_and_classcell_mapping_callbacks_and_gc_keep_owners(self):
        self.compare('''
            import sys,gc
            sys.setrecursionlimit(3000)
            stack=[]
            trigger='__classdictcell__'
            seen=[]
            class Space(dict):
                def __init__(self,depth):self.depth=depth
                def __setitem__(self,key,value):
                    if key in ('__classdictcell__','__classcell__'):
                        if self.depth in (0,300):seen.append((self.depth,key));gc.collect()
                        if key==trigger and self.depth:make(self.depth-1)
                    dict.__setitem__(self,key,value)
            class Meta(type):
                @classmethod
                def __prepare__(meta,name,bases):return Space(stack[-1])
            def make(depth):
                stack.append(depth)
                try:
                    class Result(metaclass=Meta):
                        field=7
                        def owner(self):return __class__
                        def method(self,value:field):pass
                    return Result
                finally:stack.pop()
            for trigger in ('__classdictcell__','__classcell__'):
                seen.clear();result=make(300)
                print(trigger,result().owner() is result,result.method.__annotations__,seen,stack)
            data=bytearray(b'ab')
            class CollectedSpace(dict):
                def __setitem__(self,key,value):
                    if key=='payload':gc.collect()
                    dict.__setitem__(self,key,value)
            class CollectedMeta(type):
                @classmethod
                def __prepare__(meta,name,bases):return CollectedSpace()
            class Kept(metaclass=CollectedMeta):payload=memoryview(data)
            gc.collect()
            try:data.append(33)
            except Exception as error:print(type(error).__name__)
            del Kept;gc.collect();data.append(34);print(data)
        ''')


if __name__ == "__main__":
    unittest.main()
