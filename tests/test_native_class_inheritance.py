"""Single inheritance between module-level source classes, compared with CPython."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeClassInheritanceTests(unittest.TestCase):
    def test_overrides_dispatch_through_inherited_methods(self):
        compare(self, '''class Meter:
    def __init__(self, scale):
        self.scale = scale
    def unit(self):
        return "m"
    def read(self, raw):
        return str(raw * self.scale) + self.unit()
class Kilometer(Meter):
    def unit(self):
        return "km"
class Tagged(Kilometer):
    def read(self, raw):
        return "<" + Meter.read(self, raw) + ">"
for gauge in [Meter(2), Kilometer(3), Tagged(4)]:
    print(gauge.read(5), gauge.unit())
value = Tagged(1)
print(value.scale, value.read(7))
''', '')

    def test_zero_argument_super_chains(self):
        compare(self, '''class Layer:
    def __init__(self, depth):
        super().__init__()
        self.trail = [depth]
    def weight(self, n):
        return n
class Middle(Layer):
    def __init__(self, depth):
        super().__init__(depth + 1)
        self.trail.append(depth)
    def weight(self, n):
        return super().weight(n) * 3
class Top(Middle):
    def __init__(self):
        super().__init__(10)
        self.trail.append(0)
    def weight(self, n):
        return super().weight(n) + 1
top = Top()
print(top.trail, top.weight(2), Middle(5).weight(2), Layer(1).weight(2))
''', '')

    def test_class_attributes_are_shared_until_overridden(self):
        compare(self, '''class Counter:
    label = "base"
    made = 0
    def __init__(self):
        Counter.made += 1
    def describe(self):
        return self.label + ":" + str(self.made)
class Loud(Counter):
    label = "loud"
class Quiet(Counter):
    pass
group = [Counter(), Loud(), Quiet(), Loud()]
for item in group:
    print(item.describe(), item.label)
print(Counter.made, Loud.made, Quiet.label, Loud.label)
''', '')

    def test_instance_checks_narrow_subclasses(self):
        compare(self, '''class Shape:
    def __init__(self, size):
        self.size = size
class Square(Shape):
    def area(self):
        return self.size * self.size
class Other:
    pass
total = 0
for shape in [Shape(1), Square(3), Shape(2), Square(4)]:
    if isinstance(shape, Square):
        total += shape.area()
    elif isinstance(shape, Shape):
        total -= shape.size
print(total)
print(isinstance(Square(1), Shape), isinstance(Shape(1), Square), isinstance(Other(), Shape), isinstance(Square(2), (Other, Shape)))
''', '')

    def test_inherited_special_methods_classmethods_and_properties(self):
        compare(self, '''class Money:
    def __init__(self, cents):
        self.cents = cents
    def __repr__(self):
        return "Money(" + str(self.cents) + ")"
    def __lt__(self, other):
        return self.cents < other.cents
    def __eq__(self, other):
        return self.cents == other.cents
    @classmethod
    def whole(cls, units):
        return cls(units * 100)
    @property
    def units(self):
        return self.cents // 100
class Tip(Money):
    pass
tips = [Tip(250), Tip.whole(1), Tip(75)]
print(sorted(tips), Tip(5) == Tip(5), Tip(1) < Tip(2), Tip(250).units)
''', '')

    def test_truth_and_length_follow_the_mro(self):
        compare(self, '''class Plain:
    pass
class Child(Plain):
    pass
class Sized:
    def __init__(self, n):
        self.n = n
    def __len__(self):
        return self.n
class Bag(Sized):
    pass
for value in [Child(), Bag(0), Bag(3)]:
    print(bool(value), "yes" if value else "no")
print(len(Bag(5)))
''', '')

    def test_inherited_classmethods_bind_the_receiving_class(self):
        compare(self, '''class Unit:
    symbol = "u"
    @classmethod
    def label(cls):
        return cls.symbol
    @classmethod
    def build(cls):
        return cls()
    def show(self):
        return self.label()
class Gram(Unit):
    symbol = "g"
class Plain(Unit):
    pass
print(Unit.label(), Gram.label(), Plain.label(), Gram().show(), Unit().show())
print(type(Gram.build()) is Gram, type(Unit.build()) is Unit, Gram.build().show())
''', '')

    def test_missing_fields_mangling_and_errors_follow_the_receiver(self):
        compare(self, '''class Vault:
    def __init__(self):
        self.__secret = 7
        self.open = True
    def reveal(self):
        return self.__secret
    def check(self, n):
        if n > 3:
            raise ValueError("too many: " + str(n))
        return n
class Child(Vault):
    def __init__(self):
        self.kind = "child"
    def peek(self):
        return self.__secret
class Heir(Vault):
    def peek(self):
        return self.__secret
print(Heir().reveal(), Heir().check(2))
for probe in [lambda: Child().reveal(), lambda: Heir().peek(), lambda: Child().open]:
    try:
        print(probe())
    except AttributeError as error:
        print("AttributeError", error)
try:
    Heir().check(9)
except ValueError as error:
    print("caught", error)
Child().check(5)
''', '')

    def test_unproved_inheritance_stays_positioned(self):
        sources = {
            'class A:\n    n = 1\nclass B(A):\n    pass\nB.n = 2\nprint(A.n, B.n)\n': 5,
            'class A:\n    pass\nclass B(A):\n    pass\nA = 3\nprint(B)\n': 3,
            'class A:\n    __slots__ = ("x",)\nclass B(A):\n    pass\nprint(B())\n': 3,
            'class A:\n    def f(self):\n        return 1\nclass B(A):\n    def f(self):\n        g = lambda: super().f()\n        return g()\nprint(B().f())\n': 6,
        }
        for source, line in sources.items():
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='inherit.py', license='none'))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code, 'E006')
                self.assertEqual(result.diagnostics[0].line, line)


if __name__ == '__main__':
    unittest.main()
