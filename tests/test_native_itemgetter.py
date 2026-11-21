"""operator.itemgetter with integer literal items, following itemgetter_call in Modules/_operator.c."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeItemGetterTests(unittest.TestCase):
    def test_sort_and_extrema_keys(self):
        compare(self, 'from operator import itemgetter\nn = int(input())\na = [tuple(map(int, input().split())) for _ in range(n)]\n'
                'a.sort(key=itemgetter(1))\nprint(a)\nprint(max(a, key=itemgetter(0, 1)), min(a, key=itemgetter(-1)))\n'
                'print(sorted(a, key=itemgetter(1, 0), reverse=True))\nprint(list(map(itemgetter(0), a)))\n', '4\n1 5\n2 3\n9 3\n-4 5\n')

    def test_fixed_tuples_lists_and_display(self):
        compare(self, 'import operator\nrows = [(3, "c", 1.5), (1, "a", 2.5), (2, "b", 0.5)]\nby_name = operator.itemgetter(1)\n'
                'print(sorted(rows, key=by_name), sorted(rows, key=operator.itemgetter(2)))\nprint(by_name, operator.itemgetter(0, -1))\n'
                'pick = operator.itemgetter(2, 0)\nprint(pick([5, 6, 7]), pick(rows[0]), operator.itemgetter(-2)([1, 2, 3]))\n'
                'grid = [[3, 1], [1, 2], [2, 0]]\ngrid.sort(key=operator.itemgetter(1))\nprint(grid)\n', '')

    def test_index_and_binding_errors(self):
        compare(self, 'from operator import itemgetter\nget = itemgetter(3)\nfor value in [[1, 2], (1, 2)]:\n    try:\n        print(get(value))\n'
                '    except IndexError as error:\n        print("IndexError", error)\ntry:\n    get([1], [2])\nexcept TypeError as error:\n    print(error)\n'
                'try:\n    itemgetter()\nexcept TypeError as error:\n    print(error)\nprint(sorted([[1, 2], [3]], key=itemgetter(1)))\n', '')

    def test_unsupported_items_and_receivers_are_positioned(self):
        for source, line in [('from operator import itemgetter\nk = int(input())\nprint(itemgetter(k)([1, 2]))\n', 3),
                             ('from operator import itemgetter\nd = {1: 2}\nprint(itemgetter(1)(d))\n', 3)]:
            result = transpile(source, TranspileOptions(filename='ig.py'))
            self.assertFalse(result.success)
            self.assertIn(f'ig.py:{line}:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
