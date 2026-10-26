"""Python 3.14 future statements and inherited dynamic compiler flags."""

import __future__
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class FutureTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def both_paths(self, source):
        source = textwrap.dedent(source)
        self.run_source(source + "\nexec(" + repr(source) + ", {})\n")

    def test_feature_bindings_aliases_and_releases(self):
        self.both_paths('''
            u"module documentation"
            from __future__ import (nested_scopes, generators, division as divide,
                                    absolute_import, with_statement, print_function,
                                    unicode_literals, generator_stop, annotations as strings)
            import __future__ as future
            print(future.all_feature_names)
            for name in future.all_feature_names:
                feature = getattr(future, name)
                print(name, feature.compiler_flag, feature.getOptionalRelease(), feature.getMandatoryRelease())
            print(divide is future.division, strings is future.annotations)
            print(nested_scopes, generators, absolute_import, with_statement)
            print(print_function, unicode_literals, generator_stop)
        ''')

    def test_stringized_function_module_and_class_annotations(self):
        self.both_paths('''
            from __future__ import annotations
            seen = []
            def resolve():
                seen.append(1)
                raise ValueError("must not evaluate")
            alpha: resolve()
            assigned: list [ int ] = 7
            class Example:
                __item: Missing
                def f(self, __value: resolve(), /, *items: tuple[int], key: "Forward"=None, **kw: dict[str,int])->list[int | str]:
                    local: resolve()
                    return __value
            def f(x: Missing)->None:
                ignored: Missing
                return x
            print(__annotations__, Example.__annotations__)
            print(Example.f.__annotations__, f.__annotations__, seen)
            print(f(3), hasattr(f, "__annotate__"))
            for mode in [0, 1, 2]:
                print(f.__annotate__(mode))
            print(f.__annotate__.__name__, f.__annotate__.__qualname__)
            try:
                f.__annotate__(format=1)
            except TypeError:
                print("positional format only")
            try:
                f.__annotate__(3)
            except NotImplementedError:
                print("unsupported annotation format")
        ''')

    def test_annotation_expression_canonical_strings(self):
        expressions = [
            "list[ int ]", "'Forward'", 'u"Forward"', 'U"Forward"', "u'a' 'b'", "'a' u'b'", "...", "Ellipsis",
            "0xff", "1e999", "1e-7", "1j", "1.0j", "01j", "0_01j", "1e999j", "1 + 2j", "-0j", "a + (b + c)", "(a + b) * c",
            "a ** b ** c", "(a ** b) ** c", "a ** (-b)", "not a and b or c",
            "a < b <= c", "(a if b else c) if d else e", "lambda: 1",
            "lambda a=1, /, *items, key=2, **kw: a", "f(x for x in a)",
            "lambda:(yield 1)", "lambda:(value:=1)",
            "[a for a,b in c if a if b]", "{a: b for a,b in c}",
            "a[b,]", "a[()]", "a[1:2:3]", "f(*a, **b)",
            '{"a": 1, **m}', 'f"item={value!r:>8}"', 'f"{\'a\'}"', 'f""', 'f"{ value + other }"',
            't"hello { a + b }"', 't"hello {a+b!r:>{width}}"', 'rt"line\\n{x}"',
            't"{\'a\'}"', 't""', 't"a{x}" t"b{y}"', 't"{ x = }"', 't"{ K + 1 }"',
        ]
        source = "from __future__ import annotations\n"
        for index, expression in enumerate(expressions):
            source += f"def f{index}(x: {expression}) -> {expression}: pass\n"
            source += f"print(f{index}.__annotations__)\n"
        self.both_paths(source)

    def test_annotation_mapping_setup_and_assignment_order(self):
        self.both_paths('''
            from __future__ import annotations
            if False:
                never: Missing
            print(__annotations__, __conditional_annotations__)
            __annotations__["old"] = "kept"
            exec("from __future__ import annotations\\nnew: Missing", globals())
            print(__annotations__)
            class Example:
                __annotations__ = {"old": "kept"}
                x: int = 5
                (ignored): Missing
                if False:
                    never: Missing
            print(Example.x, Example.__annotations__)
            class Derived(Example):
                pass
            annotations = Derived.__annotations__
            print(annotations, Derived.__annotations__ is annotations, Derived.__annotate__)
            print(Example.__annotations__)
            seen = []
            def receiver():
                seen.append("object")
                return None
            def index():
                seen.append("index")
                return 0
            receiver().attribute: Missing
            receiver()[index()]: Missing
            print(seen)
            space = {"__annotations__": None}
            try:
                exec("from __future__ import annotations\\nx: int = 42", space)
            except TypeError:
                print(space["x"], space["__annotations__"])
        ''')

    def test_class_prepare_mapping_observes_annotation_initialization(self):
        self.both_paths('''
            from __future__ import annotations
            class Prepared(dict):
                def __getitem__(self, key):
                    if key == "__annotations__": print("annotation lookup")
                    return super().__getitem__(key)
                def __setitem__(self, key, value):
                    if key == "__annotations__": print("annotation setup")
                    return super().__setitem__(key, value)
            class Meta(type):
                @classmethod
                def __prepare__(meta, name, bases):
                    return Prepared()
                def __new__(meta, name, bases, namespace):
                    print(list(namespace))
                    print(namespace["__annotations__"])
                    return super().__new__(meta, name, bases, dict(namespace))
            class Example(metaclass=Meta):
                "class documentation"
                field: Missing
                def f(self, value: Missing): pass
            print(Example.__annotations__)
        ''')

    def test_compile_eval_exec_inherit_and_dont_inherit(self):
        self.both_paths('''
            from __future__ import annotations
            import __future__
            statement = "def f(x: int) -> list[int]: pass"
            for explicit, isolated in [(0, False), (0, True), (__future__.annotations.compiler_flag, True)]:
                space = {}
                code = compile(statement, "flags.py", "exec", flags=explicit, dont_inherit=isolated)
                exec(code, space)
                print(space["f"].__annotations__["x"] == "int")
                if isolated and not explicit:
                    alias = space["f"].__annotations__["return"]
                    print(alias.__origin__ is list, alias.__args__ == (int,))
            def nested():
                space = {}
                exec(statement, space)
                print(space["f"].__annotations__["x"] == "int")
                print(eval("compile('def f(x:int):pass', 'nested.py', 'exec')").co_flags & __future__.annotations.compiler_flag)
                exec("inner = compile('def f(x:int):pass', 'nested.py', 'exec')", space)
                target = {}
                exec(space["inner"], target)
                print(target["f"].__annotations__["x"] == "int")
            nested()
            expression = compile("compile('def f(x:int):pass', 'inside.py', 'exec')", "outer.py", "eval", dont_inherit=True)
            target = {}
            exec(eval(expression), target)
            print(target["f"].__annotations__["x"] is int)
        ''')

    def test_all_explicit_future_flags_and_invalid_flags(self):
        self.run_source('''
            import __future__
            for name in __future__.all_feature_names:
                flag = getattr(__future__, name).compiler_flag
                code = compile("value=1", "flags.py", "exec", flag, True)
                print(name, code.co_flags)
            for flag in [-1, 1, 2048, 65536, 33554432]:
                try:
                    compile("pass", "invalid.py", "exec", flag, True)
                except ValueError:
                    print("invalid", flag)
            flags = __future__.annotations.compiler_flag | __future__.barry_as_FLUFL.compiler_flag
            target = {}
            exec(compile("def f(x: int): pass\\nvalue=1<>2", "combined.py", "exec", flags, True), target)
            print(target["f"].__annotations__, target["value"])
        ''')

    def test_dynamic_annotation_printer_precedence_and_literals(self):
        expressions = []
        for expression in ["a+b", "a-b", "a*b", "a/b", "a//b", "a%b", "a**b", "a<<b", "a&b", "a^b", "a|b", "a and b", "a or b", "not a", "a<b", "a if b else c", "lambda x:x"]:
            for form in ["-({})", "({}) + c", "a + ({})", "({}) ** c", "a ** ({})", "f({})", "f(x={})", "a[{}]"]:
                expressions.append(form.format(expression))
        expressions += ["a[1:2, 3:]", "a[*b]", "(*a,)", "[*(a,b)]", "f((x for x in a), b)",
                        'f"line\\n{x!r}"', 'f"{\'a\\n\'}"', 'f"it\'s {a}"',
                        'f"{{literal}} {a:>{width}.{precision}f}"', "f'''a\nb{x}'''"]
        self.run_source("expressions=" + repr(expressions) + '''
for expression in expressions:
    target = {}
    exec("from __future__ import annotations\\nx:" + expression, target)
    print(target["__annotations__"]["x"])
''')

    def test_future_flags_do_not_leak_and_argument_protocols(self):
        self.run_source('''
            import __future__
            flag = __future__.annotations.compiler_flag
            target = {}
            exec("from __future__ import annotations\\ndef f(x:int):pass", target)
            print(target["f"].__annotations__["x"] == "int")
            ordinary = compile("def f(x:int):pass", "ordinary.py", "exec")
            space = {}
            exec(ordinary, space)
            print(space["f"].__annotations__["x"] is int, ordinary.co_flags)
            interactive = compile("from __future__ import annotations", "single.py", "single")
            exec(interactive, {})
            print(compile("pass", "ordinary.py", "exec").co_flags)
            expression = compile("compile('def f(x:int):pass', 'inside.py', 'exec')", "outer.py", "eval", flag, True)
            result = {}
            exec(eval(expression), result)
            print(result["f"].__annotations__["x"] == "int")
            target = {"format": int}
            exec(compile("def f(x:format):pass", "format.py", "exec", dont_inherit=True), target)
            print(target["f"].__annotations__["x"] is int)
            class Index:
                def __index__(self): return flag
            print(compile("pass", "index.py", "exec", Index(), True).co_flags)
            for value in [None, 1.0, "0", []]:
                for name in ["flags", "optimize"]:
                    try:
                        compile("pass", "arguments.py", "exec", **{name:value})
                    except TypeError:
                        print("type", name, type(value).__name__)
            for truth in [None, 0.0, "", [], [1]]:
                print(compile("pass", "truth.py", "exec", dont_inherit=truth).co_flags)
        ''')

    def test_builtin_callbacks_keep_the_current_python_future_context(self):
        self.both_paths('''
            from __future__ import annotations
            import itertools
            import functools
            statement = "def f(x:int):pass"
            mapped = next(map(compile, [statement], ["mapped.py"], ["exec"]))
            starred = next(itertools.starmap(compile, [(statement, "starred.py", "exec")]))
            partial = functools.partial(compile, statement, "partial.py", "exec")()
            evaluated = next(map(eval, ["compile('def f(x:int):pass','evaluated.py','exec')"]))
            for code in [mapped, starred, partial, evaluated]:
                space = {}
                exec(code, space)
                print(space["f"].__annotations__["x"] == "int")
            isolated = {}
            exec(compile("def factory():\\n return next(map(compile,['def f(x:int):pass'],['isolated.py'],['exec']))", "factory.py", "exec", dont_inherit=True), isolated)
            space = {}
            exec(isolated["factory"](), space)
            print(space["f"].__annotations__["x"] is int)
        ''')

    def test_mandatory_features_retain_current_python_behavior(self):
        self.both_paths('''
            from __future__ import nested_scopes, division, with_statement, print_function, unicode_literals, generator_stop
            print(3 / 2, type("text").__name__)
            def outer():
                value = 13
                def inner(): return value
                return inner
            print(outer()())
            def broken():
                yield 1
                raise StopIteration("explicit")
            iterator = broken()
            print(next(iterator))
            try:
                next(iterator)
            except RuntimeError as error:
                print(str(error), type(error.__cause__).__name__, error.__cause__.args)
        ''')

    def test_barry_syntax_and_inherited_expression_flags(self):
        self.both_paths('''
            from __future__ import barry_as_FLUFL as barry
            print(1 <> 2, barry.compiler_flag)
            print(f"{1 <> 2}")
            print(eval("1 <> 2"))
            def f():
                return eval("3 <> 4")
            print(f())
            for text in ["1 != 2", "1 < > 2"]:
                try:
                    compile(text, "barry.py", "eval")
                except SyntaxError:
                    print("rejected", text)
            try:
                compile("1 <> 2", "ordinary.py", "eval", dont_inherit=True)
            except SyntaxError:
                print("isolated syntax")
            print(eval(compile("1 != 2", "ordinary.py", "eval", dont_inherit=True)))
        ''')

    def test_future_placement_unknown_features_and_nested_blocks(self):
        sources = [
            "from __future__ import missing", "from __future__ import braces",
            "from __future__ import *", "from __future__ import all_feature_names",
            "b'documentation'\nfrom __future__ import annotations",
            "f'documentation'\nfrom __future__ import annotations",
            "pass\nfrom __future__ import annotations",
            "'one'\n'other'\nfrom __future__ import annotations",
            "def f():\n from __future__ import annotations",
            "class C:\n from __future__ import annotations",
            "if True:\n from __future__ import annotations",
            "try:\n from __future__ import annotations\nexcept: pass",
            "for x in []:\n from __future__ import annotations",
            "from __future__ import annotations\nx:(a:=1)",
            "from __future__ import annotations\nx:(yield 1)",
            "from __future__ import annotations\nx:lambda a=(z:=1):a",
            "from __future__ import annotations\ndef f(x:(a:=1)):pass",
            "from __future__ import annotations\ndef f():\n global x\n x:int",
        ]
        for source in sources:
            with self.subTest(static=source):
                result = transpile(source, TranspileOptions(optimize=False))
                self.assertFalse(result.success)
        dynamic = "sources = " + repr(sources) + "\n"
        dynamic += '''for source in sources:
    try:
        compile(source, "bad_future.py", "exec")
    except SyntaxError as error:
        print(type(error).__name__, str(error).split(" (")[0])
    else:
        print("incorrectly accepted")
'''
        self.run_source(dynamic)

    def test_runtime_future_module_shadow_does_not_change_compiler_features(self):
        with tempfile.TemporaryDirectory(prefix="py2fastrust-future-module-") as directory:
            root = Path(directory)
            (root / "__future__.py").write_text("annotations='shadowed feature object'\n", encoding="utf-8")
            source = "from __future__ import annotations as feature\nx: Missing\nprint(feature, __annotations__)\n"
            path = root / "main.py"
            path.write_text(source, encoding="utf-8")
            result = transpile(source, TranspileOptions(filename=str(path), optimize=False))
            self.assertTrue(result.success, result.diagnostics)
            rust = root / "main.rs"
            rust.write_text(result.rust_source, encoding="utf-8")
            compiled = subprocess.run(["rustc", "--edition=2021", str(rust), "-o", str(root / "main")], capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            actual = subprocess.run([str(root / "main")], capture_output=True, text=True, timeout=15)
            expected = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=15)
            self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
            self.assertEqual(actual.stdout, expected.stdout)


if __name__ == "__main__":
    unittest.main()
