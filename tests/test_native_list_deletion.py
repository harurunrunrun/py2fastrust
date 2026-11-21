"""del list[index] and del list[slice] compared with CPython."""
import unittest

from test_native_exception_handlers import compare


class NativeListDeletionTests(unittest.TestCase):
    def test_items_and_slices(self):
        compare(self, 'a = list(range(10))\ndel a[1]\ndel a[-1]\nprint(a)\ndel a[2:4]\nprint(a)\ndel a[::2]\nprint(a)\n'
                'b = list(range(12))\ndel b[::-3]\nprint(b)\ndel b[5:1]\ndel b[100:]\nprint(b)\ndel b[:]\nprint(b, len(b))\n'
                'n = int(input())\nc = [str(i) for i in range(n)]\nalias = c\ndel c[n // 2], c[0]\nprint(alias)\n'
                'rows = [[1], [2], [3]]\ndel rows[1][0]\ndel rows[0]\nprint(rows)\n', '6\n')

    def test_errors(self):
        compare(self, 'a = [1, 2, 3]\nfor i in [3, -4, 5]:\n    try:\n        del a[i]\n    except IndexError as error:\n        print(error)\n'
                'try:\n    del a[::0]\nexcept ValueError as error:\n    print(error)\nprint(a)\ndel a[0]\ndel a[0]\ndel a[0]\ndel a[0]\n', '')


if __name__ == '__main__':
    unittest.main()
