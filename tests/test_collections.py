"""Differential coverage for the five bundled collections implementations."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class CollectionsTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_deque_public_api(self):
        self.run_source('''
            from collections import deque
            d = deque(range(20), maxlen=24)
            for i in range(25):
                d.append(i)
                d.appendleft(-i)
                if i % 2:
                    d.pop()
                if i % 3:
                    d.popleft()
                d.rotate(i - 12)
            print(d, len(d), d.maxlen, list(reversed(d)))
            d[2] = 77
            d[-1] = 77
            print(d.count(77), d.index(77), d.index(77, -3), 77 in d)
            del d[-2]
            d.insert(-2, 88)
            d.remove(88)
            d.reverse()
            print(d, d.copy() == d, d + deque([100]), d * 2)
            alias = d
            d += [2, 3]
            d *= 2
            print(alias is d, list(d), d < deque([1000]))
            d.clear()
            d.extend([1, 2])
            d.extendleft(d)
            print(d)
            d = deque(maxlen=0)
            d.extend(range(100))
            print(d, list(d), len(d))
            try:
                hash(d)
            except Exception as error:
                print(type(error).__name__)
            d = deque()
            d.append(d)
            print(d)
            class Index:
                def __index__(self): return 1
            d = deque([5, 6, 7])
            print(d[Index()])
            d.rotate(Index())
            print(d)
            for operation in [lambda: deque([], -1), lambda: deque([], 1.5),
                              lambda: d[10], lambda: d[1:2], lambda: d.index(100),
                              lambda: deque([], 0).insert(0, 1)]:
                try:
                    operation()
                except Exception as error:
                    print(type(error).__name__)
        ''')

    def test_deque_iteration_mutation(self):
        self.run_source('''
            from collections import deque
            for action in [lambda d: d.append(5), lambda d: d.rotate(0),
                           lambda d: d.reverse(), lambda d: d.__setitem__(1, 9),
                           lambda d: d.clear()]:
                d = deque([1, 2, 3])
                it = iter(d)
                print(next(it))
                action(d)
                try:
                    print(list(it))
                except RuntimeError:
                    print('mutated')
            for action in [lambda d: d.clear(), lambda d: d.append(5),
                           lambda d: d.extend([]), lambda d: d.extend([5])]:
                d = deque(maxlen=0)
                it = iter(d)
                action(d)
                try:
                    print(next(it))
                except Exception as error:
                    print(type(error).__name__)
            class Mutating:
                def __eq__(self, other):
                    d.clear()
                    return True
            d = deque([Mutating()])
            try:
                print(0 in d)
            except RuntimeError:
                print('mutated during comparison')
            for operation in [lambda: d.index(0), lambda: d.remove(0), lambda: d.count(0)]:
                d = deque([Mutating()])
                try:
                    print(operation())
                except Exception as error:
                    print(type(error).__name__)
        ''')

    def test_defaultdict_public_api_and_views(self):
        self.run_source('''
            from collections import defaultdict
            d = defaultdict(list, a=[1])
            d['b'].append(2)
            print(dict(d), d.default_factory is list, d.get('x'), 'x' in d)
            print(isinstance(d, dict), issubclass(defaultdict, dict))
            print(d.setdefault('x'), d.pop('x'), d.pop('x', 9))
            copied = d.copy()
            print(type(copied).__name__, copied.default_factory is list,
                  copied['a'] is d['a'], copied == d, d == dict(d), dict(d) == d)
            shared = []
            x = defaultdict.fromkeys(['a', 'b'], shared)
            x['a'].append(7)
            print(dict(x), x.default_factory, x['a'] is x['b'])
            print(dict(d | {'c': 3}), dict({'c': 3} | d))
            alias = d
            d |= [('q', 9)]
            print(alias is d, dict(d))
            keys, values, items = d.keys(), d.values(), d.items()
            print(type(keys).__name__, type(values).__name__, type(items).__name__)
            d['z'] = 10
            print(list(keys), list(values), list(items), list(reversed(keys)))
            print(sorted(keys & {'a', 'z'}), sorted(keys | {'new'}), keys.isdisjoint({'unknown'}))
            print(('q', 9) in items, ['q', 9] in items, 10 in values)
            proxy = keys.mapping
            print(type(proxy).__name__, len(proxy), list(proxy), proxy['q'], dict(proxy))
            d['q'] = 11
            print(proxy.get('q'), list(proxy.values()))
            left = defaultdict(None, a=[]).items()
            right = defaultdict(None, a=[]).items()
            print(left == right, left <= right, left & [], left ^ right)
            try:
                proxy['q'] = 1
            except Exception as error:
                print(type(error).__name__)
            d = defaultdict(None)
            d['self'] = d
            print(d)
            for operation in [lambda: defaultdict(1), lambda: defaultdict(None)['bad'],
                              lambda: d | [('a', 1)]]:
                try:
                    operation()
                except Exception as error:
                    print(type(error).__name__)
        ''')

    def test_counter_operations(self):
        self.run_source('''
            from collections import Counter
            c = Counter('abac')
            c.subtract('bcdd')
            c.update({'x': 0, 'y': -2})
            c.update(z=3)
            print(c, c.total(), c.most_common(), c.most_common(2), list(c.elements()))
            print(c['missing'], 'missing' in c, dict(c))
            print(Counter({'a': 'text'}), Counter(iterable=2))
            a = Counter(a=3, b=0, c=-2)
            b = Counter(a=1, b=2, d=4)
            print(a+b, a-b, a&b, a|b, +a, -a)
            print(Counter(a=1) == Counter(a=1, b=0), Counter(a=1) <= Counter(a=2),
                  Counter(a=1) < Counter(a=2), Counter(a=2) >= Counter(a=1),
                  Counter(a=2) > Counter(a=1), Counter(a=1) == {'a': 1},
                  {'a': 1} == Counter(a=1), Counter(a=1, b=0) == {'a': 1})
            for operation in ['+', '-', '&', '|']:
                x = a.copy()
                alias, keys = x, x.keys()
                if operation == '+': x += b
                elif operation == '-': x -= b
                elif operation == '&': x &= b
                else: x |= b
                print(operation, x, alias is x, list(keys))
            x = Counter(a=1)
            x += {'b': 2}
            x -= {'a': 3}
            x |= {'c': 7}
            print(x, x.copy() == x, x.setdefault('new', 9), x.pop('new'))
            x.clear()
            print(x, x.total())
            for operation in [lambda: Counter.fromkeys('a'), lambda: a + {},
                              lambda: a < {}, lambda: Counter(x=1.5).elements().__next__()]:
                try:
                    operation()
                except Exception as error:
                    print(type(error).__name__)
        ''')

    def test_ordereddict_public_api(self):
        self.run_source('''
            from collections import OrderedDict
            d = OrderedDict([('a', 1), ('b', 2), ('c', 3)])
            keys, values, items = d.keys(), d.values(), d.items()
            d.move_to_end('a')
            d.move_to_end('c', last=False)
            d['b'] = 20
            print(d, list(keys), list(values), list(items), list(reversed(d)))
            print(list(reversed(keys)), list(reversed(values)), list(reversed(items)))
            print(type(keys).__name__, type(values).__name__, type(items).__name__)
            print(d == OrderedDict(reversed(list(d.items()))), d == dict(d), dict(d) == d)
            copy = d.copy()
            print(copy == d, copy is d, OrderedDict.fromkeys('ab', 4))
            print(d | {'a': 9, 'd': 4}, {'z': 0} | d)
            alias = d
            d |= [('x', 7)]
            print(alias is d, d.popitem(False), d.popitem(), list(keys))
            it = iter(d)
            print(next(it))
            d.move_to_end('a')
            try:
                print(next(it))
            except RuntimeError:
                print('mutated')
            d = OrderedDict()
            d['self'] = d
            print(d)
            for operation in [lambda: OrderedDict().popitem(), lambda: d.move_to_end('bad'),
                              lambda: d | [('a', 1)]]:
                try:
                    operation()
                except Exception as error:
                    print(type(error).__name__)
        ''')

    def test_namedtuple_payload_defaults_and_validation(self):
        self.run_source('''
            from collections import namedtuple
            Point = namedtuple('Point', 'x y', defaults=[5], module='geometry')
            p = Point(2)
            print(p, p.x, p.y, tuple(p), list(p), len(p), p[-1], p[:1])
            print(isinstance(p, tuple), type(p).__name__, Point.__name__, Point.__qualname__, Point.__module__)
            print(Point._fields, Point._field_defaults, Point.__match_args__, Point.__slots__)
            print(Point.__new__.__name__, Point.__new__.__qualname__, Point.__new__.__defaults__)
            print(Point.__doc__, Point.__new__.__doc__)
            print(p._asdict(), p._replace(y=9), Point._make([7, 8]), p.__getnewargs__())
            print(p == (2, 5), (2, 5) == p, p < (3, 0), p + (9,), (9,) + p,
                  p*2, 2*p, p.count(5), p.index(5), hash(p) == hash((2, 5)))
            print(hasattr(p, '__dict__'), hasattr(p, '_values'))
            print(p.__replace__(x=4))
            Point.__new__.__defaults__ = (11, 12)
            print(Point(), Point(x=4), Point._field_defaults)
            p = Point(1, 2)
            for operation in [lambda: setattr(p, 'x', 9), lambda: setattr(p, 'extra', 9),
                              lambda: p.__setitem__(0, 9), lambda: Point._make([1]),
                              lambda: p._replace(z=9), lambda: Point(), lambda: Point(1, 2, 3)]:
                try:
                    print(operation())
                except Exception as error:
                    print(type(error).__name__)
            for typename, fields in [('bad name', 'x'), ('Point', 'x x'), ('Point', '_x'),
                                     ('Point', 'for'), ('Point', ['x', 1])]:
                try:
                    namedtuple(typename, fields)
                except Exception as error:
                    print(type(error).__name__)
            Renamed = namedtuple('Renamed', ['ok', 'ok', 'class', '_bad', 1], rename=True)
            print(Renamed._fields, Renamed(1,2,3,4,5))
            Empty = namedtuple('Empty', '')
            print(Empty(), tuple(Empty()), hash(Empty()) == hash(()))
        ''')

    def test_mapping_iterator_mutation(self):
        self.run_source('''
            from collections import defaultdict, Counter, OrderedDict
            for cls in [defaultdict, Counter, OrderedDict]:
                d = cls(None, a=1, b=2) if cls is defaultdict else cls(a=1, b=2)
                keys, values, items = d.keys(), d.values(), d.items()
                for view in [keys, values, items]:
                    it = iter(view)
                    print(next(it))
                    d['b'] += 1
                    print(next(it))
                it = iter(d)
                print(next(it))
                d['c'] = 3
                try:
                    print(next(it))
                except RuntimeError:
                    print('mutated')
                it = iter(d)
                print(list(it))
                d['d'] = 4
                print(list(it))
        ''')

    def test_ordered_dict_same_nan_boundary_does_not_invalidate_iteration(self):
        self.run_source('''
            from collections import OrderedDict
            key = float("nan")
            for last in [False, True]:
                pairs = [("other", 1), (key, 2)] if last else [(key, 2), ("other", 1)]
                mapping = OrderedDict(pairs)
                iterator = iter(mapping)
                mapping.move_to_end(key, last=last)
                print(len(list(iterator)), mapping[key], len(mapping))
        ''')
