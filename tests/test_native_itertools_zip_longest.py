"""itertools.zip_longest pull order, fill values and exhaustion."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeZipLongestTests(unittest.TestCase):
    def test_fill_and_types(self):
        compare(self, 'from itertools import zip_longest\nprint(list(zip_longest([1, 2, 3], [4], fillvalue=0)))\n'
                'for a, b in zip_longest("abc", "de"):\n    print(a, b)\n'
                'print(list(zip_longest()), list(zip_longest([], [])), list(zip_longest([7])))\n'
                'n = int(input())\nrows = [list(range(i)) for i in range(n)]\nprint(list(zip_longest(rows[1], rows[n - 1], fillvalue=-1)))\n'
                'print([x + y for x, y in zip_longest([1, 2], [10, 20, 30], fillvalue=100)])\n', '4\n')

    def test_exhausted_iterators_are_not_pulled_again(self):
        compare(self, 'from itertools import zip_longest\ndef gen(name, count):\n    for i in range(count):\n        print("pull", name, i)\n        yield i\n    print("done", name)\n'
                'it = zip_longest(gen("a", 1), gen("b", 3), fillvalue="-")\nfor pair in it:\n    print(pair)\nprint(next(it, "end"))\n', '')

    def test_starred_arguments_are_positioned(self):
        result = transpile('from itertools import zip_longest\nrows = [[1], [2, 3]]\nprint(list(zip_longest(*rows)))\n', TranspileOptions(filename='zl.py'))
        self.assertFalse(result.success)
        self.assertIn('zl.py:3:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
