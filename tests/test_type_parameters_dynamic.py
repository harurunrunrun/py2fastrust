"""PEP 695/696 declarations compiled from runtime strings without Python."""

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class DynamicTypeParameterTests(unittest.TestCase):
    maxDiff = None
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-dynamic-types-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile("import sys\nexec(sys.stdin.read())\n",
                           TranspileOptions(filename="dynamic_types.py", optimize=False))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        (root / "main.rs").write_text(result.rust_source, encoding="utf-8")
        compiled = subprocess.run(["rustc", "--edition=2021", str(root / "main.rs"),
                                   "-o", str(root / "main")], capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        cls.executable = root / "main"

    def check_source(self, source):
        source = textwrap.dedent(source)
        actual = subprocess.run([str(self.executable)], input=source,
                                capture_output=True, text=True, timeout=15)
        expected = subprocess.run([sys.executable, "-I", "-c", source],
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                             expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_lazy_alias_cache_evaluators_and_closures(self):
        self.check_source('''
            events = []
            def value():
                events.append(1)
                return int
            type Alias = value()
            print(Alias.__name__, Alias.__module__, Alias.__type_params__, events)
            print(Alias.__value__, Alias.__value__, events)
            print(Alias.evaluate_value(), events)
            type Later = Unknown
            try:
                Later.__value__
            except NameError:
                print("deferred")
            Unknown = str
            print(Later.__value__)
            type Recursive = list[Recursive]
            print(Recursive.__value__.__args__[0] is Recursive)
            def outer():
                local = bytes
                type Local = tuple[local]
                return Local
            print(outer().__value__)
            print("T" in globals())
        ''')

    def test_function_type_parameter_defaults_bounds_and_annotations(self):
        self.check_source('''
            events = []
            def resolve(name, value):
                events.append(name)
                return value
            def identity[T: resolve("bound", int) = resolve("default", str),
                         U: (int, str) = int](value: T) -> U:
                return value, T, U
            T, U = identity.__type_params__
            print(T.__name__, T.__module__, T.__infer_variance__, T.__covariant__, T.__contravariant__)
            print(T.has_default(), U.has_default(), events)
            print(T.__bound__, T.__bound__, T.__default__, events)
            print(U.__constraints__, U.__default__, U.__bound__)
            print(identity(5), identity.__annotations__)
            print(T.evaluate_bound(), T.evaluate_default(), events)
            for evaluate in [T.evaluate_bound, U.evaluate_constraints, T.evaluate_default]:
                try:
                    evaluate(3)
                except NotImplementedError:
                    print("format")
            print("T" in globals(), "U" in globals())
        ''')

    def test_decorators_defaults_recursion_and_parameter_shadowing(self):
        self.check_source('''
            events = []
            T = "outer"
            def decorator(fn):
                events.append("decorate")
                def wrapped(*args):
                    events.append("call")
                    return fn(*args)
                return wrapped
            def default():
                events.append("default")
                return T
            @decorator
            def recurse[T](n=default()):
                if isinstance(n, str):
                    return n
                return 0 if n == 0 else recurse(n - 1) + 1
            print(events, recurse(), recurse(2), events)
            def shadow[T](T):
                return T
            print(shadow(4), shadow.__type_params__[0].__name__, T)
            def outer():
                marker = int
                def inner[T: marker]():
                    return T
                marker = str
                return inner
            print(outer()().__bound__)
        ''')

    def test_generic_class_namespace_bases_and_private_parameters(self):
        self.check_source('''
            class Meta(type):
                def __new__(meta, name, bases, namespace):
                    print(name, list(namespace))
                    return super().__new__(meta, name, bases, namespace)
            class Box[__T = int](metaclass=Meta):
                local = str
                type Nested[U: local] = tuple[__T, U, local]
                def parameter(self):
                    return __T
            print(Box.__type_params__, Box().parameter() is Box.__type_params__[0])
            print(Box.__orig_bases__, Box.__parameters__, Box[str])
            print(Box.Nested.__type_params__[0].__bound__, Box.Nested.__value__)
            print(hasattr(Box, "__T"), hasattr(Box, "_Box__T"))
            class Outer:
                marker = bytes
                class Inner[T: marker]:
                    def get(self):
                        return T
            print(Outer.Inner().get().__bound__)
        ''')

    def test_paramspec_typevartuple_and_starred_defaults(self):
        self.check_source('''
            import typing
            type Alias[**P = [int, str], *Ts = *tuple[int, str]] = tuple[P, *Ts]
            P, Ts = Alias.__type_params__
            print(P.__name__, type(P).__name__, P.__default__, P.args, P.kwargs)
            print(Ts.__name__, type(Ts).__name__, Ts.__default__, Ts.__default__.__unpacked__)
            print(Alias.__value__, Alias.__value__.__parameters__)
            print(hasattr(P, "__bound__"), hasattr(P, "__constraints__"),
                  hasattr(Ts, "__bound__"), hasattr(Ts, "__constraints__"))
            def one[*Ts = *[int]](): pass
            def empty[*Ts = *[]](): pass
            def many[*Ts = *[int, str]](): pass
            def invalid[*Ts = *int](): pass
            print(one.__type_params__[0].__default__)
            for fn in [empty, many, invalid]:
                try:
                    fn.__type_params__[0].__default__
                except (TypeError, ValueError) as error:
                    print(type(error).__name__)
            type Forward[T = U, U = int] = tuple[T, U]
            print(Forward.__type_params__[0].__default__ is Forward.__type_params__[1])
        ''')

    def test_future_annotations_and_dynamic_compilation_modes(self):
        self.check_source('''
            from __future__ import annotations
            def identity[T: int = str](x: T) -> list[T]: return x
            print(identity.__annotations__, identity.__type_params__[0].__bound__)
            type Alias[T] = list[T]
            print(Alias.__value__, Alias[int])
            namespace = {}
            exec(compile("type Other[T = int] = tuple[T]", "alias.py", "exec"), namespace)
            Other = namespace["Other"]
            print(Other.__name__, Other.__value__, Other[()])
            print(eval("Other[int]", namespace))
            class Meta(type):
                def __new__(meta, name, bases, namespace):
                    print(name, "__classdictcell__" in namespace)
                    return super().__new__(meta, name, bases, namespace)
            class StringsOnly(metaclass=Meta):
                def fn(self, value: Missing): pass
            class Evaluated(metaclass=Meta):
                marker = bytes
                type Nested[T: marker = marker] = tuple[T, marker]
                def fn(self, value: Missing): pass
            parameter = Evaluated.Nested.__type_params__[0]
            print(parameter.__bound__, parameter.__default__, Evaluated.Nested.__value__)
            print(StringsOnly.fn.__annotations__)
        ''')

    def test_lazy_class_annotations_and_conditional_execution(self):
        self.check_source('''
            events = []
            def resolve(value):
                events.append(value)
                return value
            class Box[T]:
                field: resolve(T)
                if True:
                    later: list[T]
                if False:
                    skipped: Missing
                for number in range(2):
                    repeated: tuple[T]
                @staticmethod
                def fn(value: T) -> T:
                    return value
            print(events)
            print(Box.__annotations__, events)
            print(Box.__annotations__ is Box.__annotations__)
            print(Box.__annotate__(1), events)
            print(Box.fn.__annotations__)
            print("__conditional_annotations__" in Box.__dict__)
            first: resolve(int)
            if False:
                skipped: Missing
            print(__conditional_annotations__, events)
            print(__annotate__(1), events)
            print(__annotate__(2), events)
        ''')

    def test_nested_scope_shadowing_class_mapping_and_alias_recursion(self):
        self.check_source('''
            class Outer:
                marker = int
                type Local[T: marker = marker] = tuple[T, marker]
                class Inner[U: marker]:
                    type Nested = tuple[U]
                def ordinary(self):
                    type Failure = marker
                    return Failure
            print(Outer.Local.__type_params__[0].__bound__)
            print(Outer.Local.__type_params__[0].__default__)
            print(Outer.Local.__value__, Outer.Inner.Nested.__value__)
            Outer.marker = str
            print(Outer.Local.evaluate_value())
            try:
                Outer().ordinary().__value__
            except NameError:
                print("ordinary scope barrier")
            def outer():
                target = str
                class Class:
                    target = int
                    type Alias = list[target]
                return Class
            print(outer().Alias.__value__)
            def nested[T]():
                def inner[U = T]():
                    return T, U
                return inner
            fn = nested()
            print(fn()[0].__name__, fn()[1].__default__ is fn()[0])
            def rebind[T]():
                T = 7
                return T
            print(rebind())
            type SelfRef[T] = tuple[SelfRef[T], T]
            print(SelfRef.__value__.__args__[0].__origin__ is SelfRef)
        ''')

    def test_invalid_declarations_are_diagnosed_before_execution(self):
        self.check_source('''
            sources = [
                "def f[T,T](): pass",
                "class C[__T,_C__T]: pass",
                "type A[T=int,U] = int",
                "def f[*Ts:int](): pass",
                "def f[**P:int](): pass",
                "type A[T=*tuple[int]] = int",
                "type A = (x:=int)",
                "type A[T:(x:=int)] = int",
                "class C[T]((x:=object)): pass",
                "def f[T]():\\n nonlocal T",
                "type A[T] = (yield int)",
            ]
            for source in sources:
                try:
                    compile(source, "invalid_type.py", "exec")
                except SyntaxError:
                    print("syntax")
                else:
                    print("accepted")
            type Valid = lambda: (x := int)
            print(Valid.__value__())
        ''')
