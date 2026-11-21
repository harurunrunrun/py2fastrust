"""sum() over floats with CPython's compensated summation (issue #1)."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'compensated_float_sum': ('print(sum([1.0, 1e-17, -1.0]))\nprint(sum([0.1] * 10), sum([]), sum([1, 2.5, 3]), sum([2.5, 1, True]))\nprint(sum([1e308, 1e308, -1e308]), sum([-0.0]), sum([float("inf"), 1.0]))\nprint(sum([0.1, 0.2, 0.3], 1.0), sum([1, 2], 0.5))\nvals = [x / 3 for x in range(10)]\nprint(sum(vals), sum(v for v in vals if v > 1))\nprint(sum([10**17, 0.5, 3]))\nprint(sum(float(x) for x in range(3)))\n', ''),
}


class NativeFloatSumTests(unittest.TestCase):
    def test_compensated_float_sum(self):
        compare(self, *CASES['compensated_float_sum'])
