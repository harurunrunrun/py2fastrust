"""itertools.groupby runs, shared groupers and grouper invalidation."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


CASES = {
    'runs_and_invalidated_groupers': ('from itertools import groupby\ns = "aaabccdd"\nprint([(k, len(list(g))) for k, g in groupby(s)])\nnums = [1, 1, 2, 2, 2, 1]\nfor k, g in groupby(nums):\n    print(k, list(g))\ngroups = [g for k, g in groupby([5, 5, 6])]\nprint([list(g) for g in groups])\nit = groupby([3, 3, 4])\nk1, g1 = next(it)\nk2, g2 = next(it)\nprint(k1, list(g1), k2, list(g2))\nprint(list(groupby([])))\n', ''),
}


class NativeGroupbyTests(unittest.TestCase):
    def test_runs_and_invalidated_groupers(self):
        compare(self, *CASES['runs_and_invalidated_groupers'])

    def test_key_function_is_positioned(self):
        result = transpile('from itertools import groupby\nprint([k for k, g in groupby([1, 2], key=lambda v: v % 2)])\n',
                           TranspileOptions(filename='groupby.py'))
        self.assertFalse(result.success)
        text = '\n'.join(map(str, result.diagnostics))
        self.assertIn('key function', text)
        self.assertIn('groupby.py:2:', text)
