"""Native storage and constructor behavior for subclasses of built-in types."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class BuiltinInstanceTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_mutable_payload_construction_and_aliases(self):
        self.run_source('''
            class L(list): pass
            a = L([1, 2])
            a.extra = 'value'
            alias = a
            a.append(3)
            a[0] = 8
            del a[1]
            a += [9]
            a *= 2
            print(type(a).__name__, a, list(a), a.extra, alias is a, len(a), isinstance(a, list))
            print(type(a.copy()).__name__, a[:2], a + [10], [10] + a)
            list.__init__(a, [4, 5])
            print(alias, list.__new__(L, [100]))
            a.__init__(a)
            print(a)
            class D(dict): pass
            d = D([('a', 1)], b=2)
            d.extra = 9
            alias = d
            d['c'] = 3
            d |= {'d': 4}
            print(type(d).__name__, dict(d), list(d), alias is d, d.extra)
            dict.__init__(d, {'a': 7}, z=9)
            dict.__setitem__(d, 'base', 8)
            print(dict(d), dict.__getitem__(d, 'base'), d.get('missing', 5))
            print(type(d.copy()).__name__, dict.__new__(D, {'ignored': 1}))
            class S(set): pass
            s = S([3, 1, 3])
            s.extra = 8
            alias = s
            s.add(2)
            s |= {4}
            print(type(s).__name__, sorted(s), alias is s, s.extra, len(s), 2 in s)
            set.__init__(s, [7, 7, 8])
            print(sorted(s), type(s.copy()).__name__)
            s.__init__(s)
            print(sorted(s))
            for value in [a, d, s]:
                try:
                    hash(value)
                except TypeError:
                    print('unhashable')
        ''')

    def test_immutable_payload_numbers_strings_and_slots(self):
        self.run_source('''
            class I(int): pass
            n = I('ff', base=16)
            n.extra = 3
            print(type(n).__name__, isinstance(n, int), n, int(n), n.extra, hash(n) == hash(255))
            print(n+2, 2+n, n*3, -n, ~n, n<<2, bin(n), oct(n), hex(n), format(n, '#08x'))
            print(type(int.__new__(int, 3)).__name__, type(int.__new__(I, 3)).__name__)
            class T(str): pass
            s = T('hello')
            s.extra = 7
            print(type(s).__name__, isinstance(s, str), str(s), repr(s), s.extra, len(s), s[1], s[:2])
            print(s.upper(), s+'!', '!'+s, s*2, hash(s) == hash('hello'))
            class Tight(list): __slots__ = ()
            t = Tight([1, 2])
            print(t, hasattr(t, '__dict__'))
            try:
                t.extra = 2
            except AttributeError:
                print('slotted')
            class HasDict(list): pass
            class Child(HasDict): __slots__ = ()
            c = Child([1])
            c.extra = 4
            print(c, c.extra, hasattr(c, '__dict__'))
        ''')

    def test_custom_initializers_and_partial_mutation(self):
        self.run_source('''
            class L(list):
                def __init__(self, values):
                    super().__init__(values)
                    self.append(9)
            print(L([1, 2]))
            class D(dict):
                def __init__(self, **kwargs):
                    super().__init__(kwargs)
                    self['extra'] = 4
            print(dict(D(a=1)))
            def bad():
                yield 1
                raise ValueError('stop')
            class A(list): pass
            class B(set): pass
            for cls in [A, B]:
                value = cls([4, 5])
                try:
                    value.__init__(bad())
                except ValueError:
                    print(sorted(value))
            d = D()
            try:
                dict.__init__(d, [('ok', 2), ('bad',)])
            except ValueError:
                print(dict(d))
            for operation in [lambda: A(1, 2), lambda: A(unknown=2), lambda: B(unknown=2),
                              lambda: int.__new__(int, '1', base=1)]:
                try:
                    operation()
                except Exception as error:
                    print(type(error).__name__)
        ''')


if __name__ == "__main__":
    unittest.main()
