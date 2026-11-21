"""a[i] = a[j] = value assigns the single value to each target from left to right."""
import unittest

from test_native_exception_handlers import compare


class NativeChainedAssignmentTests(unittest.TestCase):
    def test_sieve_and_order(self):
        compare(self, 'from math import isqrt\nn = int(input())\np = [True] * (n + 1)\np[0] = p[1] = False\nfor i in range(2, isqrt(n) + 1):\n    if p[i]:\n        for j in range(i * i, n + 1, i):\n            p[j] = False\nprint(sum(p))\n'
                'q = [0] * 3\nx = q[0] = q[2] = 5\nd = {}\nd["a"] = d["b"] = []\nd["a"].append(1)\nprint(x, q, d, d["a"] is d["b"])\n'
                'def idx(k):\n    print("index", k)\n    return k\nr = [0] * 3\nr[idx(0)] = r[idx(1)] = idx(7)\nprint(r)\n', '100\n')


if __name__ == '__main__':
    unittest.main()
