"""Class argument expansion shares evaluation and mapping rules with CPython."""

import shutil
import textwrap
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ClassUnpackingTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare_both(self, source):
        source = textwrap.dedent(source)
        return self.run_source(source + "\nprint('dynamic')\nexec(" + repr(source) + ")\n")

    def test_multiple_starred_bases_consume_before_keywords(self):
        self.compare_both('''
            events = []
            class Left: pass
            class Right: pass
            class Bases:
                def __init__(self, name, values): self.name = name; self.values = values
                def __iter__(self):
                    events.append("iter " + self.name)
                    for value in self.values:
                        events.append("yield " + value.__name__)
                        yield value
            def mark(name, value): events.append(name); return value
            class Meta(type):
                @classmethod
                def __prepare__(cls, name, bases, **kwargs):
                    events.append(("prepare", tuple(base.__name__ for base in bases), kwargs))
                    return {}
                def __new__(cls, name, bases, namespace, **kwargs):
                    events.append(("new", kwargs))
                    return super().__new__(cls, name, bases, namespace)
            class Example(*mark("first", Bases("first", [Left])),
                          *mark("empty", Bases("empty", [])),
                          *mark("last", Bases("last", [Right])),
                          flag=mark("keyword", 7),
                          **mark("mapping", {"metaclass": Meta})):
                events.append("body")
            print(Example.__bases__ == (Left, Right), events)
        ''')

    def test_keyword_mapping_consumption_duplicates_and_invalid_inputs(self):
        self.compare_both('''
            events = []
            class Meta(type):
                @classmethod
                def __prepare__(cls, name, bases, **kwargs): events.append("prepare"); return {}
                def __new__(cls, name, bases, namespace, **kwargs):
                    return super().__new__(cls, name, bases, namespace)
            class Mapping:
                def __init__(self, keys): self.names = keys
                def keys(self):
                    events.append("keys")
                    def names():
                        for name in self.names:
                            events.append(("key", name))
                            yield name
                    return names()
                def __getitem__(self, key): events.append(("getitem", key)); return 17
            for mapping in [Mapping(["flag", "flag"]), Mapping(["flag"]),
                            Mapping([1]), [("flag", 3)], 1, Mapping([[]])]:
                events.clear()
                try:
                    class Example(*[], metaclass=Meta, flag=1, **mapping):
                        events.append("body")
                except BaseException as error: print(type(error).__name__, events)
            events.clear()
            class Example(*[], metaclass=Meta, **Mapping(["x", "y"])): pass
            print(events)
        ''')

    def test_expanded_keywords_metaclass_prepare_decorators_and_mro_entries(self):
        self.compare_both('''
            events = []
            class Base:
                def method(self): return "base"
            class Entry:
                def __mro_entries__(self, bases):
                    events.append(("mro", len(bases), bases[0] is self))
                    return (Base,)
            class Namespace:
                def __init__(self): self.data = {}
                def __getitem__(self, name): return self.data[name]
                def __setitem__(self, name, value): self.data[name] = value
                def keys(self): return self.data.keys()
            class Meta(type):
                @classmethod
                def __prepare__(cls, name, bases, **kwargs):
                    events.append(("prepare", kwargs))
                    return Namespace()
                def __new__(cls, name, bases, namespace, **kwargs):
                    events.append(("new", kwargs, "__orig_bases__" in namespace.data))
                    return super().__new__(cls, name, bases, dict(namespace))
            def decorator(label):
                events.append("evaluate " + label)
                def apply(cls): events.append("apply " + label); return cls
                return apply
            original = Entry()
            @decorator("outer")
            @decorator("inner")
            class Example(*[original], **{"metaclass": Meta}, flag=3, **{"other": 4}):
                def method(self): return super().method() + " child"
            print(Example().method(), Example.__orig_bases__[0] is original, events)
        ''')

    def test_generic_classes_defaults_alias_bases_and_closure_metadata(self):
        self.compare_both('''
            import gc
            def outer(value):
                class Base:
                    def method(self): return value
                bases = [Base]
                class Generic[T = int](*bases, **{}):
                    item: T
                    def method(self): return super().method() + 1
                return Generic
            Generic = outer(7)
            gc.collect()
            print(Generic().method(), Generic.__type_params__[0].__default__,
                  Generic.__annotations__["item"] is Generic.__type_params__[0],
                  Generic[int].__origin__ is Generic,
                  [base.__name__ for base in Generic.__bases__])
            class Listing(*[list[int]], **{}): pass
            print(Listing.__bases__, Listing.__orig_bases__)
        ''')

    def test_gc_keeps_expanded_bases_mapping_values_and_keys_alive(self):
        self.compare_both('''
            import gc
            events = []
            def bases():
                class Base: pass
                events.append("bases")
                yield Base
                gc.collect()
            class Mapping:
                def keys(self):
                    return (name for name in ["metaclass", "first", "second"])
                def __getitem__(self, name):
                    gc.collect()
                    if name == "metaclass": return Meta
                    return [name]
            class Meta(type):
                @classmethod
                def __prepare__(cls, name, bases, **kwargs):
                    gc.collect()
                    events.append(("prepare", bases[0].__name__, kwargs))
                    return {}
                def __new__(cls, name, bases, namespace, **kwargs):
                    gc.collect()
                    result = super().__new__(cls, name, bases, namespace)
                    result.payload = kwargs
                    return result
            class Example(*bases(), **Mapping()): pass
            gc.collect()
            print(Example.__bases__[0].__name__, Example.payload, events)
        ''')

    def test_string_subclass_keys_use_native_spelling_and_dict_fast_path(self):
        self.compare_both('''
            events = []
            class Key(str):
                def __str__(self): return "wrong spelling"
            class Meta(type):
                def __new__(cls, name, bases, namespace, **kwargs):
                    result = super().__new__(cls, name, bases, namespace)
                    result.answer = kwargs["answer"]
                    return result
            class Mapping:
                def keys(self): return [Key("metaclass"), Key("answer")]
                def __getitem__(self, key): return Meta if key == "metaclass" else 42
            class Example(**Mapping()): pass
            print(Example.answer)
            class Dictionary(dict):
                def keys(self): events.append("keys"); return []
                def __getitem__(self, key): events.append("getitem"); return None
            class Other(*[], **Dictionary(metaclass=Meta, answer=17)): pass
            print(Other.answer, events)
        ''')

    def test_expansion_failures_stop_later_evaluation(self):
        self.compare_both('''
            events = []
            def mark(name, value): events.append(name); return value
            try:
                class Bad(*mark("bad base", 1),
                          metaclass=mark("wrong keyword", type),
                          **mark("wrong mapping", {})): pass
            except TypeError: print(events)
            events.clear()
            try:
                class Bad(*mark("base", []),
                          **mark("first", {"metaclass": type}),
                          **mark("duplicate", {"metaclass": type}),
                          flag=mark("wrong later", 1)): pass
            except TypeError: print(events)
        ''')

    def test_keywords_reach_cooperative_init_subclass_and_default_rejects_them(self):
        self.compare_both('''
            events = []
            class Left:
                def __init_subclass__(cls, *, left=1, **kwargs):
                    events.append(("left", cls.__name__, left))
                    super().__init_subclass__(**kwargs)
            class Right:
                def __init_subclass__(cls, *, right=2, **kwargs):
                    events.append(("right", cls.__name__, right))
                    super().__init_subclass__(**kwargs)
            class Example(*[Left], *[Right], **{"left": 7}, right=8): pass
            print(events, isinstance(Left.__dict__["__init_subclass__"], classmethod))
            print(object.__init_subclass__())
            events.clear()
            try:
                class Bad(*[], **{"unknown": 1}): events.append("body")
            except TypeError: print("rejected", events)
            try:
                class Bad(*[Left, Right], **{"unknown": 1}): pass
            except TypeError: print("forwarded", events)
        ''')

    def test_most_derived_metaclass_conflicts_and_callable_factories(self):
        self.compare_both('''
            events = []
            class First(type): pass
            class Derived(First): pass
            class Other(type): pass
            class A(metaclass=First): pass
            class B(metaclass=Derived): pass
            class C(metaclass=Other): pass
            class Combined(*[A, B], **{}): pass
            print(type(Combined) is Derived)
            try:
                class Conflict(*[A, C], **{}): events.append("wrong body")
            except TypeError: print("conflict", events)
            def factory(name, bases, namespace, **kwargs):
                return name, bases, namespace["value"], kwargs
            class Result(*[17], **{"metaclass": factory, "flag": 3}): value = 9
            print(Result)
            saved = {}
            def non_type(name, bases, namespace, **kwargs): saved.update(namespace); return 42
            class Value(*[], **{"metaclass": non_type}):
                def method(self): return __class__
            print(Value)
            try: saved["method"](None)
            except NameError as error: print(type(error).__name__)
        ''')

    def test_init_subclass_descriptors_receive_class_binding_and_validate_cells(self):
        self.compare_both('''
            class Descriptor:
                def __get__(self, instance, owner):
                    print(instance is None, owner.__name__)
                    return lambda **kwargs: print(kwargs)
            class Base: __init_subclass__ = Descriptor()
            class Child(*[Base], **{"flag": 3}): pass
            class WrongCell(type):
                def __new__(cls, name, bases, namespace):
                    result = super().__new__(cls, name, bases, namespace)
                    namespace["__classcell__"].cell_contents = int
                    return result
            try:
                class Invalid(*[], **{"metaclass": WrongCell}):
                    def method(self): return __class__
            except TypeError as error: print(type(error).__name__)
        ''')

    def test_fresh_mro_bases_and_prepare_metadata_survive_callback_gc(self):
        self.compare_both('''
            import gc
            class Entry:
                def __mro_entries__(self, bases):
                    class Fresh: pass
                    return (Fresh,)
            class Collect:
                def __mro_entries__(self, bases): gc.collect(); return ()
            class Expanded(*[Entry(), Collect()], **{}): pass
            print(Expanded.__bases__[0].__name__)
            class Namespace:
                def __init__(self): self.data = {}
                def __getitem__(self, key): return self.data[key]
                def __setitem__(self, key, value):
                    gc.collect()
                    self.data[key] = value
                def keys(self): return self.data.keys()
            class Meta(type):
                @classmethod
                def __prepare__(cls, name, bases): return Namespace()
                def __new__(cls, name, bases, namespace):
                    print("bases", len(bases))
                    return super().__new__(cls, name, bases, dict(namespace))
            class Prepared(*[], **{"metaclass": Meta}): pass
            print(Prepared.__name__)
        ''')


if __name__ == "__main__":
    unittest.main()
