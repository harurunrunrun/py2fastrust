"""str padding, affix removal and ASCII case transforms compared with CPython."""
import unittest

from test_native_exception_handlers import compare


class NativeTextTransformTests(unittest.TestCase):
    def test_padding(self):
        compare(self, 'for s in ["", "a", "ab", "abc", "-42", "+7", "x-1", "hello"]:\n'
                '    print(repr(s.ljust(4)), repr(s.rjust(5, "*")), repr(s.center(6, "-")), repr(s.center(5)), repr(s.zfill(4)), repr(s.zfill(0)), repr(s.ljust(-3)))\n'
                'n = int(input())\nprint(str(n).zfill(8), str(-n).zfill(8), "|" + "abc".center(n) + "|", "ab".center(n, "="))\n'
                'for width in range(7):\n    print(repr("abc".center(width, ".")), repr("ab".center(width, ".")))\n', '9\n')

    def test_case_and_affixes(self):
        compare(self, 'for s in ["", "hello world", "HELLO", "hELLO wORLD", "they\'re bill\'s", "abc123def", "1st place", "a-b_c d"]:\n'
                '    print(s.swapcase(), s.capitalize(), s.title(), s.removeprefix("he"), s.removesuffix("ld"), s.removeprefix(""), s.removesuffix(s))\n'
                'line = input()\nprint(line.title(), line.capitalize(), line.swapcase())\n', 'the QUICK brown fox\n')

    def test_errors(self):
        compare(self, 'for fill in ["", "ab"]:\n    try:\n        print("a".ljust(3, fill))\n    except TypeError as error:\n        print(error)\n'
                '', '')


if __name__ == '__main__':
    unittest.main()
