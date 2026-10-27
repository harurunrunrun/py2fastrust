"""Lexical qualnames remain independent of mutable function metadata."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

DRIVER = 'import sys\nexec(sys.stdin.read())\n'


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class QualifiedNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='pytors-qualified-names-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.binary = cls.build(DRIVER, 'driver')

    @classmethod
    def build(cls, source, name, integer='i64', module_paths=()):
        result = transpile(source, TranspileOptions(optimize=False, integer=integer,
                                                   module_paths=module_paths))
        if not result.success:
            raise AssertionError(result.diagnostics)
        path = cls.root / (name + '.rs')
        path.write_text(result.rust_source)
        binary = cls.root / name
        result = subprocess.run(['rustc', '--edition=2021', str(path), '-o', str(binary)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stderr)
        return binary

    def compare(self, source, *, aot=False, integer='i64', module_paths=()):
        source = textwrap.dedent(source)
        binary = self.build(source, 'aot-' + integer, integer, module_paths) if aot else self.binary
        env = os.environ.copy()
        if module_paths:
            env['PYTHONPATH'] = os.pathsep.join(map(str, module_paths))
        expected = subprocess.run([sys.executable, '-S', '-c', source if aot else DRIVER],
                                  input='' if aot else source, capture_output=True,
                                  text=True, timeout=20, env=env)
        actual = subprocess.run([str(binary)], input='' if aot else source,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_nested_functions_classes_private_names_and_decorators(self):
        source = '''
            def decorate(value):
                print('decorate', value.__name__, value.__qualname__)
                return value
            @decorate
            def outer():
                @decorate
                class Local:
                    @decorate
                    class __Inner:
                        @decorate
                        def __method(self):
                            @decorate
                            def child(): pass
                            @decorate
                            class Deep: pass
                            return child, Deep
                return Local
            C=outer();D=C._Local__Inner
            f,E=D()._Inner__method()
            print(C.__qualname__,D.__qualname__,f.__qualname__,E.__qualname__)
            print(f.__code__.co_name,f.__code__.co_qualname)
            print(D._Inner__method.__code__.co_name,D._Inner__method.__code__.co_qualname)
        '''
        self.compare(source)
        self.compare(source, aot=True)

    def test_mutated_function_and_class_attributes_do_not_rename_inner_code(self):
        self.compare('''
            import gc
            def outer():
                def child():
                    return lambda: 0
                class Local:
                    def method(self):
                        class Deep: pass
                        return Deep
                return child,Local
            original=outer.__code__.co_qualname
            outer.__qualname__='replacement';outer.__name__='changed';gc.collect()
            f,C=outer()
            C.__qualname__='ChangedClass';f.__qualname__='ChangedFunction'
            print(outer.__qualname__,outer.__code__.co_qualname,original)
            print(f.__qualname__,f.__code__.co_qualname,f().__qualname__)
            print(C.__qualname__,C.method.__qualname__,C().method().__qualname__)
        ''')

    def test_global_and_nonlocal_definition_targets(self):
        self.compare('''
            def outer():
                global published, PublishedClass
                def published():
                    def child(): pass
                    return child
                class PublishedClass:
                    def method(self):pass
                local=None
                def inner():
                    nonlocal local
                    def local():pass
                    return local
                return inner()
            f=outer()
            print(published.__qualname__,published().__qualname__)
            print(PublishedClass.__qualname__,PublishedClass.method.__qualname__,f.__qualname__)
            class Private:
                global __published
                def __published():pass
            print(_Private__published.__qualname__)
            print(compile('pass','module.py','exec').co_name,compile('pass','module.py','exec').co_qualname)
        ''')

    def test_lambdas_nested_comprehensions_and_generator_expressions(self):
        source = '''
            def outer():
                return (lambda:0), [lambda:0 for i in range(1)], {i:(lambda:0) for i in range(1)}, ((lambda:0) for i in range(1)), [(lambda:0 for j in range(1)) for i in range(1)]
            a,b,c,d,e=outer()
            for f in [a,b[0],c[0],next(d),next(e[0])]:
                print(f.__name__,f.__qualname__,f.__code__.co_name,f.__code__.co_qualname)
            class C:
                a=[lambda:0 for i in range(1)]
                b=(lambda:0 for i in range(1))
            print(C.a[0].__qualname__,next(C.b).__qualname__)
        '''
        self.compare(source)
        self.compare(source, aot=True)

    def test_class_body_hook_receives_lexical_metadata_before_runtime_mutation(self):
        source = '''
            import builtins,gc
            old=builtins.__build_class__
            def build(body,name,*bases,**kwargs):
                print('body',body.__name__,body.__qualname__,body.__code__.co_name,body.__code__.co_qualname)
                body.__qualname__='MutatedBody'
                gc.collect()
                return old(body,name,*bases,**kwargs)
            builtins.__build_class__=build
            def outer():
                class Local:
                    class Inner:pass
                    def method(self):pass
                return Local
            outer.__qualname__='ChangedOuter'
            C=outer();builtins.__build_class__=old
            print(C.__qualname__,C.Inner.__qualname__,C.method.__qualname__)
        '''
        self.compare(source)
        self.compare(source, aot=True)

    def test_generic_declarations_and_lazy_annotation_scopes(self):
        source = '''
            def outer():
                class C[T]:
                    def method[U](self):
                        def child():pass
                        return child
                def generic[T: (lambda:0)](x: (lambda:0)):
                    return lambda:0
                def annotated(x: (lambda:0)):pass
                type Alias[T = (lambda:0)] = (lambda:0)
                return C,generic,annotated,Alias
            C,f,g,A=outer()
            print(C.__qualname__,C.method.__qualname__,C().method().__qualname__)
            print(f.__qualname__,f().__qualname__)
            print(f.__type_params__[0].__bound__.__qualname__,f.__annotations__['x'].__qualname__)
            print(g.__annotations__['x'].__qualname__,g.__annotate__.__qualname__)
            print(A.__type_params__[0].__default__.__qualname__,A.__value__.__qualname__)
        '''
        # Supply the sole ordinary parameter without touching annotations.
        source=source.replace('f().__qualname__','f(0).__qualname__')
        self.compare(source)
        self.compare(source, aot=True)

    def test_runtime_compile_exec_eval_all_modes_and_integer_modes(self):
        source = '''
            space={}
            for mode in ['exec','single']:
                code=compile('def outer():\\n class C:\\n  def method(self):pass\\n return C', '<dynamic>',mode)
                exec(code,space)
                C=space['outer']()
                print(mode,C.__qualname__,C.method.__qualname__)
            f=eval(compile('lambda: (lambda:0)','<expression>','eval'))
            print(f.__name__,f.__qualname__,f().__qualname__)
        '''
        for integer in ['i64','i128','bigint']:
            with self.subTest(integer=integer):
                self.compare(source,aot=True,integer=integer)

    def test_direct_build_class_preserves_str_subclass_name_and_gc(self):
        self.compare('''
            import builtins,gc
            class Text(str):
                def __str__(self):raise AssertionError('no conversion')
            name=Text('Target')
            def body():pass
            C=builtins.__build_class__(body,name)
            gc.collect()
            print(type(C.__name__).__name__,C.__name__ is name,C.__qualname__ is name)
            replacement=Text('Renamed')
            C.__name__=replacement
            print(C.__name__ is replacement,C.__qualname__ is name)
            qualified=Text('Outer.Renamed');C.__qualname__=qualified
            del name,replacement,qualified;gc.collect()
            print(type(C.__name__).__name__,C.__name__=='Renamed')
            print(type(C.__qualname__).__name__,C.__qualname__=='Outer.Renamed')
            class Meta(type):
                @classmethod
                def __prepare__(cls,name,bases):return {'__qualname__':42}
            try:builtins.__build_class__(body,'Bad',metaclass=Meta)
            except Exception as error:print(type(error).__name__,str(error))
            try:builtins.__build_class__(body,'bad\\0name')
            except Exception as error:print(type(error).__name__,str(error))
            for value in [body,C]:
                for attribute in ['__name__','__qualname__']:
                    try:delattr(value,attribute)
                    except Exception as error:print(type(error).__name__,str(error))
        ''')


    def test_generator_names_snapshot_function_metadata_and_preserve_subclasses(self):
        source = """
            import gc
            class Text(str):
                def __str__(self):raise AssertionError('no conversion')
            def outer():
                def generate():yield 1
                return generate
            f=outer();name=Text('Current');qualname=Text('Current.Qualified')
            f.__name__=name;f.__qualname__=qualname;g=f()
            print(f.__name__ is name,f.__qualname__ is qualname)
            print(g.__name__ is name,g.__qualname__ is qualname)
            print(g.gi_code is f.__code__,g.gi_code is g.gi_code)
            print(g.gi_code.co_name,g.gi_code.co_qualname)
            f.__name__='Later';f.__qualname__='Later.Qualified'
            print(g.__name__ is name,g.__qualname__ is qualname)
            del name,qualname,f;gc.collect()
            print(type(g.__name__).__name__,g.__name__=='Current')
            print(type(g.__qualname__).__name__,g.__qualname__=='Current.Qualified')
            print(next(g));g.close();gc.collect()
            print(g.__name__=='Current',g.gi_code.co_qualname)
        """
        self.compare(source)
        self.compare(source,aot=True)

    def test_generator_names_mutate_while_running_and_survive_suspension(self):
        self.compare("""
            import gc
            def f():
                g.__name__='Running';g.__qualname__='Running.Qualified'
                gc.collect()
                yield (g.__name__,g.__qualname__)
                gc.collect()
                yield (g.__name__,g.__qualname__)
            g=f();print(next(g),g.__name__,g.__qualname__)
            g.__name__='Paused';g.__qualname__='Paused.Qualified'
            gc.collect();print(next(g),g.__name__,g.__qualname__)
            g.close();print(g.__name__,g.__qualname__)
            def renamable(x):yield x
            class Key(str):
                __hash__=str.__hash__
                def __eq__(self,other):
                    renamable.__name__='Callback';renamable.__qualname__='Callback.Qualified'
                    gc.collect();return str.__eq__(self,other)
            h=renamable(**{Key('x'):3})
            print(h.__name__,h.__qualname__,next(h))
            iterator=(item for item in range(1))
            print(iterator.__name__,iterator.__qualname__,iterator.gi_code.co_name,iterator.gi_code.co_qualname)
        """)

    def test_generator_metadata_validation_and_code_replacement_independence(self):
        self.compare("""
            def first():yield 1
            def second():yield 2
            g=first();code=g.gi_code
            first.__code__=second.__code__
            print(g.gi_code is code,g.gi_code is first.__code__,next(g),next(first()))
            for name in ['__name__','__qualname__','gi_code']:
                try:setattr(g,name,42)
                except Exception as error:print(name,type(error).__name__,str(error))
                try:delattr(g,name)
                except Exception as error:print('del',name,type(error).__name__,str(error))
        """)


    def test_precompiled_generator_expression_requires_iterator_and_closure_first(self):
        self.compare("""
            iterator=(item for item in range(1));code=iterator.gi_code
            def outer():
                captured=3
                return (item+captured for item in range(1))
            closure_code=outer().gi_code
            for selected in [code,closure_code]:
                for operation in [eval,exec]:
                    space={};local={'.0':iter([7])}
                    try:operation(selected,space,local)
                    except Exception as error:
                        print(operation.__name__,type(error).__name__,'__builtins__' in space)
                        print('free' if 'free' in str(error) or 'closure' in str(error) else 'argument')
            def generate():yield 4
            generated=eval(generate.__code__)
            print(generated.__name__,generated.__qualname__,next(generated))
        """)

    def test_code_identity_survives_gc_only_while_owned(self):
        self.compare("""
            import gc
            def f():yield 1
            initial=id(f.__code__);gc.collect();print(id(f.__code__)==initial)
            g=f();saved=g.gi_code
            def other():yield 2
            f.__code__=other.__code__;del saved;gc.collect()
            print(id(g.gi_code)==initial,next(g),next(f()))
            # Exercise reclaimed code-object slots and fresh dynamic code IDs.
            for i in range(30):
                code=compile('pass','temporary','exec');del code;gc.collect()
            print(g.gi_code.co_name,id(g.gi_code)==initial)
            def factory():
                def child():pass
                return child
            saved=factory().__code__;gc.collect()
            print(factory().__code__ is saved)
            outer_code=factory.__code__;del factory;gc.collect()
            print(eval(outer_code).__code__ is saved)
        """)


    def test_active_frames_keep_nested_code_identity_after_owner_replacement(self):
        source = """
            import gc
            def replacement():pass
            def outer():
                previous=None
                for i in range(2):
                    def child():pass
                    if i==0:
                        previous=id(child.__code__);del child
                        outer.__code__=replacement.__code__
                        gc.collect()
                        temporary=compile('pass','temporary','exec')
                    else:print(id(child.__code__)==previous)
            outer()
            previous=None
            for i in range(2):
                def module_child():pass
                if i==0:
                    previous=id(module_child.__code__);del module_child;gc.collect()
                    temporary=compile('pass','temporary','exec')
                else:print(id(module_child.__code__)==previous)
        """
        self.compare(source)
        self.compare(source,aot=True)


class FrontendQualifiedNameTests(unittest.TestCase):
    def test_scope_metadata_matches_official_code_objects(self):
        import types
        from collections import Counter
        from py2fastrust.compiler import Compiler
        source = textwrap.dedent('''
            def outer():
                class C[T]:
                    def __method[U](self, value: (lambda:0)):
                        return lambda:0
                def generic[T: (lambda:0) = (lambda:0)]():pass
                def annotated(x: (lambda:0)):pass
                type Alias[T] = (lambda:0)
                return [lambda:0 for i in range(1)], ((lambda:0) for i in range(1))
            def publishing():
                global published, Published
                def published():pass
                class Published:pass
        ''')
        expected = Counter()
        def visit(code):
            if code.co_name != '<module>':
                expected[code.co_name, code.co_qualname] += 1
            for child in code.co_consts:
                if isinstance(child, types.CodeType):
                    visit(child)
        visit(compile(source, '<qualified-source>', 'exec'))
        program = Compiler(filename='<qualified-source>').compile(source)
        actual = Counter((code.name, code.qualname) for code in program.codes
                         if code.filename == '<qualified-source>'
                         and code.kind != 'Module'
                         and not (code.kind == 'Comprehension' and not code.is_generator))
        self.assertEqual(actual, expected)
