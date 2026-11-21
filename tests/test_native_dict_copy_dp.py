"""Dictionary DP that copies the previous table with dict() each round."""
import unittest

from test_native_exception_handlers import compare


class NativeDictCopyDpTests(unittest.TestCase):
    def test_subset_sum_counts(self):
        compare(self, 'dp = {0: 1}\nfor x in map(int, input().split()):\n    nd = dict(dp)\n    for s, c in dp.items():\n        nd[s + x] = nd.get(s + x, 0) + c\n    dp = nd\n'
                'print(sorted(dp.items()))\nprint(list(dp), len(dp))\n', '1 2 3 3\n')

    def test_constructor_forms(self):
        compare(self, 'a = {1: "x", 2: "y"}\nb = dict(a)\nb[3] = "z"\ndel b[1]\nb[1] = "w"\nprint(a, b, b is a, list(b.items()))\nprint(dict(p=1, q=2), dict([(2, 3), (1, 4)]), dict())\n', '')


if __name__ == '__main__':
    unittest.main()
