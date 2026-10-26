"""User generic classes specialize through typing, preserving native bases."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class GenericClassTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_typing_alias_defaults_metadata_cache_and_substitution(self):
        self.run_source('''
            from types import GenericAlias
            class Box[T, U=str]:
                pass
            T, U = Box.__type_params__
            alias = Box[int]
            print(type(alias).__module__, type(alias).__name__,
                  alias.__origin__ is Box, alias.__args__, alias.__parameters__)
            print(alias is Box[int], alias is Box[int, str],
                  alias.__args__ is alias.__args__,
                  alias.__parameters__ is alias.__parameters__)
            partial = Box[T, int]
            print(partial.__parameters__ == (T,),
                  partial[str] is Box[str, int])
            raw = GenericAlias(Box, (int, str))
            print(alias == raw, raw == alias, alias != raw,
                  alias.__args__ == raw.__args__)
            print(alias().__orig_class__ is alias)
            print(type(Box.__orig_bases__[0]).__name__)
            print(hasattr(alias, "__unpacked__"), hasattr(alias, "__mro__"),
                  hasattr(alias, "__bases__"))
            print(alias.__name__, alias.__qualname__, alias.__module__)
            unpacked = next(iter(alias))
            print(type(unpacked).__name__, unpacked,
                  unpacked.__args__[0] is alias)
            class Default[T=int]:
                pass
            print(Default[()].__args__, Default[()] is Default[int])
        ''')

    def test_generic_arity_plain_subclasses_and_native_base_priority(self):
        self.run_source('''
            from typing import Generic, TypeVar
            class Box[T, U=str]:
                pass
            for key in [(), (int, str, bytes)]:
                try:
                    Box[key]
                except TypeError as error:
                    print(type(error).__name__)
            T = TypeVar("T")
            class Base(Generic[T]):
                pass
            class Plain(Base):
                pass
            class Fixed(Base[int]):
                pass
            print(Plain.__parameters__, Fixed.__parameters__)
            for cls in [Plain, Fixed]:
                try:
                    cls[int]
                except TypeError as error:
                    print(type(error).__name__)
            try:
                class Invalid(Generic):
                    pass
            except TypeError as error:
                print(type(error).__name__)
            class Native[T, U=str](list[T]):
                pass
            for key in [int, (), (int, str, bytes)]:
                alias = Native[key]
                print(type(alias).__name__, alias.__args__)
            class Override[T]:
                @classmethod
                def __class_getitem__(cls, key):
                    return "custom", key
            print(Override[int])
        ''')

    def test_call_metadata_and_exception_suppression_match_alias_kind(self):
        self.run_source('''
            from types import GenericAlias
            for exception in [AttributeError, TypeError, ValueError, RuntimeError]:
                class Box[T]:
                    def __setattr__(self, name, value):
                        raise exception("metadata")
                for alias in [Box[int], GenericAlias(Box, int)]:
                    try:
                        alias()
                        print("suppressed")
                    except Exception as error:
                        print(type(error).__name__)
            class Interrupted[T]:
                def __setattr__(self, name, value):
                    raise BaseException("metadata")
            try:
                Interrupted[int]()
            except BaseException as error:
                print(type(error).__name__)
        ''')
