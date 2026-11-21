"""copy.copy and copy.deepcopy for builtin lists, tuples and scalars."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeCopyModuleTests(unittest.TestCase):
    def test_grids(self):
        compare(self, 'import copy\nh, w = map(int, input().split())\ng = [[0] * w for _ in range(h)]\nnew = copy.deepcopy(g)\nnew[0][0] = 1\nshallow = copy.copy(g)\nshallow[1][1] = 7\nshallow.append([9])\n'
                'print(g, new, shallow, len(g))\nrows = [list(input()) for _ in range(h)]\nsnap = copy.deepcopy(rows)\nrows[0][0] = "#"\nprint(rows, snap)\n', '2 3\nabc\ndef\n')

    def test_shared_inner_lists_stay_shared(self):
        compare(self, 'from copy import deepcopy, copy\ninner = [1, 2]\nouter = [inner, inner, [3]]\nd = deepcopy(outer)\nd[0].append(5)\nprint(outer, d, d[0] is d[1], d[0] is inner)\n'
                'pairs = [(1, "a"), (2, "b")]\nq = deepcopy(pairs)\nprint(q == pairs, q is pairs)\nprint(deepcopy(5), copy("text"), deepcopy((1, (2, 3))))\n', '')

    def test_unsupported_values_are_positioned(self):
        result = transpile('import copy\nclass Box:\n    pass\nprint(copy.deepcopy(Box()))\n', TranspileOptions(filename='cp.py'))
        self.assertFalse(result.success)
        self.assertIn('cp.py:4:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
