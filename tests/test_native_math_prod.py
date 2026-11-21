"""math.prod over integers multiplies sequentially from start."""
import unittest

from test_native_exception_handlers import compare


class NativeMathProdTests(unittest.TestCase):
    def test_integer_products(self):
        compare(self, 'import math\na = list(map(int, input().split()))\nprint(math.prod(a), math.prod(range(1, 6), start=2), math.prod([]), math.prod([True, 3]))\n'
                'from math import prod\nprint(prod(x % 7 + 1 for x in a), prod([], start=-4))\n', '3 5 7 2\n')


if __name__ == '__main__':
    unittest.main()
