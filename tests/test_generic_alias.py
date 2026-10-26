"""Parameterized built-ins retain their type arguments at runtime."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class GenericAliasTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_future_flag_inheritance_and_lazy_annotation_type_arguments(self):
        self.run_source('''
            from __future__ import annotations
            import __future__
            statement = "def f(x:int)->list[int]:pass"
            for flags, isolated in [(0, False), (0, True),
                                    (__future__.annotations.compiler_flag, True)]:
                space = {}
                code = compile(statement, "flags.py", "exec", flags=flags,
                               dont_inherit=isolated)
                exec(code, space)
                annotations = space["f"].__annotations__
                print(annotations["x"] is int, annotations["x"] == "int",
                      annotations["return"] == list[int],
                      annotations["return"] == "list[int]")
                if isolated and not flags:
                    alias = annotations["return"]
                    print(alias.__origin__ is list, alias.__args__ == (int,))
            statement = "def f(x:dict[str,list[int]])->tuple[int,...]:pass"
            space = {}
            exec(compile(statement, "lazy.py", "exec", flags=0,
                         dont_inherit=True), space)
            original_int = int
            space["int"] = str
            annotations = space["f"].__annotations__
            print(annotations["x"], annotations["return"])
            print(annotations["x"] == dict[str, list[str]],
                  annotations["return"] == tuple[str, ...])
            space["int"] = original_int
            print(space["f"].__annotations__ is annotations,
                  annotations["x"] == dict[str, list[str]],
                  annotations["return"] == tuple[str, ...])
        ''')

    def test_origins_arguments_nested_repr_and_metadata(self):
        self.run_source('''
            aliases = [list[int], dict[str, list[int]], tuple[int, ...],
                       tuple[()], list[()], list[None], list["Forward"],
                       list[int, str], set[tuple[int, str]], frozenset[bytes]]
            for alias in aliases:
                print(alias, repr(alias), type(alias).__name__)
                print(alias.__origin__.__name__, alias.__args__, alias.__parameters__,
                      alias.__args__ is alias.__args__,
                      alias.__parameters__ is alias.__parameters__)
            alias = list[int]
            print(alias.__name__, alias.__qualname__, alias.__module__,
                  alias.__origin__ is list, alias.__args__[0] is int)
            values = []
            alias.append(values, 7)
            print(values, alias([1, 2]))
        ''')

    def test_structural_equality_hashing_and_alias_constructor(self):
        self.run_source('''
            from types import GenericAlias
            print(type(list[int]) is GenericAlias)
            arguments = (int, str)
            print(GenericAlias(list, arguments).__args__ is arguments)
            class Arguments(tuple):
                pass
            arguments = Arguments((int, str))
            print(GenericAlias(list, arguments),
                  GenericAlias(list, arguments).__args__ is arguments)
            aliases = [GenericAlias(list, int), GenericAlias(dict, (str, list[int])),
                       GenericAlias(tuple, ()), GenericAlias(list, (int, str)),
                       GenericAlias(list, [int]), GenericAlias(42, int)]
            for alias in aliases:
                print(alias, alias.__origin__, alias.__args__)
            print(GenericAlias(list, int) == list[int],
                  GenericAlias(dict, (str, list[int])) == dict[str, list[int]],
                  GenericAlias(tuple, ()) == tuple[()])
            print(list[int] == list[str], list[int] != list[str],
                  list[int] == list, list[int] == (list, int))
            print(hash(list[int]) == hash(GenericAlias(list, int)),
                  hash(dict[str, list[int]]) == hash(dict[str, list[int]]))
            print(GenericAlias(list, 1) == GenericAlias(list, 1.0),
                  hash(GenericAlias(list, 1)) == hash(GenericAlias(list, 1.0)))
            mapping = {list[int]: "integer", dict[str, int]: "mapping"}
            print(mapping[GenericAlias(list, int)], len({list[int], list[int], list[str]}))
            alias = GenericAlias(list, [int])
            try:
                hash(alias)
            except TypeError as error:
                print(type(error).__name__)
            print(alias == GenericAlias(list, [int]))
            try:
                hash(GenericAlias(list, (([],),)))
            except TypeError as error:
                print(type(error).__name__)
        ''')

    def test_substitution_validation_and_mro_entries(self):
        self.run_source('''
            from types import GenericAlias
            for alias in [list[int], dict[str, int], tuple[()], GenericAlias(42, int)]:
                try:
                    alias[str]
                except TypeError as error:
                    print(type(error).__name__, str(error))
                print(alias.__mro_entries__((alias,)))
            alias = list[int]
            for args in [(), ((), 1)]:
                try:
                    alias.__mro_entries__(*args)
                except TypeError as error:
                    print(type(error).__name__)
            try:
                alias.__mro_entries__(bases=())
            except TypeError as error:
                print(type(error).__name__)
            try:
                alias.__origin__ = tuple
            except AttributeError as error:
                print(type(error).__name__)
            try:
                isinstance([], alias)
            except TypeError as error:
                print(type(error).__name__)
            try:
                issubclass(list, alias)
            except TypeError as error:
                print(type(error).__name__)
            class Integers(list[int]):
                pass
            print(Integers.__bases__[0] is list,
                  Integers.__orig_bases__[0] == list[int], Integers([1, 2]))
        ''')

    def test_user_origins_class_hooks_and_call_metadata(self):
        self.run_source('''
            from types import GenericAlias
            class Container:
                def __init__(self, value=0):
                    self.value = value
            Container.__module__ = "sample"
            alias = GenericAlias(Container, int)
            value = alias(value=3)
            print(alias, alias.__name__, alias.__module__, value.value,
                  value.__orig_class__ is alias,
                  alias.__mro_entries__(None)[0] is Container)
            class Hook:
                @classmethod
                def __class_getitem__(cls, key):
                    return cls.__name__, key
            class Child(list):
                @classmethod
                def __class_getitem__(cls, key):
                    return "override", key
            print(Hook[int], Child[str])
            for exception in [AttributeError, TypeError, ValueError]:
                class Setter:
                    def __setattr__(self, name, value):
                        raise exception("orig")
                try:
                    GenericAlias(Setter, int)()
                    print("suppressed")
                except ValueError as error:
                    print(type(error).__name__, str(error))
        ''')

    def test_unicode_names_arbitrary_origins_and_gc_callbacks(self):
        self.run_source('''
            import gc
            from types import GenericAlias
            class 箱:
                pass
            箱.__module__ = "日本語"
            print(GenericAlias(箱, (str, list[int])))
            for origin in [42, "name", None]:
                alias = GenericAlias(origin, int)
                print(alias, alias.__origin__, alias.__args__)
                try:
                    alias()
                except TypeError as error:
                    print(type(error).__name__)
            class Origin:
                def __repr__(self):
                    gc.collect()
                    return "origin"
                def __eq__(self, other):
                    gc.collect()
                    return isinstance(other, Origin)
                def __hash__(self):
                    gc.collect()
                    return 19
            class Argument:
                def __repr__(self):
                    gc.collect()
                    return "argument"
                def __eq__(self, other):
                    gc.collect()
                    return isinstance(other, Argument)
                def __hash__(self):
                    gc.collect()
                    return 23
            print(repr(GenericAlias(Origin(), (Argument(),))))
            print(GenericAlias(Origin(), (Argument(),)) ==
                  GenericAlias(Origin(), (Argument(),)))
            print(hash(GenericAlias(Origin(), (Argument(),))) ==
                  hash(GenericAlias(Origin(), (Argument(),))))
            items = []
            recursive = GenericAlias(list, items)
            items.append(recursive)
            try:
                repr(recursive)
            except RecursionError as error:
                print(type(error).__name__)
        ''')

    def test_tuple_subclass_rich_comparison_and_hash(self):
        self.run_source('''
            from types import GenericAlias
            class Parameters(tuple):
                def __eq__(self, other):
                    print("parameters eq")
                    return "matched"
                def __ne__(self, other):
                    print("parameters ne")
                    return "different"
                def __hash__(self):
                    print("parameters hash")
                    return 77
            args = Parameters((int,))
            left = GenericAlias(list, args)
            right = GenericAlias(list, (str,))
            print(left.__args__ is args, left == right, left != right)
            print(hash(left) == (hash(list) ^ 77))
            print(left == GenericAlias(tuple, args))
            class TrueParameters(tuple):
                def __eq__(self, other):
                    return True
            print(GenericAlias(list, TrueParameters((int,))) != right)
        ''')
