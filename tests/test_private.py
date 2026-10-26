"""Lexical private-name transformations use the official scope information."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_runtime
from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class PrivateNameTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_private_import_module_and_from_attribute_names(self):
        source = '''class C:
    import __dep
    import __dep as __alias
    from module import __value
    def read(self):
        return self.__dep.value, self.__alias.__name__, self.__value
print(C().read())
'''
        with tempfile.TemporaryDirectory(prefix="py2fastrust-private-import-") as directory:
            root = Path(directory)
            (root / "_C__dep.py").write_text("value=17\n")
            (root / "module.py").write_text("__value=3\n_C__value=19\n")
            script = root / "main.py"
            script.write_text(source)
            result = transpile(source, TranspileOptions(filename=str(script), module_paths=(root,), optimize=False))
            self.assertTrue(result.success, result.diagnostics)
            target = root / "main.rs"
            target.write_text(result.rust_source)
            compiled = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(root / "main")],
                                      capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            actual = subprocess.run([str(root / "main")], capture_output=True, text=True, timeout=15)
            expected = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=15)
            self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
            self.assertEqual(actual.stdout, expected.stdout)

    def test_inheritance_and_nested_lexical_scopes(self):
        self.run_source('''
            class Base:
                def __init__(self):
                    self.__value = 3
                def read(self):
                    return self.__value
            class Child(Base):
                def __init__(self):
                    super().__init__()
                    self.__value = 7
                def closure(self, __step):
                    __value = self.__value
                    def update():
                        nonlocal __value
                        __value += __step
                        return __value
                    return update
                class __Inner:
                    __value = 11
                    def read(self):
                        return self.__value
                def inner(self):
                    return self.__Inner().read()
            value = Child()
            update = value.closure(2)
            print(value.read(), value._Base__value, value._Child__value)
            print(update(), update(), value.inner())
            print(Base.__static_attributes__, Child.__static_attributes__)
        ''')

    def test_arguments_imports_comprehensions_and_annotations(self):
        self.run_source('''
            class _Example:
                import math as __math
                __items = [__x * 2 for __x in range(4)]
                def f(self, __x: int=3, *, __kw: int=5, **__extra):
                    return self.__math.isqrt(__x) + __kw + len(__extra)
                def keywords_are_literal(self):
                    try:
                        return self.f(__x=4)
                    except TypeError:
                        return "unmangled keyword"
                def comprehension(self):
                    __offset = 3
                    return [lambda: __x + __offset for __x in range(3)]
            value = _Example()
            print(value._Example__items, value.f(), value.f(9, _Example__kw=2, extra=1))
            print(value.keywords_are_literal())
            print(_Example.f.__annotations__, _Example.f.__kwdefaults__)
            print([f() for f in value.comprehension()])
            class ___:
                __value = 13
            print(___.__value)
        ''')

    def test_match_exception_and_global_bindings(self):
        self.run_source('''
            class Example:
                __constant = 17
                def f(self, value):
                    global __global
                    __global = 19
                    try:
                        raise ValueError("message")
                    except ValueError as __error:
                        print(str(__error))
                    try:
                        print(__error)
                    except UnboundLocalError:
                        print("deleted")
                    match value:
                        case {"k": [__head, *__tail], **__rest}:
                            return __head, __tail, __rest
                def pattern(self, value):
                    match value:
                        case Example.__constant:
                            return True
                    return False
            value = Example()
            print(value.f({"k": [2,3,4], "extra": 5}))
            print(_Example__global, value.pattern(17), value.pattern(18))
            class Pattern:
                pass
            pattern = Pattern()
            pattern.__field = 23
            class Match:
                def f(self, value):
                    match value:
                        case Pattern(__field=__value):
                            return __value
            print(Match().f(pattern))
        ''')

    def test_transitive_captures_in_synthetic_comprehensions(self):
        self.run_source('''
            _Capture__outside = 100
            class Capture:
                def make(self):
                    __a, __b, __outside = 4, 9, 1
                    left = [lambda: __a + __x for __x in range(2)]; right = [lambda: __b + __y for __y in range(2)]
                    nested = [[lambda: __a + __x + __y for __y in range(2)] for __x in range(2)]
                    transitive = [(lambda: lambda: __a + __x)() for __x in range(2)]
                    mapping = {__x: lambda: __b + __x for __x in range(2)}
                    members = {lambda: __a + __x for __x in range(2)}
                    iterator_lambda = [lambda: __a for __x in (lambda: range(__b - 7))()]
                    def global_barrier():
                        global __outside
                        return [lambda: __outside for _ in range(2)]
                    return left, right, nested, transitive, mapping, members, global_barrier(), iterator_lambda
            left, right, nested, transitive, mapping, members, globals_, iterator_lambda = Capture().make()
            print([f() for f in left], [f() for f in right])
            print([[f() for f in row] for row in nested])
            print([f() for f in transitive], [f() for f in mapping.values()])
            print(sorted(f() for f in members), [f() for f in globals_])
            print([f() for f in iterator_lambda])
        ''')


if __name__ == "__main__":
    unittest.main()
