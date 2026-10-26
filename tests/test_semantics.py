"""Regression cases spanning control flow, object identity and namespaces."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class SemanticsTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_comprehension_closures_and_walrus_scope(self):
        self.run_source('''
            x = 99
            def f():
                print(x)
                functions = [lambda: i for i in range(3)]
                print([g() for g in functions])
                values = [(last := i*i) for i in range(4)]
                print(values, last, x)
                return list((last := last + 1) for _ in range(2))
            print(f())
            print(x)
            print([(outside := i) for i in range(2)], outside)
        ''')

    def test_except_alias_and_nested_exception_context(self):
        self.run_source('''
            def make():
                try:
                    raise ValueError("gone")
                except ValueError as error:
                    return lambda: error
            closure = make()
            try:
                closure()
            except NameError:
                print("alias removed")
            try:
                try:
                    1 // 0
                except ZeroDivisionError:
                    try:
                        raise ValueError("inner")
                    except ValueError:
                        pass
                    raise
            except ZeroDivisionError:
                print("outer restored")
            def f():
                try:
                    return 1
                finally:
                    return 2
            print(f())
        ''')

    def test_meta_prepare_mapping_and_internal_temps(self):
        self.run_source('''
            class Mapping:
                def __init__(self):
                    self.data = {"provided": 7}
                def __getitem__(self, key):
                    return self.data[key]
                def __setitem__(self, key, value):
                    self.data[key] = value
                def keys(self):
                    return self.data.keys()
            class Meta(type):
                @classmethod
                def __prepare__(meta, name, bases):
                    return Mapping()
                def __new__(meta, name, bases, namespace):
                    print(sorted(namespace.keys()))
                    return type.__new__(meta, name, bases, dict(namespace))
            class Example(metaclass=Meta):
                result = provided + 1
                compare = 1 < 2 < 3
            print(Example.result, Example.compare)
            print([key for key in globals() if key.startswith("$tmp")])
        ''')

    def test_descriptor_and_diamond_inheritance(self):
        self.run_source('''
            class A:
                def name(self):
                    return "A"
            class B(A):
                pass
            class C(A):
                def name(self):
                    return "C"
            class D(B, C):
                @property
                def doubled(self):
                    return self.value * 2
                @doubled.setter
                def doubled(self, value):
                    self.value = value // 2
            d = D()
            d.doubled = 18
            print(d.name(), d.value, d.doubled)
        ''')

    def test_with_target_failure_and_return_cleanup(self):
        self.run_source('''
            class Guard:
                def __enter__(self):
                    return [1]
                def __exit__(self, kind, error, tb):
                    print("exit", kind.__name__ if kind else None)
                    return True
            with Guard() as (a, b):
                print("unreachable")
            def f():
                with Guard():
                    return 4
            print(f())
        ''')

    def test_match_patterns_guards_and_singletons(self):
        self.run_source('''
            class Point:
                __match_args__ = ("x", "y")
                def __init__(self, x, y):
                    self.x, self.y = x, y
            subjects = [1, True, [2, 3, 4], {"a": 5, "b": 6}, Point(7, 8), "other"]
            for subject in subjects:
                match subject:
                    case True:
                        print("true")
                    case 0 | 1 as number:
                        print("number", number)
                    case [first, *rest] if first > 0:
                        print("sequence", first, rest)
                    case {"a": value, **rest}:
                        print("mapping", value, rest)
                    case Point(x, y=last):
                        print("point", x, last)
                    case _:
                        print("fallback")
        ''')

    def test_starred_evaluation_and_shadowed_set(self):
        self.run_source('''
            def g():
                print("consume")
                yield 2
            def h():
                print("evaluate")
                return 3
            def f(*args, **kw):
                print(args, kw)
            print([*g(), h()])
            f(*g(), h())
            f(*g(), x=h())
            set = 0
            print(sorted({*range(3), 1}))
        ''')

    def test_gc_roots_and_list_iteration_mutation(self):
        self.run_source('''
            import gc
            a = [[]]
            a[0].append(a)
            shared = [a]
            for i in range(11000):
                discarded = [i]
            gc.collect()
            print(shared[0] is a, a[0][0] is a)
            values = [0]
            for value in values:
                if value < 3:
                    values.append(value + 1)
            print(values)
        ''')

    def test_cycle_finalizers_resurrection_and_generator_cleanup(self):
        self.run_source('''
            import gc
            seen = []
            saved = []
            class Finalized:
                def __init__(self, number):
                    self.number = number
                    self.cycle = self
                def __del__(self):
                    seen.append(self.number)
                    if self.number == 1:
                        saved.append(self)
            a = Finalized(1)
            b = Finalized(2)
            del a, b
            gc.collect()
            print(sorted(seen), len(saved), saved[0].number)
            saved.clear()
            gc.collect()
            print(sorted(seen))
            def values():
                try:
                    yield 3
                finally:
                    seen.append("closed")
            iterator = values()
            print(next(iterator))
            del iterator
            gc.collect()
            print(seen[-1])
        ''')


if __name__ == "__main__":
    unittest.main()
