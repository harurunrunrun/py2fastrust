"""Exception sentinels use actual classes, including subclasses and spoofing."""

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
def static_raise(error):
    raise error
def static_next(iterator, default):
    return next(iterator, default)
def static_delegate(iterator):
    return (yield from iterator)
def static_with(manager, error):
    with manager:
        raise error
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExceptionSubclassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-exception-subclasses-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="exception_subclasses.py", optimize=False))
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
            capture_output=True, text=True, timeout=20,
        )
        actual = subprocess.run(
            [str(self.binary)], input=source, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                             expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_stop_iteration_subclass_for_next_and_materialization(self):
        self.compare('''
            import gc
            class Finished(StopIteration): pass
            class Iterator:
                def __init__(self): self.position = 0
                def __iter__(self): return self
                def __next__(self):
                    gc.collect()
                    self.position += 1
                    if self.position > 2: raise Finished("finished")
                    return self.position
            print(list(Iterator()), tuple(Iterator()), sum(Iterator()))
            for value in Iterator(): print("for", value)
            else: print("complete")
            iterator = Iterator()
            print(next(iterator), next(iterator), static_next(iterator, "default"))
            iterator = Iterator()
            next(iterator); next(iterator)
            try: next(iterator)
            except Finished as error: print(type(error).__name__, error.value, error.args)
            print(list(map(lambda value: value + 1, Iterator())))
            from itertools import starmap, takewhile
            def finish(*args): raise Finished("callback")
            for iterator in [map(finish, [1]), filter(finish, [1]), iter(finish, "stop"),
                             starmap(finish, [(1,)]), takewhile(finish, [1])]:
                print(list(iterator))
        ''')

    def test_yield_from_subclass_value_and_pep479(self):
        self.compare('''
            import gc
            class Finished(StopIteration): pass
            class Iterator:
                def __iter__(self): return self
                def __next__(self):
                    error = Finished("original")
                    error.value = ["return value"]
                    gc.collect()
                    raise error
            generator = static_delegate(Iterator())
            try: next(generator)
            except StopIteration as error: print(error.value)
            def bad(error):
                yield "started"
                static_raise(error)
            for action in ["next", "send", "throw"]:
                error = Finished("explicit")
                generator = bad(error)
                print(next(generator))
                try:
                    if action == "next": next(generator)
                    elif action == "send": generator.send(None)
                    else: generator.throw(error)
                except BaseException as caught:
                    print(type(caught).__name__, str(caught),
                          caught.__cause__ is error, caught.__context__ is error,
                          caught.__suppress_context__)
        ''')

    def test_generator_exit_subclass_close_and_delegation(self):
        self.compare('''
            class Exit(GeneratorExit): pass
            def generator():
                try: yield "ready"
                finally: raise Exit("closed")
            iterator = generator()
            print(next(iterator), iterator.close())
            events = []
            class Delegate:
                def __iter__(self): return self
                def __next__(self): return 1
                def close(self): events.append("close")
                def throw(self, error):
                    events.append("throw")
                    raise error
            iterator = static_delegate(Delegate())
            print(next(iterator))
            try: iterator.throw(Exit("exit"))
            except Exit as error: print(type(error).__name__, error.args)
            print(events)
        ''')

    def test_attribute_error_subclasses_for_fallbacks_and_patterns(self):
        self.compare('''
            class Missing(AttributeError): pass
            class Object:
                def __getattribute__(self, name): raise Missing(name)
                def __getattr__(self, name):
                    if name == "found": return 17
                    raise Missing(name)
            value = Object()
            print(value.found, getattr(value, "missing", "default"),
                  hasattr(value, "missing"), hasattr(value, "found"))
            class Pattern:
                __match_args__ = ("item",)
                @property
                def item(self): raise Missing("item")
            match Pattern():
                case Pattern(item): print("wrong match")
                case _: print("no match")
            class Descriptor:
                def __get__(self, instance, owner): raise Missing("descriptor")
            class Described:
                attribute = Descriptor()
            print(getattr(Described(), "attribute", "missing descriptor"))
        ''')

    def test_mapping_key_error_subclass_for_namespaces(self):
        self.compare('''
            class Missing(KeyError): pass
            class Namespace:
                def __init__(self): self.values = {}
                def __getitem__(self, name):
                    if name not in self.values: raise Missing(name)
                    return self.values[name]
                def __setitem__(self, name, value): self.values[name] = value
                def __delitem__(self, name):
                    if name not in self.values: raise Missing(name)
                    del self.values[name]
            namespace = Namespace()
            exec("value = len([1, 2])", {}, namespace)
            print(namespace.values)
            class Meta(type):
                @classmethod
                def __prepare__(cls, name, bases): return Namespace()
                def __new__(cls, name, bases, namespace):
                    return super().__new__(cls, name, bases, namespace.values)
            class Example(metaclass=Meta):
                value = len([1, 2, 3])
            print(Example.value)
        ''')

    def test_sequence_sentinel_subclasses(self):
        self.compare('''
            class End(IndexError): pass
            class Finished(StopIteration): pass
            class Sequence:
                def __init__(self, error): self.error = error
                def __len__(self): return 4
                def __getitem__(self, index):
                    if index == 1 or index >= 3: raise self.error("end")
                    return index
            for error in [End, Finished]:
                print(list(Sequence(error)), list(reversed(Sequence(error))))
            from operator import length_hint
            class LengthError(TypeError): pass
            class Hinted:
                def __len__(self): raise LengthError("no length")
                def __length_hint__(self): return 7
            print(length_hint(Hinted(), 3))
        ''')

    def test_key_error_subclass_string_and_base_descriptor(self):
        self.compare('''
            class Missing(KeyError): pass
            for args in [(), ("missing",), (17,), ("a", "b")]:
                error = Missing(*args)
                print(str(error), repr(error), BaseException.__str__(error),
                      KeyError.__str__(error), error.args)
            for owner, method, value in [(KeyError, "__str__", ValueError("x")),
                                          (StopIteration, "__init__", ValueError("x")),
                                          (SystemExit, "__init__", ValueError("x"))]:
                try: getattr(owner, method)(value)
                except BaseException as error: print(type(error).__name__)
        ''')

    def test_sentinel_names_and_class_spoofing_do_not_change_matching(self):
        self.compare('''
            class Named(ValueError): pass
            Named.__name__ = "StopIteration"
            class Spoofed(ValueError):
                @property
                def __class__(self): return StopIteration
            for error in [Named("named"), Spoofed("spoofed")]:
                class Iterator:
                    def __iter__(self): return self
                    def __next__(self): raise error
                try: next(Iterator(), "wrong default")
                except ValueError as caught: print(caught is error, caught.args)
                try: static_raise(error)
                except StopIteration: print("wrong catch")
                except ValueError as caught: print("actual", caught is error)
            class SpoofedAttribute(ValueError):
                @property
                def __class__(self): return AttributeError
            class Object:
                def __getattr__(self, name): raise SpoofedAttribute(name)
            try: getattr(Object(), "missing", "wrong default")
            except ValueError as error: print(error.args)
        ''')

    def test_reported_names_do_not_select_native_fields_or_messages(self):
        self.compare('''
            class Named(ValueError): pass
            for name, field in [("StopIteration", "value"), ("SystemExit", "code"),
                                ("KeyError", "unused"), ("UnicodeDecodeError", "encoding")]:
                Named.__name__ = name
                error = Named("argument")
                print(name, str(error), hasattr(error, field))
            class Missing(KeyError): pass
            Missing.__name__ = "OtherName"
            error = Missing("key")
            print(str(error), BaseException.__str__(error), repr(error))
        ''')

    def test_dictionary_equality_errors_are_not_missing_keys(self):
        self.compare('''
            class Missing(KeyError): pass
            for error_type in [KeyError, Missing]:
                class Key:
                    def __hash__(self): return 1
                    def __eq__(self, other): raise error_type("comparison")
                dictionary = {Key(): "value"}
                for get in [dictionary.get, dictionary.keys().mapping.get]:
                    try: print(get(Key(), "wrong default"))
                    except KeyError as error: print(type(error).__name__, error.args)
        ''')

    def test_attribute_subclass_vars_and_generic_construction(self):
        self.compare('''
            import types
            class Missing(AttributeError): pass
            class Invalid(TypeError): pass
            class NoDictionary:
                @property
                def __dict__(self): raise Missing("dictionary")
            try: vars(NoDictionary())
            except BaseException as error: print(type(error).__name__)
            for error_type in [Missing, Invalid, ValueError]:
                class Generic:
                    def __setattr__(self, name, value): raise error_type(name)
                try:
                    value = types.GenericAlias(Generic, int)()
                    print(type(value).__name__)
                except BaseException as error: print(type(error).__name__)
            from typing import Generic, TypeVar
            T = TypeVar("T")
            class Typed(Generic[T]): pass
            for error_type in [TypeError, Invalid, ValueError]:
                class Meta(type):
                    def __hash__(cls): raise error_type("hash")
                class Argument(metaclass=Meta): pass
                try:
                    first = Typed[Argument]
                    second = Typed[Argument]
                    print(first is second, first.__args__[0] is Argument)
                except BaseException as error: print(type(error).__name__)
        ''')

    def test_sequence_exhaustion_and_reversed_protocol_side_effects(self):
        self.compare('''
            class End(IndexError): pass
            events = []
            class Sequence:
                def __len__(self): events.append("len"); return 3
                def __getitem__(self, index):
                    events.append(index)
                    if index == 1: raise End(index)
                    return index
            for factory in [iter, reversed]:
                iterator = factory(Sequence())
                print("created", events)
                print(next(iterator, "end"), next(iterator, "end"), next(iterator, "end"))
                print(events)
                events.clear()
            class Custom:
                def __reversed__(self): return iter([7, 8])
            print(list(reversed(Custom())))
        ''')

    def test_existing_instances_follow_class_rename_for_display_only(self):
        self.compare('''
            class OldStop(StopIteration): pass
            class OldKey(KeyError): pass
            class OldGroup(ExceptionGroup): pass
            stop = OldStop("done")
            key = OldKey("key")
            group = OldGroup("group", [key])
            OldStop.__name__ = "NewStop"
            OldKey.__name__ = "NewKey"
            OldGroup.__name__ = "NewGroup"
            print(type(stop).__name__, repr(stop), stop.value)
            print(type(key).__name__, repr(key), str(key), BaseException.__repr__(key))
            print(type(group).__name__, repr(group), str(group))
            class Iterator:
                def __iter__(self): return self
                def __next__(self): raise stop
            print(next(Iterator(), "default"), list(Iterator()))
        ''')
        self.compare('''
            class Original(ValueError): pass
            error = Original("argument")
            Original.__name__ = "Changed"
            raise error
        ''')
        self.compare('''
            class Original(ValueError): pass
            error = Original("argument")
            Original.__qualname__ = "Qualified"
            Original.__module__ = "custom_module"
            raise error
        ''')

    def test_special_descriptor_attribute_errors_are_not_absent_methods(self):
        self.compare('''
            import math
            from operator import length_hint
            class Missing(AttributeError): pass
            for error_type in [AttributeError, Missing]:
                class Descriptor:
                    def __get__(self, instance, owner): raise error_type("descriptor")
                class Number:
                    __int__ = Descriptor()
                    __float__ = Descriptor()
                    __complex__ = Descriptor()
                    __bytes__ = Descriptor()
                    __str__ = Descriptor()
                    def __index__(self): return 3
                for convert in [int, float, complex, bytes, str, math.sqrt]:
                    try: convert(Number())
                    except BaseException as error: print(convert.__name__, type(error).__name__)
            class Rounded:
                __ceil__ = Descriptor()
                __floor__ = Descriptor()
                __trunc__ = Descriptor()
                def __float__(self): return 2.75
            for convert in [math.ceil, math.floor, math.trunc]:
                try: print(convert.__name__, convert(Rounded()))
                except BaseException as error: print(convert.__name__, type(error).__name__)
            class Hidden:
                def __getattribute__(self, name): raise Missing(name)
                def __float__(self): return 2.25
                def __ceil__(self): return 8
            print(math.ceil(Hidden()), math.floor(Hidden()), math.sqrt(Hidden()))
            class Hinted:
                __length_hint__ = Descriptor()
            try: length_hint(Hinted())
            except BaseException as error: print(type(error).__name__)
        ''')

    def test_index_descriptor_errors_and_mapping_attribute_fallback(self):
        self.compare('''
            class Missing(AttributeError): pass
            class Descriptor:
                def __get__(self, instance, owner): raise Missing("index")
            class Index:
                __index__ = Descriptor()
            for operation in [lambda: range(Index()), lambda: [7][Index()],
                              lambda: bytes(Index())]:
                try: operation()
                except BaseException as error: print(type(error).__name__)
            class Dictionary(dict): pass
            for error_type in [Missing, ValueError]:
                class Pairs:
                    @property
                    def keys(self): raise error_type("keys")
                    def __iter__(self): return iter([("key", 17)])
                for constructor in [dict, Dictionary]:
                    try: print(constructor(Pairs()))
                    except BaseException as error: print(type(error).__name__)
        ''')

    def test_with_and_exc_info_use_native_metadata_despite_spoofing(self):
        self.compare('''
            import sys
            class Error(ValueError):
                @property
                def __class__(self): return KeyError
                @property
                def __traceback__(self): return "spoofed traceback"
            class Manager:
                def __enter__(self): return self
                def __exit__(self, cls, error, traceback):
                    print(cls is Error, error.__class__ is KeyError,
                          error.__traceback__, traceback is sys.exc_info()[2],
                          hasattr(traceback, "tb_frame"))
                    return True
            type = lambda value: KeyError
            static_with(Manager(), Error("static"))
            with Manager(): raise Error("dynamic")
        ''')


if __name__ == "__main__":
    unittest.main()
