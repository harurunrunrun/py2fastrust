"""CPython differential coverage for live mapping views and iterators."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class DictViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-views-")
        root = Path(cls.directory.name)
        source = transpile("import sys\nexec(sys.stdin.read())\n", TranspileOptions(filename="views.py", optimize=False, include_modules=("collections",)))
        if not source.success:
            raise AssertionError("\n".join(map(str, source.diagnostics)))
        rust = root / "main.rs"
        rust.write_text(source.rust_source)
        cls.binary = root / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(rust), "-o", str(cls.binary)], text=True, capture_output=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def check(self, source):
        source = textwrap.dedent(source)
        actual = subprocess.run([str(self.binary)], input=source, text=True, capture_output=True, timeout=20)
        expected = subprocess.run([sys.executable, "-I", "-c", source], text=True, capture_output=True, timeout=20)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_live_contents_representation_and_identity(self):
        self.check('''
            key = "".join(["runtime", " key"])
            value = int("1000")
            d = {key: value, "second": 2}
            keys, values, items = d.keys(), d.values(), d.items()
            print(type(keys).__name__, type(values).__name__, type(items).__name__)
            print(keys, values, items, len(keys), bool(values))
            print(next(iter(keys)) is key, next(iter(values)) is value,
                  next(iter(items))[0] is key, next(iter(items))[1] is value)
            d["third"] = 3
            d["second"] = 20
            print(list(keys), list(values), list(items), len(keys))
            print(list(reversed(keys)), list(reversed(values)), list(reversed(items)))
            del d[key]
            print(keys, values, items)
            d.clear()
            print(keys, values, items, len(keys), bool(values))
            for action in [lambda: d.keys(1), lambda: keys.__len__(1), lambda: d.items(x=1)]:
                try: action()
                except Exception as error: print(type(error).__name__)
        ''')

    def test_live_value_updates_and_reversed_iterators(self):
        self.check('''
            for kind in ["keys", "values", "items"]:
                d = {"a": 1, "b": 2, "c": 3}
                it = iter(getattr(d, kind)())
                print(type(it).__name__, next(it), it.__length_hint__())
                d["b"] = 20
                print(list(it), it.__length_hint__())
                d = {"a": 1, "b": 2, "c": 3}
                it = reversed(getattr(d, kind)())
                print(type(it).__name__, next(it), it.__length_hint__())
                del d["b"]
                d["d"] = 4
                print(list(it), it.__length_hint__())
            d = {"a": 1, "b": 2}
            print(list(reversed(d)), list(d.__reversed__()))
        ''')

    def test_size_errors_stick_and_exhaustion_does_not_revive(self):
        self.check('''
            import operator
            def step(it):
                try: print("next", next(it))
                except Exception as error: print(type(error).__name__, str(error))
            for factory in [lambda d: iter(d), lambda d: iter(d.values()),
                            lambda d: iter(d.items()), lambda d: reversed(d)]:
                d = {"a": 1, "b": 2}
                it = factory(d)
                print(it.__length_hint__(), operator.length_hint(it))
                d["c"] = 3
                print(it.__length_hint__())
                del d["c"]
                step(it)
                d["c"] = 3
                step(it)
                del d["c"]
                step(it)
                print(it.__length_hint__())
                d = {"a": 1}
                it = factory(d)
                step(it)
                step(it)
                d["b"] = 2
                step(it)
                print(it.__length_hint__())
            s = {1, 2}
            it = iter(s)
            s.add(3)
            step(it)
            s.remove(3)
            step(it)
            print(it.__length_hint__())
        ''')

    def test_same_size_key_changes_and_deleted_entry_positions(self):
        self.check('''
            def rest(it):
                for unused in range(6):
                    try: print(next(it), it.__length_hint__())
                    except Exception as error: print(type(error).__name__, str(error))
            for remove, insert in [("a", "d"), ("b", "d"), ("a", "a")]:
                d = {"a": 1, "b": 2, "c": 3}
                it = iter(d)
                print(next(it))
                del d[remove]
                d[insert] = 4
                rest(it)
            d = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
            it = iter(d)
            print(next(it))
            del d["a"]
            d["f"] = 6
            rest(it)
            s = {1, 2, 3}
            it = iter(s)
            first = next(it)
            s.remove(first)
            s.add(first)
            print(sorted(it))
            s = {1, 2, 3}
            it = iter(s)
            first = next(it)
            s.remove(first)
            s.add(4)
            print(sorted(it))
        ''')

    def test_membership_equality_and_set_operations(self):
        self.check('''
            nan = float("nan")
            d = {"a": 1, "b": 2, "nan": nan, "list": []}
            keys, values, items = d.keys(), d.values(), d.items()
            print("a" in keys, "z" in keys, [] in values, nan in values)
            print(("a", 1) in items, ["a", 1] in items,
                  ("nan", nan) in items, ("list", []) in items)
            for candidate in [([], 1), ("a",), ("a", 1, 2)]:
                try: print(candidate in items)
                except Exception as error: print(type(error).__name__)
            print(keys == set(d), keys == list(d), keys <= set(d), keys < set(d) | {"extra"})
            print(values == values, values == d.values())
            for left, right in [(keys, ["a", "z"]), (["a", "z"], keys)]:
                print(sorted(left & right), sorted(left | right),
                      sorted(left - right), sorted(left ^ right))
            small = {"a": 1, "b": 2}.items()
            print(small == {("a", 1), ("b", 2)}, small.isdisjoint([("z", 3)]),
                  small.isdisjoint([("a", 1)]))
            print(sorted(small & [("a", 1), ("z", 3)]))
            print(items.isdisjoint([("list", [])]))
            unhashable = {"a": []}.items()
            for action in [lambda: unhashable & [("a", [])],
                           lambda: unhashable & [], lambda: unhashable | [],
                           lambda: unhashable - [("a", [])],
                           lambda: unhashable ^ [("a", [])],
                           lambda: unhashable ^ {"a": []}.items()]:
                try: print(action())
                except Exception as error: print(type(error).__name__)
            for view in [keys, items]:
                try: hash(view)
                except Exception as error: print(type(error).__name__)
            print(isinstance(hash(values), int))
        ''')

    def test_mappingproxy_is_readonly_live_and_supports_mapping_operations(self):
        self.check('''
            d = {"a": 1, "b": 2}
            view = d.keys()
            proxy = view.mapping
            print(type(proxy).__name__, proxy, proxy == d, d == proxy,
                  view.mapping is view.mapping)
            print(list(proxy), list(reversed(proxy)), len(proxy), bool(proxy),
                  "a" in proxy, proxy["a"], proxy.get("missing", 3))
            keys = proxy.keys()
            d["c"] = 3
            print(proxy, list(keys), proxy.copy(), proxy | {"z": 9}, {"z": 9} | proxy)
            for action in [lambda: proxy.__setitem__("a", 10), lambda: proxy.update({}),
                           lambda: proxy.pop("a")]:
                try: action()
                except Exception as error: print(type(error).__name__)
            try: proxy["a"] = 10
            except Exception as error: print(type(error).__name__)
            try: del proxy["a"]
            except Exception as error: print(type(error).__name__)
            try: proxy |= {}
            except Exception as error: print(type(error).__name__)
            try: hash(proxy)
            except Exception as error: print(type(error).__name__)
        ''')

    def test_namespaces_class_dicts_and_inplace_mutation(self):
        self.check('''
            def namespace_equal(namespace):
                proxy = namespace.keys().mapping
                snapshot = proxy.copy()
                return proxy == snapshot, snapshot == proxy
            print(namespace_equal(globals()))
            scope = {"a": 1, "b": 2}
            exec("view = globals().keys()", scope)
            keys = scope["view"]
            scope["extra"] = 3
            print("extra" in keys)
            class C:
                x = 1
            mapping = C.__dict__
            keys = mapping.keys()
            C.y = 2
            print("y" in keys, mapping["y"])
            it = iter(mapping)
            C.z = 3
            try: next(it)
            except Exception as error: print(type(error).__name__, str(error))
            try: C.__dict__["x"] = 5
            except Exception as error: print(type(error).__name__)
            d = {"a": 1}
            view = d.items()
            alias = d
            d |= {"b": 2}
            print(d is alias, list(view))
            s = {1, 2}
            alias = s
            it = iter(s)
            s |= {3}
            print(s is alias)
            try: next(it)
            except Exception as error: print(type(error).__name__, str(error))
        ''')

    def test_collection_views_interoperate_with_builtin_views(self):
        self.check('''
            from collections import defaultdict, Counter, OrderedDict
            for make in [dict, defaultdict, Counter, OrderedDict]:
                mapping = make(a=1, b=2)
                keys = mapping.keys()
                items = mapping.items()
                builtin_keys = {"a": 1, "b": 2}.keys()
                builtin_items = {"a": 1, "b": 2}.items()
                print(keys == builtin_keys, builtin_keys == keys,
                      keys <= builtin_keys, builtin_keys <= keys,
                      keys >= builtin_keys, builtin_keys >= keys)
                print(items == builtin_items, builtin_items == items,
                      sorted(items & builtin_items), sorted(builtin_items ^ items))
        ''')

    def test_random_dictionary_mutation_traces(self):
        import random
        rng = random.Random(315)
        cases = []
        for count in range(9):
            for unused in range(8):
                actions = [(rng.choice(["next", "next", "delete", "insert", "hint", "clear"]), rng.randrange(10))
                           for step in range(12)]
                cases.append((count, actions))
        self.check("cases = " + repr(cases) + "\n" + textwrap.dedent('''
            for reverse in [False, True]:
                for count, actions in cases:
                    d = {number: number for number in range(count)}
                    it = reversed(d) if reverse else iter(d)
                    for action, key in actions:
                        if action == "delete":
                            if key in d: del d[key]
                        elif action == "insert": d[key] = key
                        elif action == "clear": d.clear()
                        elif action == "hint": print("hint", it.__length_hint__())
                        else:
                            try: print("next", next(it))
                            except Exception as error: print(type(error).__name__, str(error))
        '''))

    def test_set_update_methods_expose_live_changes_and_gc_roots(self):
        self.check('''
            import gc
            s = {1, 2, 3}
            def changes():
                yield 4
                print("visible", 4 in s)
                gc.collect()
                yield 5
            s.update(changes())
            print(sorted(s))
            for name, values in [("difference_update", [2]), ("intersection_update", [1, 3]),
                                 ("symmetric_difference_update", [3, 9])]:
                it = iter(s)
                getattr(s, name)(values)
                print(sorted(s))
                try: next(it)
                except Exception as error: print(type(error).__name__, str(error))
            s.difference_update(s)
            print(s)
            for name in ["keys", "values", "items"]:
                d = {"a": 1}
                view = getattr(d, name)()
                d["view"] = view
                print(repr(view))
        ''')

    def test_views_iterators_and_mappingproxy_keep_their_owner_alive(self):
        self.check('''
            import gc
            def views():
                d = {"a": [1], "b": [2]}
                return d.keys(), d.values(), d.items(), iter(d), d.keys().mapping
            keys, values, items, iterator, proxy = views()
            for unused in range(11000):
                discarded = [unused]
            gc.collect()
            print(list(keys), list(values), list(items), list(iterator), proxy["a"])
            nan = float("nan")
            d = {nan: nan}
            print(next(iter(d.keys())) is nan, next(iter(d.values())) is nan,
                  next(iter(d.items()))[0] is nan, (nan, nan) in d.items())
        ''')


if __name__ == "__main__":
    unittest.main()
