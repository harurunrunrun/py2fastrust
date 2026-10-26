"""Slot descriptors, storage, inheritance and GC versus CPython."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class SlotTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_storage_private_names_and_attribute_errors(self):
        self.run_source('''
            class Point:
                __slots__ = ("x", "__hidden")
                def __init__(self, x):
                    self.x = x
                    self.__hidden = x + 1
                def hidden(self): return self.__hidden
            point = Point(3)
            print(point.x, point.hidden(), hasattr(point, "__dict__"), Point.x.__name__)
            print(Point.x.__objclass__ is Point, Point.x.__get__(None, Point) is Point.x)
            for operation in [lambda: setattr(point, "extra", 1), lambda: vars(point)]:
                try: operation()
                except Exception as error: print(type(error).__name__)
            del point.x
            print(hasattr(point, "x"))
            try: del point.x
            except AttributeError: print("missing")
            Point.x.__set__(point, 7)
            print(point.x, Point.x.__get__(point, Point))
            Point.x.__delete__(point)
            print(hasattr(point, "x"))
        ''')

    def test_inherited_same_name_has_distinct_storage(self):
        self.run_source('''
            class Base:
                __slots__ = ("x",)
            class Child(Base):
                __slots__ = ("x", "y")
            child = Child()
            Base.x.__set__(child, 1)
            Child.x.__set__(child, 2)
            child.y = 3
            print(child.x, child.y, Base.x.__get__(child, Child), hasattr(child, "__dict__"))
            del child.x
            print(hasattr(child, "x"), Base.x.__get__(child, Child))
            try: Base.x.__get__(object(), object)
            except TypeError: print("wrong owner")
            class Empty(Base): __slots__ = ()
            value = Empty()
            value.x = 4
            print(value.x, hasattr(value, "__dict__"))
        ''')

    def test_dictionary_slots_and_inherited_dictionaries(self):
        self.run_source('''
            class Both:
                __slots__ = ("x", "__dict__", "__weakref__")
            value = Both()
            value.x, value.extra = 1, 2
            value.__dict__["x"] = 99
            print(value.x, vars(value), value.__weakref__)
            replacement = {"new": 3}
            value.__dict__ = replacement
            print(value.__dict__ is replacement, value.new, value.x)
            del value.__dict__
            print(replacement, vars(value), value.x)
            class Loose: pass
            class Child(Loose): __slots__ = ()
            child = Child()
            child.extra = 4
            print(child.extra, hasattr(child, "__dict__"))
            class Tight: __slots__ = ()
            class Grandchild(Tight): pass
            grandchild = Grandchild()
            grandchild.extra = 5
            print(grandchild.extra, hasattr(grandchild, "__dict__"))
        ''')

    def test_native_payload_slots_and_gc_cycles(self):
        self.run_source('''
            import gc
            class Values(list): __slots__ = ("tag",)
            values = Values([1, 2])
            values.tag = "ok"
            print(values, values.tag, hasattr(values, "__dict__"))
            try: values.extra = 3
            except AttributeError: print("blocked")
            seen = []
            saved = []
            class Node:
                __slots__ = ("link", "number")
                def __del__(self):
                    seen.append(self.number)
                    saved.append(self)
            node = Node()
            node.link, node.number = node, 7
            del node
            gc.collect()
            print(seen, saved[0].link is saved[0], saved[0].number)
            saved.clear()
            gc.collect()
            print(seen)
        ''')

    def test_slot_definition_validation_and_layout_conflicts(self):
        self.run_source('''
            cases = [
                "class C: __slots__ = ('bad-name',)",
                "class C: __slots__ = (1,)",
                "class C: __slots__ = ('x',); x = 1",
                "class C: __slots__ = ('__dict__', '__dict__')",
                "class C(int): __slots__ = ('x',)",
                "class A: pass\\nclass C(A): __slots__ = ('__dict__',)",
                "class A: __slots__ = ('x',)\\nclass B: __slots__ = ('y',)\\nclass C(A, B): __slots__ = ()",
            ]
            for source in cases:
                try: exec(source, {})
                except Exception as error: print(type(error).__name__)
        ''')


if __name__ == "__main__":
    unittest.main()
