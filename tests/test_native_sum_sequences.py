"""sum() with a list start concatenates through list addition, as PyNumber_Add does."""
import unittest

from test_native_exception_handlers import compare


class NativeSumSequenceTests(unittest.TestCase):
    def test_list_start(self):
        compare(self, 'a = [[1, 2], [3], [], [4, 5]]\nflat = sum(a, [])\nprint(flat, len(flat))\nstart = [0]\nprint(sum([[7]], start), start)\n'
                'empty = []\nsame = sum([], empty)\nsame.append(9)\nprint(empty, same is empty)\n'
                'rows = [list(map(int, line.split())) for line in ["1 2", "3 4 5"]]\nprint(sum(rows, [-1]))\nprint(sum(([i, i * i] for i in range(3)), []))\n', '')

    def test_list_start_type_error(self):
        compare(self, 'print(sum([[1], (2,)], []))\n', '')
        compare(self, 'print(sum([[1], [2]], []))\nprint(sum([1, 2], []))\n', '')


if __name__ == '__main__':
    unittest.main()
