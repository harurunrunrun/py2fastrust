"""Unit-step str slices read in place keep CPython's slice clamping and str results."""
import unittest

from test_native_exception_handlers import compare


class NativeTextSliceViewTests(unittest.TestCase):
    def test_window_comparisons(self):
        compare(self, 's = input()\nt = input()\nk = len(t)\nc = 0\nfor i in range(len(s) - k + 1):\n    if s[i:i + k] == t:\n        c += 1\n'
                'print(c, s[:3] == "abc", s[-2:] != "zz", s[5:2] == "", s[-100:2], s[2:100] < t, s[:k] >= t[:k])\n', 'abcabcxabc\nabc\n')

    def test_slices_in_other_readers(self):
        compare(self, 's = input()\nd = {"ab": 1, "cd": 2}\nprint(d.get(s[0:2], 0), d.get(s[2:4]), s[1:3] in d, "b" in s[:2], len(s[1:-1]), s[1:4].count("c"))\n'
                'print(s[1:4].upper(), s[::1], s[:], s[3:][:2], f"{s[1:3]}|{s[-3:]}", s[1:3] + s[0:1], s[0:2] * 2)\n'
                'parts = [s[i:i + 2] for i in range(0, len(s), 2)]\nprint(parts, sorted(set(parts)), max(s[i:i + 3] for i in range(len(s) - 2)))\n'
                'print(s[1:3].isalpha(), s[0:3].startswith("ab"), int(s[4:6] or "0", 16) if s[4:6].isalnum() else -1)\n', 'abcdef01\n')

    def test_bounds_are_clamped_and_evaluated_in_order(self):
        compare(self, 'def f(x):\n    print("f", x)\n    return x\ns = input()\nprint(s[f(1):f(-1)] == s[1:-1], s[f(10):f(20)] == "", s[f(-30):f(2)])\n'
                'n = len(s)\nfor a in range(-n - 1, n + 2, 3):\n    for b in range(-n - 1, n + 2, 4):\n        print(a, b, s[a:b], s[a:b] == s[a:][:max(0, b - a)] if a >= 0 and b >= 0 else "")\n', 'hello world\n')

    def test_index_type_errors_keep_position(self):
        compare(self, 's = input()\nx = None if len(s) > 100 else "q"\nprint(s[0:2] == "ab")\nprint(s[x:2] == "ab")\n', 'abc\n')


if __name__ == '__main__':
    unittest.main()
