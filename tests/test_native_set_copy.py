"""set.copy() follows set_copy/set_merge in Objects/setobject.c, so the copy keeps CPython's table order."""
import unittest

from test_native_exception_handlers import compare


class NativeSetCopyTests(unittest.TestCase):
    def test_copy_is_independent(self):
        compare(self, 's = {3, 1, 2}\nt = s.copy()\nt.add(30)\ns.discard(1)\nprint(s, t, len(t), s is t, s == t)\n'
                'for x in t.copy():\n    if x % 2:\n        t.discard(x)\nprint(t, set().copy())\n', '')

    def test_copy_after_discards_and_growth_keeps_table_order(self):
        compare(self, 'n = int(input())\ns = set(range(0, n, 7))\nfor x in range(0, n, 21):\n    s.discard(x)\ns.add(1000)\ns.add(-5)\n'
                'c = s.copy()\nprint(list(c))\nfor i in range(40):\n    c.add(i * 33)\nprint(list(c))\nprint(list(s))\n'
                'print(list({i * 37 % 101 for i in range(50)}.copy()))\n', '200\n')

    def test_text_copy_with_operators(self):
        compare(self, 'u = set(input().split())\nv = u.copy()\nv |= {"zz"}\nw = v.copy() - u\nprint(sorted(u), sorted(v), sorted(w), len(v.copy()))\n', 'b a c a\n')


if __name__ == '__main__':
    unittest.main()
