"""Bundled sortedcontainers SortedList/SortedSet/SortedDict, checked against sortedcontainers 2.4.0 output.

The expected outputs were produced by the upstream package; the converted
programs must reproduce them in every integer mode and build.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile

CASES = {
    'sorted_list_operations_and_errors': ('from sortedcontainers import SortedList\ns = SortedList([7, 3, 1, 5, 3])\nprint(s, len(s), s[0], s[-1], s.bisect_left(3), s.bisect_right(3), s.count(3), 3 in s, 4 in s)\ns.add(4); s.discard(3); s.remove(7)\nprint(s, s.pop(), s.pop(0), s, s.index(4))\nprint(list(s.irange(2, 10)), list(reversed(s)), list(s.islice(0, 1)))\nfor v in [10, -2, 8]:\n    s.update([v, v + 1])\nprint(s)\ntry:\n    s.remove(100)\nexcept ValueError as e:\n    print("ValueError", e)\ntry:\n    print(s[100])\nexcept IndexError as e:\n    print("IndexError", e)\nt = SortedList()\nx = 1\nfor k in range(200000):\n    x = (x * 1103515245 + 12345) & 0x7fffffff\n    t.add(x % 1000)\nprint(len(t), t[0], t[100000], t.bisect_left(500), t.count(7))\ndel t[0]\nprint(t[0], len(t))\n',
        '',
        'SortedList([1, 3, 3, 5, 7]) 5 1 7 1 3 2 True False\nSortedList([3, 4]) 5 1 SortedList([3, 4]) 1\n[3, 4] [4, 3] [3]\nSortedList([-2, -1, 3, 4, 8, 9, 10, 11])\nValueError 100 not in list\nIndexError list index out of range\n200000 0 502 99605 223\n0 199999\n'),
    'sorted_set_algebra_and_comparisons': ('from sortedcontainers import SortedSet, SortedList\ns = SortedSet([7, 3, 1, 5])\ni = s.bisect_left(4)\nprint(s[i])\ns.add(6)\ns.discard(5)\nprint(s[s.bisect_left(4)], s, len(s), 3 in s, s.pop(), s.pop(0), s)\nt = s | [10, 1, 11]\nprint(t, t & {1, 6}, t - {1}, t ^ {1, 99}, s == SortedSet([3, 6]), s == {3, 6}, s == [3, 6])\ntry:\n    s.remove(42)\nexcept KeyError as e:\n    print("KeyError", e)\ndel t[0]\nprint(t, list(reversed(t)), t.index(10), SortedSet())\na = SortedList([3, 1, 2])\nprint(a == [1, 2, 3], a == SortedList([1, 2, 3]), a < [1, 3], a != (1, 2, 3))\n',
        '',
        '5\n6 SortedSet([3, 6]) 4 True 7 1 SortedSet([3, 6])\nSortedSet([1, 3, 6, 10, 11]) SortedSet([1, 6]) SortedSet([3, 6, 10, 11]) SortedSet([3, 6, 10, 11, 99]) True True False\nKeyError 42\nSortedSet([3, 6, 10, 11]) [11, 10, 6, 3] 2 SortedSet([])\nTrue True True False\n'),
    'sorted_dict_views_and_items': ('from sortedcontainers import SortedDict\n\nd = SortedDict({7:49, 3:9, 1:1, 5:25})\ni = d.bisect_left(4)  # d のキーをソートしたリストに対して bisect_left を行ったときと同じ値である 2 が返される\nprint(d.peekitem(i))  # d のキーと値の組をソートしたリストに対して添字アクセスしたときと同じ値である (5, 25) が返される\nd[6] = 36\nd.pop(5)\nprint(d.peekitem(d.bisect_left(4)))  # (6, 36)\nprint(d, len(d), 3 in d, d.get(9), d.get(9, 0), d.setdefault(2, 4), d.pop(2), d.pop(99, -1))\nprint(list(d), list(d.keys()), list(d.values()), list(d.items()), d.keys()[0], d.items()[-1], d.values()[1])\nd[0] = 0\nprint(d.popitem(), d.popitem(0), d, d.bisect_right(3), d.index(6))\ntry:\n    d.pop(1234)\nexcept KeyError as e:\n    print("KeyError", e)\n',
        '',
        '(5, 25)\n(6, 36)\nSortedDict({1: 1, 3: 9, 6: 36, 7: 49}) 4 True None 0 4 4 -1\n[1, 3, 6, 7] [1, 3, 6, 7] [1, 9, 36, 49] [(1, 1), (3, 9), (6, 36), (7, 49)] 1 (7, 49) 9\n(7, 49) (0, 0) SortedDict({1: 1, 3: 9, 6: 36}) 2 2\nKeyError 1234\n'),
    'sorted_dict_word_counts': ('from sortedcontainers import SortedDict\nw = SortedDict()\nfor word in "the quick brown fox jumps over the lazy dog the end".split():\n    w[word] = w.get(word, 0) + 1\nprint(w, w.keys())\n',
        '',
        "SortedDict({'brown': 1, 'dog': 1, 'end': 1, 'fox': 1, 'jumps': 1, 'lazy': 1, 'over': 1, 'quick': 1, 'the': 3}) SortedKeysView(SortedDict({'brown': 1, 'dog': 1, 'end': 1, 'fox': 1, 'jumps': 1, 'lazy': 1, 'over': 1, 'quick': 1, 'the': 3}))\n"),
    'builtins_and_query_loop': ('from sortedcontainers import SortedList\ns = SortedList([5, 2, 9, 2])\nprint(sorted(s, reverse=True), sum(s), max(s), min(s), list(s), tuple(s), len(s) > 0, bool(SortedList()))\nprint(*list(s))\nprint([x * 2 for x in s], {x for x in s}, any(x > 8 for x in s), sorted(set(s)))\nfor i, v in enumerate(s):\n    print(i, v, end=" ")\nprint()\nn, q = map(int, input().split())\nsl = SortedList(map(int, input().split()))\nfor _ in range(q):\n    t, x = map(int, input().split())\n    if t == 1:\n        sl.add(x)\n    elif t == 2:\n        sl.discard(x)\n    else:\n        i = sl.bisect_left(x)\n        print(sl[i] if i < len(sl) else -1)\n',
        '3 5\n4 1 7\n3 5\n1 5\n3 5\n2 7\n3 6\n',
        '[9, 5, 2, 2] 18 9 2 [2, 2, 5, 9] (2, 2, 5, 9) True False\n2 2 5 9\n[4, 4, 10, 18] {9, 2, 5} True [2, 5, 9]\n0 2 1 2 2 5 3 9 \n7\n5\n-1\n'),
}


def run(test, source, stdin):
    with tempfile.TemporaryDirectory(prefix='pytors-sorted-') as directory:
        outputs = []
        for integer in ('i64', 'i128', 'bigint'):
            result = transpile(source, TranspileOptions(integer=integer, filename='program.py', license='none'))
            test.assertTrue(result.success, result.diagnostics)
            test.assertLess(len(result.rust_source.encode()), 512 * 1024)
            rust = Path(directory) / (integer + '.rs')
            rust.write_text(result.rust_source)
            for optimized in (False, True):
                binary = rust.with_suffix('.opt' if optimized else '.debug')
                built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                                       capture_output=True, text=True, timeout=300)
                test.assertEqual(built.returncode, 0, built.stderr)
                test.assertNotIn('warning', built.stderr)
                actual = subprocess.run([str(binary)], input=stdin, capture_output=True, text=True, timeout=60,
                                        env={**os.environ, 'PATH': '/no-python-runtime'})
                outputs.append((integer, optimized, actual.returncode, actual.stdout))
        return outputs


class NativeSortedContainersTests(unittest.TestCase):
    def check(self, name):
        source, stdin, expected = CASES[name]
        for integer, optimized, code, stdout in run(self, source, stdin):
            with self.subTest(integer=integer, optimized=optimized):
                self.assertEqual((code, stdout), (0, expected))

    def test_sorted_list_operations_and_errors(self):
        self.check('sorted_list_operations_and_errors')

    def test_sorted_set_algebra_and_comparisons(self):
        self.check('sorted_set_algebra_and_comparisons')

    def test_sorted_dict_views_and_items(self):
        self.check('sorted_dict_views_and_items')

    def test_sorted_dict_word_counts(self):
        self.check('sorted_dict_word_counts')

    def test_builtins_and_query_loop(self):
        self.check('builtins_and_query_loop')

    def test_unimplemented_upstream_surface_is_positioned(self):
        sources = {
            'from sortedcontainers import SortedList\ns = SortedList([3, 1], key=lambda v: -v)\nprint(s)\n': 2,
            'from sortedcontainers import SortedList\ns = SortedList([3, 1])\ns.append(4)\n': 3,
            'from sortedcontainers import SortedList\ns = SortedList([3, 1])\nprint(s + [5])\n': 3,
            'from sortedcontainers import SortedList\ns = SortedList([3, 1, 2])\nprint(s[0:2])\n': 3,
            'from sortedcontainers import SortedList\ns = SortedList([3, 1])\ns.add(4, 5)\n': 3,
        }
        for source, line in sources.items():
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='sorted.py', license='none'))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code, 'E006')
                self.assertEqual(result.diagnostics[0].line, line)


if __name__ == '__main__':
    unittest.main()
