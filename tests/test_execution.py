"""compile/eval/exec argument, source-decoding, and namespace effects."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = '''\
import sys
def static_eval(source, space, local):
    return eval(source, globals=space, locals=local)
def static_exec(source, space, local):
    return exec(source, globals=space, locals=local)
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-execution-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        built = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=20)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                             expected.stderr.splitlines()[-1].split(":")[0])

    def test_keyword_namespaces_and_aot_dynamic_calls(self):
        self.compare('''
            g={'x':7}; local={}
            static_exec('y=x+2',g,local)
            print(local['y'], 'y' in g, static_eval('x+y',g,local))
            print(eval('x+3', globals=g))
            exec('z=23', locals=local)
            print(local['z'])
            print(eval(compile('x+2','code.py','eval'),globals=g))
        ''')

    def test_argument_errors_and_no_source_string_coercion(self):
        self.compare('''
            class Source:
                def __str__(self):
                    print('must not coerce')
                    return '1'
            for value in [1, None, [], {}, Source()]:
                for action in [lambda:eval(value),lambda:exec(value),lambda:compile(value,'x','exec')]:
                    try:action()
                    except Exception as error:print(type(error).__name__)
            for action in [lambda:eval(source='1'), lambda:exec('pass',unknown=1),
                           lambda:eval('1',None,None,4), lambda:eval('1',{},globals={}),
                           lambda:exec('pass',closure=()),lambda:exec('pass',closure=None),
                           lambda:exec(compile('pass','x','exec'),closure=())]:
                try:print(action())
                except Exception as error:print(type(error).__name__)
            class Text(str):
                def __str__(self):raise RuntimeError('must not coerce')
            print(eval(Text('2+8')))
        ''')

    def test_bytes_encoding_cookies_bom_and_errors(self):
        self.compare(r'''
            for source in [b'2+3', b'# coding: latin-1\n\'caf\xe9\'',
                           b'# ordinary\r\n# coding: latin-1\r\n\'caf\xe9\'',
                           b'# ordinary\r# coding: latin-1\r\'caf\xe9\'',
                           b'# one\r# two\r# coding: latin-1\r\'caf\xe9\'',
                           b'\xef\xbb\xbf\'snow\'', b'# coding: ascii\n2+7',
                           b'# coding: invalid-codec\n2', b'\xff',
                           b'\xef\xbb\xbf# coding: latin-1\n2']:
                try:print(eval(source))
                except Exception as error:print(type(error).__name__)
            space={}
            exec(compile(b'# coding: latin-1\nx=\'caf\xe9\'','bytes.py','exec'),space)
            print(space['x'])
        ''')

    def test_compile_filename_protocol_and_exact_mode_type(self):
        self.compare(r'''
            class Path:
                def __init__(self, value):self.value=value
                def __fspath__(self):
                    print('path')
                    return self.value
                def __str__(self):raise RuntimeError('must not coerce')
            class Text(str):
                def __str__(self):raise RuntimeError('must not coerce')
            for filename in [Path('valid.py'),Path(b'bytes.py'),Path(12),
                             123,None,b'bytes.py','bad\x00name']:
                try:
                    code=compile('x=19',filename,Text('exec'))
                    space={};exec(code,space);print(space['x'])
                except Exception as error:print(type(error).__name__)
            for mode in [None,b'exec',12,Path('exec'),Text('eval'),'bad','ex\x00ec']:
                try:print(eval(compile('2+3','file.py',mode)))
                except Exception as error:print(type(error).__name__)
        ''')

    def test_compile_conversion_order_and_keyword_only_feature_version(self):
        self.compare('''
            class Number:
                def __init__(self,name,value):self.name=name;self.value=value
                def __index__(self):
                    print('index',self.name)
                    return self.value
                def __bool__(self):
                    print('bool',self.name)
                    return bool(self.value)
            class Path:
                def __fspath__(self):print('path');return 'path.py'
            for mode in ['exec','bad',None]:
                try:
                    compile(123,Path(),mode,Number('flags',0),Number('inherit',1),
                            Number('optimize',-1),_feature_version=Number('feature',-1))
                except Exception as error:print(type(error).__name__)
            for key in ['flags','optimize','_feature_version']:
                for value in [2**40,1.2,'x']:
                    try:compile('pass','file.py','exec',**{key:value})
                    except Exception as error:print(key,type(error).__name__)
            try:compile('pass','file.py','exec',0,False,-1,-1)
            except Exception as error:print(type(error).__name__)
            for flags,optimize,mode in [(1,-2,'bad'),(0,-2,'bad'),(1,-1,'bad')]:
                try:compile(123,'file.py',mode,flags=flags,optimize=optimize)
                except Exception as error:print(type(error).__name__)
        ''')

    def test_globals_subclass_identity_and_native_global_operations(self):
        self.compare(r'''
            class Space(dict):
                def __getitem__(self,key):
                    print('get',key)
                    return super().__getitem__(key)
                def __setitem__(self,key,value):
                    print('set',key)
                    return super().__setitem__(key,value)
            space=Space({'x':2})
            exec('y=x+3',space)
            print(space['y'],'__builtins__' in space)
            exec('global z\nz=19',space)
            print(space['z'])
            exec('global z\ndel z',space)
            print('z' in space)
            space['original']=space
            exec('print(globals() is original, locals() is original)',space)
        ''')

    def test_namespace_validation_and_builtins_insertion_before_errors(self):
        self.compare('''
            for source in [123,'x +']:
                space={}
                try:exec(source,space)
                except Exception as error:print(type(error).__name__,'__builtins__' in space)
            for global_,local in [([],{}),({},7),({},'text'),({},b'text'),({},[]),({},())]:
                try:print(eval('1',global_,local))
                except Exception as error:print(type(error).__name__)
            for local in ['a',b'a',[],(),range(2)]:
                exec('pass',{},local)
                try:eval('missing',{},local)
                except Exception as error:print(type(error).__name__)
            for source in [123, 'x +']:
                try:exec(source,globals=[])
                except Exception as error:print(type(error).__name__)
        ''')

    def test_custom_local_mapping_gc_and_snapshot_locals(self):
        self.compare('''
            import gc
            class Space:
                def __init__(self):self.data={}
                def __getitem__(self,key):
                    gc.collect()
                    print('get',key)
                    return self.data[key]
                def __setitem__(self,key,value):
                    gc.collect()
                    print('set',key)
                    self.data[key]=value
            local=Space()
            exec('x=[3,4]',{},local)
            print(eval('x',{},local))
            def function():
                x=11
                exec('x=23')
                print(x,eval('x'),eval('x',locals={'x':31}))
            function()
        ''')

    def test_global_delete_ignores_dict_subclass_override(self):
        self.compare(r'''
            class Space(dict):
                def __delitem__(self,key):
                    print('must not call global delete override')
                    raise RuntimeError('override')
            space=Space({'x':1})
            exec('global x\ndel x',space)
            print('x' in space)
            for source in ['global missing\ndel missing',
                           'def remove():\n global missing\n del missing\nremove()']:
                try:exec(source,space)
                except Exception as error:print(type(error).__name__)
        ''')

    def test_compile_native_int_payload_and_index_results(self):
        self.compare('''
            import gc
            class Integer(int):
                def __index__(self):raise RuntimeError('must not call override')
                def __int__(self):raise RuntimeError('must not call override')
            class Child(Integer):pass
            class Index:
                def __index__(self):
                    gc.collect()
                    return Child(0)
            for value in [Integer(0),Child(0),Index()]:
                code=compile('2+3','x','eval',value,False,value,_feature_version=value)
                print(eval(code))
            for value in [Integer(1),Child(1)]:
                try:compile('pass','x','exec',flags=value)
                except Exception as error:print(type(error).__name__)
        ''')

    def test_separate_dict_subclass_namespaces_survive_collection(self):
        self.compare('''
            import gc
            class Space(dict):
                def __getitem__(self,key):
                    gc.collect()
                    print('get',key)
                    return super().__getitem__(key)
                def __setitem__(self,key,value):
                    gc.collect()
                    print('set',key)
                    return super().__setitem__(key,value)
            class Child(Space):pass
            for cls in [Space,Child]:
                space=cls({'x':2});local=cls()
                exec('y=x+1',space,local)
                print(local['y'])
                exec('global y;y=x+1',space,local)
                print(space['y'])
        ''')

    def test_code_objects_reject_free_variables_and_required_arguments_before_body(self):
        self.compare('''
            events=[]
            def outer():
                x=1
                def closed(a=2):
                    events.append('closed body')
                    return x+a
                return closed
            def positional(a=1):events.append('positional body');return a
            def keyword(*,x=1):events.append('keyword body');return x
            for function in [outer(),positional,keyword]:
                for operation in [eval,exec]:
                    space={'events':events};local={'a':99,'x':99}
                    try:operation(function.__code__,space,local)
                    except Exception as error:
                        print(function.__name__,operation.__name__,type(error).__name__,'__builtins__' in space)
                    print(local)
            print(events)
        ''')

    def test_code_objects_use_fresh_fast_locals_and_unstarted_generators(self):
        self.compare('''
            events=[]
            def noargs():
                events.append('noargs')
                value=19
                return value
            def star(*args,**kwargs):
                events.append('star')
                return args,kwargs,locals()
            def generator():
                events.append('generator')
                yield 7
            space={'events':events};local={'value':99,'args':[1],'kwargs':{'x':2}}
            print(eval(noargs.__code__,space,local),local)
            print(exec(noargs.__code__,space,local),local)
            print(eval(star.__code__,space,local),local)
            print(exec(star.__code__,space,local),local)
            value=eval(generator.__code__,space,local)
            print(events)
            print(next(value),events)
            print(exec(generator.__code__,space,local),events)
        ''')

    def test_whitespace_cookie_and_primitive_locals_boundaries(self):
        self.compare(r'''
            import gc
            for source in [' 1 ','\t1\t','\f1',' \f 1','\n1\n','1\r','1\r\n',
                           '1\x0b','1\x85','1\u2028','1\\\t','1\\ ',' 1 + ']:
                try:print(repr(source),eval(source))
                except Exception as error:print(repr(source),type(error).__name__)
            class Collect:
                def __call__(self):gc.collect();return 3
            for local in ['abc',b'abc']:
                space={'run':Collect()}
                exec('global run\nrun()',space,local)
                print(eval('1',space,local))
            for prefix in [b' ',b'\t',b'\x0c',b'\v',b'#!one\r',b'#one\r\n',b'1\n',b'\n\n']:
                source=prefix+b"# coding: latin-1\n'caf\xe9'"
                try:print(eval(source))
                except Exception as error:print(type(error).__name__)
        ''')
