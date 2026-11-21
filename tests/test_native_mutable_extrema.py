"""min/max whose winner is a mutable object return that same object, and None comparisons stay warning-free."""
import unittest

from test_native_exception_handlers import compare


class NativeMutableExtremaTests(unittest.TestCase):
    def test_rows_are_returned_by_identity(self):
        compare(self, 'a = [list(map(int, input().split())) for _ in range(3)]\nb = max(a)\nb.append(99)\nprint(a, min(a), b is a[0] or b is a[1] or b is a[2])\n'
                'print(max([1, 2], [1, 3]), min([[2], [1, 5], [1, 4]]), min(a, default=None))\ntry:\n    print(max([]))\nexcept ValueError as error:\n    print(error)\n', '3 1\n3 2\n1 9\n')

    def test_none_identity_chains(self):
        compare(self, 'class A:\n    pass\nx = [1]\ny = None\nprint(x is not None, x is None, 1 < 2 < 3, y is None, None is y, max([[1], [2]]) is not None)\n', '')


if __name__ == '__main__':
    unittest.main()
