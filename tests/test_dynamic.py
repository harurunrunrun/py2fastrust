"""Runtime compilation and AOT/dynamic interoperability against CPython."""

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
def static_twice(value):
    return value * 2
source = sys.stdin.read()
exec(source)
if "dynamic_result" in globals():
    print(static_twice(dynamic_result))
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class DynamicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-dynamic-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="dynamic_wrapper.py"))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(
            ["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=120,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run(
            [sys.executable, "-I", "-c", WRAPPER], input=source,
            capture_output=True, text=True, timeout=15,
        )
        actual = subprocess.run(
            [str(self.binary)], input=source, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(
                actual.stderr.strip().splitlines()[-1].split(":")[0],
                expected.stderr.strip().splitlines()[-1].split(":")[0],
            )
        return actual

    def test_arbitrary_expression_and_aot_calls(self):
        self.compare('''
            expression = "sum(i*i for i in range(10) if i % 2)"
            print(eval(expression))
            def dynamically_defined(x):
                return static_twice(x) + 1
            dynamic_result = dynamically_defined(4)
        ''')

    def test_scope_rebinding_and_unbound_loop(self):
        self.compare('''
            x = 123
            def f():
                for x in []:
                    pass
                return x
            try:
                f()
            except UnboundLocalError:
                print("unbound")
            x = 1
            if True:
                x = "changed"
            for i in range(0):
                x = None
            print(x)
        ''')

    def test_positional_defaults_keyword_defaults_and_closures(self):
        self.compare('''
            def outer(x):
                def f(a, /, b=2, *args, factor=3, **kwargs):
                    nonlocal x
                    x += (a+b+sum(args)+sum(kwargs.values())) * factor
                    return x
                return f
            f = outer(1)
            print(f(2), f(2,4,6,factor=2,extra=3))
            print((lambda a,b=2: a+b)(3))
        ''')

    def test_exec_namespaces_and_function_globals(self):
        self.compare('''
            g = {"x": 2}
            local = {"x": 9}
            exec("y=x; def_placeholder=0", g, local)
            exec("def f():\\n return x\\n", g, local)
            print(local["y"], local["f"]())
            print(eval("x+1", g, local), eval("x+1", g))
            print("__builtins__" in g)
        ''')

    def test_optimized_locals_snapshots(self):
        self.compare('''
            def f():
                x = 1
                snapshot = locals()
                snapshot["x"] = 99
                exec("x=7; new_name=8")
                print(x, snapshot["x"], locals()["x"], "new_name" in locals())
                explicit = {}
                exec("new_name=8", globals(), explicit)
                print(explicit["new_name"])
            f()
        ''')

    def test_compile_eval_exec_and_single(self):
        self.compare('''
            expression = compile("2**8", "expression.py", "eval")
            print(eval(expression))
            exec(compile("answer=37", "statements.py", "exec"))
            print(answer)
            exec(compile("1; None; 2", "interactive.py", "single"))
            print(eval("  4+5  "))
        ''')

    def test_short_circuit_and_comparison_evaluation(self):
        self.compare('''
            seen = []
            def mark(value):
                seen.append(value)
                return value
            print(mark(1) < mark(2) < mark(3), seen)
            seen.clear()
            print(mark(3) < mark(2) < mark(1), seen)
            print(0 and int("bad"), 3 or int("bad"))
            print("yes" if True else int("bad"))
        ''')

    def test_unicode_strings_fstrings_and_literals(self):
        self.compare('''
            日本語 = "日本語🙂"
            print(日本語, 日本語[::-1], len(日本語))
            print(f"{{text}} {len("abc")} {7:04d}", f"{日本語=}")
            print("a" "b", r"\\n", b"\\x41\\101".decode())
            print(0x_ffff, 0b10_10, 1_000.5e-1)
        ''')

    def test_comprehension_scopes_and_named_expressions(self):
        self.compare('''
            x = "outer"
            print([x*x for x in range(5) if x % 2], x)
            print({str(x): x*x for x in range(3)})
            print(sorted({x % 3 for x in range(10)}))
            print([(last := x*2) for x in range(3)], last)
            print([[(i,j) for j in range(2)] for i in range(2)])
            print(sum(x*x for x in range(4)))
            def f():
                print([created := x*2 for x in range(3)], created)
            f()
        ''')

    def test_comprehension_named_expression_scope_errors(self):
        self.compare('''
            invalid = [
                "[x for x in (created := range(3))]",
                "[x for x in (lambda: (created := []))()]",
                "[[outer := inner for inner in [1]] for outer in [1]]",
                "class A:\\n values = [(created := x) for x in [1]]",
            ]
            for source in invalid:
                try:
                    compile(source,"comprehension.py","exec")
                except SyntaxError:
                    print("syntax")
        ''')

    def test_shared_containers_and_augmented_assignment(self):
        self.compare('''
            a = [1]
            shared = a
            a += [2]
            a[0] *= 3
            a *= 2
            print(a, shared, a is shared)
            first, *middle, last = range(5)
            print(first, middle, last)
            print([*[1,2],3], (*range(3),4), {*range(3),4})
            print({**{"x":1}, "x":2})
            print(dict(a=1, **{"b":2}))
        ''')

    def test_unpacking_consumes_iterators_in_python_order(self):
        self.compare('''
            seen = []
            def items():
                seen.append("iterate")
                yield 1
            def mark(label):
                seen.append(label)
                return 2
            def collect(*args, **kwargs):
                return args, kwargs
            print([*items(), mark("list")], seen)
            seen.clear()
            print((*items(), mark("tuple")), seen)
            seen.clear()
            print(collect(*items(), mark("positional")), seen)
            seen.clear()
            print(collect(*items(), key=mark("keyword")), seen)
            seen.clear()
            set = None
            print(sorted({*items(), mark("set")}), seen)
        ''')

    def test_classes_decorators_and_context_managers(self):
        self.compare('''
            def decorator(f):
                def wrapped(*args, **kwargs):
                    return f(*args, **kwargs) + 1
                return wrapped
            class Guard:
                def __enter__(self):
                    print("enter")
                    return 4
                def __exit__(self, kind, error, tb):
                    print("exit", kind is None)
                    return True
                @decorator
                def double(self, value):
                    return value*2
            print(Guard().double(3))
            with Guard() as value:
                print(value)
                raise ValueError("suppressed")
            print("after")
            def f():
                with Guard():
                    return 5
            print(f())
        ''')

    def test_python314_class_namespace_metadata(self):
        self.compare('''
            class Meta(type):
                def __new__(metaclass,name,bases,namespace):
                    print(sorted(namespace.keys()))
                    print(namespace["__firstlineno__"], namespace["__static_attributes__"])
                    return type.__new__(metaclass,name,bases,namespace)
            def identity(cls):
                return cls
            @identity
            class Shape(metaclass=Meta):
                "class documentation"
                def one(obj):
                    obj.excluded = 1
                    self.y = 2
                def two(self):
                    self.z = 3
                    self.augmented += 1
                    self.annotation: int
                    def nested():
                        self.a = 4
                    class Inner:
                        def method(self):
                            self.excluded_from_outer = 5
            print(Shape.__doc__, Shape.__static_attributes__)
        ''')

    def test_python314_lazy_function_annotations(self):
        self.compare('''
            seen=[]
            def resolve():
                seen.append("resolved")
                return int
            def annotated(value:resolve())->str:
                return str(value)
            print(seen)
            annotations=annotated.__annotations__
            print(annotations["value"] is int,annotations["return"] is str,seen)
            print(annotated.__annotations__ is annotations,seen)
            try:
                annotated.__annotate__(3)
            except NotImplementedError:
                print("unsupported format")
            def forward(value:Later): return value
            Later=int
            print(forward.__annotations__["value"] is int)
            class Scoped:
                Type=int
                def method(self,value:Type): return value
            print(Scoped.method.__annotations__["value"] is int)
        ''')

    def test_exception_finally_and_loop_transfers(self):
        self.compare('''
            for i in range(3):
                try:
                    if i == 0:
                        continue
                    if i == 1:
                        break
                finally:
                    print("cleanup",i)
            print("after")
            try:
                for i in range(2):
                    continue
                1//0
            except ZeroDivisionError:
                print("outer handler retained")
            try:
                raise ValueError("message")
            except ValueError as error:
                print(str(error))
            try:
                print(error)
            except NameError:
                print("exception alias cleared")
        ''')

    def test_with_target_assignment_failure_exits_context(self):
        self.compare('''
            class Guard:
                def __enter__(self):
                    print("enter")
                    return [1]
                def __exit__(self, kind, value, tb):
                    print("exit", kind.__name__)
                    return True
            with Guard() as (a,b):
                print("unreachable")
            print("after")
        ''')

    def test_generators_yield_from_and_resume(self):
        self.compare('''
            def g():
                yield 1
                received = yield 2
                print(received)
                yield from [3,4]
            it = g()
            print(next(it), next(it), next(it), list(it))
        ''')

    def test_nested_exception_context_and_finally_transfers(self):
        self.compare('''
            try:
                raise ValueError("outer")
            except ValueError:
                try:
                    1//0
                except ZeroDivisionError:
                    print("inner")
                try:
                    raise
                except ValueError:
                    print("restored")
            def f():
                try:
                    return 1
                finally:
                    try:
                        pass
                    finally:
                        print(2)
                    print(3)
            print(f())
        ''')

    def test_syntax_errors_are_runtime_exceptions(self):
        self.compare('''
            bad_sources = ["x=", "if True:", "for 1 in [2]: pass", "x=1; global x", "nonlocal x", "def f(a,a): pass", "x=1_.0"]
            for source in bad_sources:
                try:
                    compile(source,"bad_dynamic.py","exec")
                except SyntaxError:
                    print("syntax")
        ''')

    def test_match_singletons_sequences_mappings_and_guards(self):
        self.compare('''
            for subject in [1, True, None, [1,2,3], {"a":4,"b":5}, "abc"]:
                match subject:
                    case True:
                        print("true")
                    case 1:
                        print("one")
                    case None:
                        print("none")
                    case [first, *tail] if first == 1:
                        print("sequence", first, tail)
                    case {"a": int(value), **rest}:
                        print("mapping", value, rest)
                    case _:
                        print("other")
            match {"x":7}:
                case {"x": bound} if False:
                    pass
                case _:
                    print("guard binding",bound)
            match = 3
            print(match)
        ''')

    def test_match_or_as_values_and_class_patterns(self):
        self.compare('''
            class Point:
                __match_args__ = ("x","y")
                def __init__(self,x,y):
                    self.x=x
                    self.y=y
            class Constants:
                FIRST = 7
            for subject in [Point(1,2), (3,4), {"x":5}, 7, 8]:
                match subject:
                    case Point(1,y=y) as point:
                        print("point",point.x,y)
                    case [x,y] | {"x":x,"y":y}:
                        print("pair",x,y)
                    case {"x":x}:
                        print("x",x)
                    case Constants.FIRST:
                        print("constant")
                    case int(value):
                        print("integer",value)
            match Point(4,5):
                case Point(x=4,y=value):
                    print("keywords",value)
        ''')

    def test_match_pattern_validation_and_attribute_errors(self):
        self.compare('''
            invalid = [
                "match 1:\\n case [x,x]: pass",
                "match 1:\\n case x|1: pass",
                "match 1:\\n case [x]|[y]: pass",
                "match 1:\\n case [*a,*b]: pass",
                "match 1:\\n case _: pass\\n case 1: pass",
                "match 1:\\n case {1:x, True:y}: pass",
            ]
            for source in invalid:
                try:
                    compile(source,"pattern.py","exec")
                except SyntaxError:
                    print("syntax")
            class Point:
                __match_args__ = ("missing",)
            match Point():
                case Point(value):
                    print("unreachable")
                case _:
                    print("attribute absent")
            try:
                match 1:
                    case int(a,b):
                        pass
            except TypeError:
                print("too many positional")
        ''')


if __name__ == "__main__":
    unittest.main()
