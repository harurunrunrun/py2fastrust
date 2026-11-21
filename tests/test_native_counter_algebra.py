"""Counter + - | & build new Counters with CPython's item order and positive-count filtering."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'operators': ('from collections import Counter\nc1 = Counter("aaabbc")\nc2 = Counter("abbbd")\nprint(c1 + c2)\nprint(c1 - c2)\nprint(c1 | c2)\nprint(c1 & c2)\n'
                  'print(list((c2 - c1).items()), list((c1 + c2).keys()))\n'
                  'a = Counter({"x": 2, "y": -1, "z": 0})\nb = Counter({"y": -3, "w": -2, "x": 2})\n'
                  'for result in (a + b, a - b, b - a, a | b, a & b, a + Counter()):\n    print(result, len(result))\n'
                  'empty = Counter() - Counter([1, 1])\nprint(empty, Counter([1, 1]) & Counter([1]))\n', ''),
    'counts_from_input': ('from collections import Counter\nn = int(input())\nleft = Counter(input().split())\nright = Counter(input().split())\nboth = left & right\nprint(sum(both.values()), sorted((left - right).items()))\nprint((left | right).most_common(2))\n',
                          '3\nx y x z\ny y x\n'),
}


class NativeCounterAlgebraTests(unittest.TestCase):
    def test_operators(self):
        compare(self, *CASES['operators'])

    def test_counts_from_input(self):
        compare(self, *CASES['counts_from_input'])


if __name__ == '__main__':
    unittest.main()
