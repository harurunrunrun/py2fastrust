"""Sorting tuple rows whose comparator is a single block compiles without warnings."""
import unittest

from test_native_exception_handlers import compare


class NativeSortedComparatorBlockTests(unittest.TestCase):
    def test_sorted_dictionary_items(self):
        compare(self, 'd = {"b": 1}\nd["a"] = 2\nd["c"] = 0\nprint(sorted(d.items()), sorted(d.items(), reverse=True))\n'
                'rows = [(2, "x"), (1, "y"), (2, "a")]\nrows.sort()\nprint(rows)\n', '')


if __name__ == '__main__':
    unittest.main()
