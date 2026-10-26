"""Range coordinates and cardinalities remain exact in every integer mode."""

import random
import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class RangeTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_fixed_width_iteration_and_structural_boundaries(self):
        for integer, bits in [('i64', 64), ('i128', 128), ('bigint', 200)]:
            lower, upper = -(2**(bits-1)), 2**(bits-1)-1
            source = f'''
                lo, hi = {lower}, {upper}
                for r in [range(hi-1, hi, 2), range(lo+1, lo, -2),
                          range(hi-4, hi, 2), range(lo+4, lo, -2),
                          range(hi, lo, lo), range(lo, hi, hi)]:
                    print(list(r), len(r), bool(r), list(reversed(r)))
                for r in [range(lo, hi), range(hi, lo, -1), range(lo, hi, hi)]:
                    print(bool(r), r[0], r[-1], r[1], r[-2])
                    print(r.start, r.stop, r.step, r.count(lo), r.count(hi), lo in r, hi in r)
                    try:
                        print(len(r))
                    except OverflowError:
                        print('length overflow')
                r = range(lo, lo+2)[::-1]
                print(r.start, r.stop, r.step, list(r))
                r = range(hi, lo, lo)[::-1]
                print(r.start, r.stop, r.step, list(r))
            '''
            with self.subTest(integer=integer):
                self.run_source(source, integer=integer)

    def test_sequence_protocol_and_errors(self):
        self.run_source('''
            for r in [range(0), range(5), range(8, -9, -3), range(3, 3, -1)]:
                print(r, repr(r), len(r), bool(r), list(r), list(reversed(r)))
                print(r.start, r.stop, r.step)
                for value in [0, 1, -1, True, False, 1.0, 1.5, float('inf'), float('nan'), '1']:
                    print(value in r, r.count(value))
                    try:
                        print(r.index(value))
                    except ValueError:
                        print('missing')
                for index in [0, 1, -1, -2, 100, -100]:
                    try:
                        print(r[index])
                    except IndexError:
                        print('index error')
            class Index:
                def __index__(self): return -1
            print(range(4)[Index()])
            class Equal:
                def __eq__(self, other): return True
            print(Equal() in range(3), range(3).count(Equal()), range(3).index(Equal()))
            a, b = range(0, 6, 2), range(0, 5, 2)
            print(a == b, a != b, hash(a) == hash(b), range(0) == range(2, 2),
                  range(4, 5) == range(4, 6, 2), a == [0,2,4], a == (0,2,4))
            for operation in [lambda: range(), lambda: range(1,2,3,4), lambda: range(1.5),
                              lambda: range('3'), lambda: range(1, step=2), lambda: range(1,2,0),
                              lambda: range(3)[1.5], lambda: range(3)[::0],
                              lambda: setattr(range(3), 'start', 9), lambda: range(3).index(1,2)]:
                try:
                    operation()
                except Exception as error:
                    print(type(error).__name__)
        ''')

    def test_random_small_ranges_and_slices(self):
        rng = random.Random(81734)
        cases = [(rng.randrange(-50, 51), rng.randrange(-50, 51), rng.choice([n for n in range(-12, 13) if n]),
                  rng.choice([None, rng.randrange(-100, 101)]), rng.choice([None, rng.randrange(-100, 101)]),
                  rng.choice([None, -13, -3, -1, 1, 2, 11])) for _ in range(150)]
        source = f'''
            cases = {cases!r}
            for start, stop, step, lower, upper, stride in cases:
                r = range(start, stop, step)
                sliced = r[slice(lower, upper, stride)]
                print(len(r), bool(r), list(r), sliced, list(sliced),
                      sliced.start, sliced.stop, sliced.step)
                print([value in r for value in [-51, -3, 0, 2, 49, 80]])
        '''
        self.run_source(source)

    def test_arbitrary_precision_cardinality_and_index(self):
        self.run_source('''
            n = 10**100
            r = range(-n, n, 3)
            print(bool(r), r[0], r[-1], r[n//3], r.count(2), r.index(2))
            print(-n in r, n in r, 2 in r, 3 in r)
            s = r[1:-1:10**50]
            print(s.start, s.stop, s.step, s[0], s[-1])
            it = reversed(r)
            print(next(it), next(it), next(it))
            try:
                print(len(r))
            except OverflowError:
                print('length overflow')
        ''', integer='bigint')


if __name__ == '__main__':
    unittest.main()
