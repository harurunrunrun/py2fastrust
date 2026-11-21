"""zip(*rows) with a runtime number of argument iterators."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'transpose_and_columns': ('m = [[1, 2, 3], [4, 5, 6]]\nprint(list(zip(*m)))\ngrid = ["abc", "def"]\ncols = ["".join(c) for c in zip(*grid)]\nprint(cols)\nfor a, b in zip(*[[1, 2], [3, 4]]):\n    print(a + b)\nprint(list(zip(*[])))\nt = [list(r) for r in zip(*[[1, 2], [3]])]\nprint(t)\n', ''),
    'noniterable_argument': ('rows = [[1, 2], 5]\nprint(list(zip(*rows)))\n', ''),
}


class NativeZipExpandedTests(unittest.TestCase):
    def test_transpose_and_columns(self):
        compare(self, *CASES['transpose_and_columns'])

    def test_noniterable_argument(self):
        compare(self, *CASES['noniterable_argument'])
