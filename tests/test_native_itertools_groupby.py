"""itertools.groupby runs, shared groupers and grouper invalidation."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'runs_and_invalidated_groupers': ('from itertools import groupby\ns = "aaabccdd"\nprint([(k, len(list(g))) for k, g in groupby(s)])\nnums = [1, 1, 2, 2, 2, 1]\nfor k, g in groupby(nums):\n    print(k, list(g))\ngroups = [g for k, g in groupby([5, 5, 6])]\nprint([list(g) for g in groups])\nit = groupby([3, 3, 4])\nk1, g1 = next(it)\nk2, g2 = next(it)\nprint(k1, list(g1), k2, list(g2))\nprint(list(groupby([])))\n', ''),
    'key_functions': ('from itertools import groupby\nprint([(k, list(g)) for k, g in groupby([1, 3, 2, 4, 5, 7], key=lambda v: v % 2)])\n'
                      'words = ["apple", "avocado", "banana", "blueberry", "cherry"]\nfor first, group in groupby(words, lambda w: w[0]):\n    print(first, list(group))\n'
                      'def size(text):\n    return len(text)\nprint([(k, len(list(g))) for k, g in groupby(["ab", "cd", "e", "fg"], key=size)])\n'
                      'calls = []\ndef tracked(v):\n    calls.append(v)\n    return v // 10\nit = groupby([1, 2, 11, 12, 21], tracked)\nk, g = next(it)\nprint(k, calls)\nk, g = next(it)\nprint(k, list(g), calls)\n'
                      'print(list(groupby([], key=lambda v: v)), [k for k, _ in groupby("aAbB", key=None)])\n', ''),
    'key_function_error': ('from itertools import groupby\nfor k, g in groupby([2, 1, 0, 3], key=lambda v: 6 // v):\n    print(k, list(g))\n', ''),
}


class NativeGroupbyTests(unittest.TestCase):
    def test_runs_and_invalidated_groupers(self):
        compare(self, *CASES['runs_and_invalidated_groupers'])

    def test_key_functions(self):
        compare(self, *CASES['key_functions'])

    def test_key_function_error(self):
        compare(self, *CASES['key_function_error'])
