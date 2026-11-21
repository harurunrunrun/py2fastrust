"""Builtin set operators |, &, -, ^ and their in-place forms in CPython table order."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'named_methods': ('xs = {4, 7, 12, 33}\nys = {7, 9, 33, 100, 5}\nprint(xs.union(ys), xs.intersection(ys), xs.difference(ys), xs.symmetric_difference(ys))\nprint(xs.issubset(ys), {7}.issubset(ys), ys.issuperset({9, 5}), xs.isdisjoint({1, 2}), xs.isdisjoint(ys), set().isdisjoint(set()))\nzs = set(range(20))\nalias = zs\nzs.intersection_update({3, 5, 7, 99})\nprint(zs, alias is zs)\nzs.difference_update({5})\nzs.symmetric_difference_update({7, 8})\nprint(zs)\n', ""),
    'set_comparisons': ('a = {1, 2, 3}\nb = set([3, 2, 1])\nc = {1, 2}\nprint(a == b, a != b, c < a, c <= a, a < a, a <= a, a > c, a >= b, c > a, a == c)\nprint({"x"} == {"x"}, {"x"} <= {"x", "y"})\nseen = set()\nfor v in [4, 4, 5]:\n    seen |= {v}\nprint(seen == {4, 5}, seen != {4})\n', ""),
    'operators_follow_cpython_table_order': ('xs = {4, 7, 12, 33}\nys = {7, 9, 33, 100, 5}\nprint(xs | ys, xs & ys, xs - ys, xs ^ ys)\nprint(ys | xs, ys & xs, ys - xs, ys ^ xs)\nbig = set(range(0, 60, 3))\nsmall = {6, 7, 9}\nprint(big - small, small - big, big & small, small ^ big)\nprint(xs | xs, xs & xs, xs - xs, xs ^ xs)\nwords = {"ab", "cd"}\nprint(sorted(words | {"x"}), len(words & {"cd", "q"}))\nhuge = set(range(100))\ntiny = {3, 500}\nprint(tiny - huge, len(huge - tiny))\nfor v in big - small:\n    print(v, end=" ")\nprint()\n', ""),
    'inplace_operators_keep_identity': ('seen = {3, 8}\nalias = seen\nseen |= {5, 8, 40}\nprint(seen, alias is seen)\nseen &= {40, 3, 99}\nprint(seen, alias)\nseen ^= {3, 77}\nprint(seen)\nseen -= {77}\nprint(seen, alias is seen)\ngrow = set(range(30))\ngrow -= set(range(0, 30, 2))\nprint(grow)\ngrow -= set(range(1000))\nprint(grow)\nsame = {1, 2}\nsame ^= same\nprint(same)\nloop = set()\nfor i in range(10):\n    loop |= {i * 7 % 10}\nprint(loop)\n', ""),
    'random_operator_sequences': ('state = 12345\ndef nxt(m):\n    global state\n    state = (state * 1103515245 + 12345) % 2147483648\n    return state % m\npool = []\nfor k in range(6):\n    s = set()\n    for _ in range(nxt(120)):\n        s.add(nxt(400) - 50)\n    pool.append(s)\nfor step in range(300):\n    i = nxt(6)\n    j = nxt(6)\n    op = nxt(8)\n    a = pool[i]\n    b = pool[j]\n    if op == 0:\n        c = a | b\n    elif op == 1:\n        c = a & b\n    elif op == 2:\n        c = a - b\n    elif op == 3:\n        c = a ^ b\n    elif op == 4:\n        a |= b\n        c = a\n    elif op == 5:\n        a &= b\n        c = a\n    elif op == 6:\n        a -= b\n        c = a\n    else:\n        a ^= b\n        c = a\n    if len(c) < 3:\n        for _ in range(nxt(200)):\n            c.add(nxt(1000))\n    pool[nxt(6)] = c\n    print(step, op, len(c), list(c)[:12])\n', ""),
}


class NativeSetAlgebraTests(unittest.TestCase):
    def test_operators_follow_cpython_table_order(self):
        compare(self, *CASES['operators_follow_cpython_table_order'])

    def test_inplace_operators_keep_identity(self):
        compare(self, *CASES['inplace_operators_keep_identity'])

    def test_random_operator_sequences(self):
        compare(self, *CASES['random_operator_sequences'])

    def test_set_comparisons(self):
        compare(self, *CASES['set_comparisons'])

    def test_named_methods(self):
        compare(self, *CASES['named_methods'])
