"""Public closure cells, existing code execution, and shared binding identity."""

import os
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
def static_factory(value):
    def update():
        nonlocal value
        value += 2
        return value
    return update
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ClosureCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-closure-cells-")
        path = Path(cls.tmp.name) / "main.rs"
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        path.write_text(result.rust_source)
        cls.binary = path.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", str(path), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_shared_identity_mutation_deletion_and_local_snapshots(self):
        self.compare('''
            def factory():
                value=3
                def get():return value
                def update():
                    nonlocal value
                    value+=4
                    return value
                def remove():
                    nonlocal value
                    del value
                print(get.__closure__[0].cell_contents,locals()['value'],'value' in dir())
                return get,update,remove
            get,update,remove=factory()
            cell=get.__closure__[0]
            print(get.__closure__ is get.__closure__,cell is update.__closure__[0],cell is remove.__closure__[0])
            print(get(),update(),cell.cell_contents)
            cell.cell_contents='changed';print(get())
            remove()
            for action in [get,lambda:cell.cell_contents]:
                try:action()
                except Exception as error:print(type(error).__name__)
            del cell.cell_contents
            cell.cell_contents=9;print(update(),get())
            for action in [lambda:setattr(get,'__closure__',None),lambda:delattr(get,'__closure__'),lambda:hash(cell)]:
                try:action()
                except Exception as error:print(type(error).__name__)
            get.__dict__['__closure__']='shadow'
            print(get.__closure__[0] is cell,(lambda:None).__closure__ is None)
        ''')

    def test_exec_existing_code_validates_cells_and_shares_mutations(self):
        self.compare('''
            def outer():
                a=2;z=7
                def body():
                    nonlocal z
                    z+=a
                    print(a,z,marker)
                    return 'ignored'
                return body
            body=outer();cells=body.__closure__
            print(body.__code__.co_freevars)
            space={'marker':'code'}
            print(exec(body.__code__,space,{},closure=cells))
            print([cell.cell_contents for cell in cells],'__builtins__' in space)
            exec(body.__code__,space,closure=tuple(reversed(cells)))
            print([cell.cell_contents for cell in cells])
            class Tuple(tuple):pass
            for closure in [None,(),[],(1,),Tuple(cells),(cells[0],1)]:
                try:exec(body.__code__,space,closure=closure)
                except Exception as error:print(type(error).__name__)
            for action in [lambda:eval(body.__code__),lambda:exec('pass',closure=()),
                           lambda:exec(compile('pass','x','exec'),closure=())]:
                try:action()
                except Exception as error:print(type(error).__name__)
            print(exec('pass',closure=None))
        ''')

    def test_replacing_code_rebinds_cells_by_position_and_checks_count(self):
        self.compare('''
            def first():
                x=11
                def body():return x
                return body
            def second():
                y=23
                def body():return y+1
                return body
            f=first();g=second();cells=f.__closure__
            f.__code__=g.__code__
            print(f(),f.__code__.co_freevars,f.__closure__ is cells)
            cells[0].cell_contents=40;print(f())
            plain=lambda:7
            for target,code in [(f,plain.__code__),(plain,g.__code__)]:
                try:target.__code__=code
                except Exception as error:print(type(error).__name__)
            f=static_factory(3);cell=f.__closure__[0]
            print(exec(f.__code__,{},closure=(cell,)),cell.cell_contents,f())
        ''')

    def test_cell_and_function_constructors_accept_shared_cells_and_defaults(self):
        self.compare('''
            import types
            class Tuple(tuple):pass
            class Globals(dict):pass
            def factory():
                a=1;z=4
                def f(step=2):return a+z+step
                return f
            f=factory();a=types.CellType(10);z=types.CellType(20)
            print(type(a) is types.CellType,isinstance(a,types.CellType))
            cells=Tuple((a,z))
            g=types.FunctionType(code=f.__code__,globals=Globals(),name='renamed',argdefs=(5,),closure=cells)
            print(g(),g(1),g.__name__,g.__qualname__,g.__closure__ is cells)
            a.cell_contents=30;print(g())
            g.__code__=f.__code__;print(g(),g.__closure__ is cells)
            print(types.LambdaType is types.FunctionType,type(g) is types.FunctionType)
            empty=types.CellType()
            try:print(empty.cell_contents)
            except Exception as error:print(type(error).__name__)
            empty.cell_contents=None;print(empty.cell_contents)
            del empty.cell_contents;del empty.cell_contents
            plain=lambda:17
            g=types.FunctionType(plain.__code__,{},closure=())
            print(g(),g.__closure__==())
            for action in [lambda:types.FunctionType(f.__code__,{}),
                lambda:types.FunctionType(f.__code__,{},closure=()),
                lambda:types.FunctionType(f.__code__,{},closure=(a,1)),
                lambda:types.CellType(value=2),lambda:types.CellType(1,2)]:
                try:action()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_class_cell_identity_gc_cycles_and_captured_comprehensions(self):
        self.compare('''
            import gc
            saved=[]
            class Meta(type):
                def __new__(m,name,bases,space):
                    saved.append(space['__classcell__'])
                    return super().__new__(m,name,bases,space)
            class Parent:
                def name(self):return 'parent'
            class Child(Parent,metaclass=Meta):
                def name(self):return super().name(),__class__
            print(Child.name.__closure__[0] is saved[0])
            print(Child().name()[0],Child().name()[1] is Child)
            def factory():
                value=[]
                def get():return value
                return get
            f=factory();cells=f.__closure__;value=f();value.append(cells)
            del f,value;gc.collect()
            print(cells[0].cell_contents[0] is cells)
            functions=[lambda:i for i in range(3)]
            print([f() for f in functions],functions[0].__closure__[0] is functions[2].__closure__[0])
            functions[0].__closure__[0].cell_contents=8
            gc.collect();print([f() for f in functions])
        ''')

    def test_standalone_aot_and_dynamic_closures_all_integer_build_modes(self):
        source='''\
from types import CellType, FunctionType
def outer():
    value=4
    def step():
        nonlocal value
        value+=3
        print(value)
    return step
f=outer()
exec(f.__code__,{},closure=f.__closure__)
f.__closure__[0].cell_contents=10
g=FunctionType(f.__code__,{},closure=(CellType(20),))
g();f()
exec("f.__closure__[0].cell_contents=30; f()")
'''
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,check=True).stdout
        for integer in ('i64','i128','bigint'):
            for optimized in (False,True):
                with self.subTest(integer=integer,optimized=optimized):
                    result=transpile(source,TranspileOptions(integer=integer,optimize=False))
                    self.assertTrue(result.success,str(result.diagnostics))
                    path=Path(self.tmp.name)/f'{integer}-{optimized}.rs'
                    path.write_text(result.rust_source)
                    binary=path.with_suffix('')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O'] if optimized else []),str(path),'-o',str(binary)],
                                         capture_output=True,text=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20,
                                          env={**os.environ,'PATH':'/nonexistent'})
                    self.assertEqual(actual.returncode,0,actual.stderr)
                    self.assertEqual(actual.stdout,expected)
