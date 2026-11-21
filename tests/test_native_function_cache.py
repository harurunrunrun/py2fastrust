"""functools.cache and lru_cache(maxsize=None) on module-level functions."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


CASES = {
    'memoized_recursion': ('''import sys
from functools import cache, lru_cache
import functools
sys.setrecursionlimit(20000)
visits = []
@cache
def paths(row, column):
    visits.append((row, column))
    if row == 0 or column == 0:
        return 1
    return (paths(row - 1, column) + paths(row, column - 1)) % 998244353
print(paths(25, 25), len(visits))
print(paths(25, 25), len(visits))
@lru_cache(maxsize=None)
def chain(n):
    if n == 0:
        return 0
    return chain(n - 1) + 1
print(chain(2500))
@functools.cache
def repeat(text, count):
    print("build", text, count)
    return text * count
print(repeat("xy", 2), repeat("xy", 2), repeat("xy", 3))
''', ''),
    'errors_are_not_cached': ('''from functools import lru_cache
tries = []
@lru_cache(None)
def flaky(n):
    tries.append(n)
    if len(tries) == 1:
        raise ValueError("first")
    return n * 3
try:
    flaky(5)
except ValueError:
    print("failed")
print(flaky(5), flaky(5), tries)
''', ''),
    'tuple_keys_and_results': ('''from functools import cache
@cache
def combine(pair):
    print("combine", pair)
    return (pair[0] + pair[1], pair[0] * pair[1])
print(combine((2, 5)), combine((2, 5)), combine((5, 2)))
''', ''),
    'input_driven_division_memo': ('''from functools import cache
@cache
def split(n):
    if n == 0:
        return 1
    return split(n // 2) + split(n // 3) + split(n // 5)
print(split(int(input())))
''', '1000000000000\n'),
    'non_recursive_wrapper': ('''from functools import cache
@cache
def twice(n):
    print("run", n)
    return n * 2
print(twice(3), twice(3), twice(4))
''', ''),
}


class NativeFunctionCacheTests(unittest.TestCase):
    def test_memoized_recursion(self):
        compare(self, *CASES['memoized_recursion'])

    def test_errors_are_not_cached(self):
        compare(self, *CASES['errors_are_not_cached'])

    def test_tuple_keys_and_results(self):
        compare(self, *CASES['tuple_keys_and_results'])

    def test_input_driven_division_memo(self):
        compare(self, *CASES['input_driven_division_memo'])

    def test_non_recursive_wrapper(self):
        compare(self, *CASES['non_recursive_wrapper'])

    def test_unproved_wrappers_are_positioned(self):
        head = 'from functools import cache, lru_cache\n'
        boundaries = {
            '@lru_cache\ndef f(n):\n    return n\nprint(f(1))\n': ('bounded LRU', ':2:2:'),
            '@cache\ndef f(n):\n    return n\nprint(f(1))\nf.cache_clear()\n': ('used as a value', ':6:1:'),
            '@cache\ndef f(n):\n    return n\nprint(f(n=1))\n': ('positionally', ':5:7:'),
            'def outer():\n    @cache\n    def f(n):\n        return n\n    return f(2)\nprint(outer())\n': ('top-level module statement', ':3:6:'),
            '@cache\ndef f(x):\n    return x\nprint(f(1.5))\n': ('hash/equality', ':5:7:'),
            '@cache\ndef f(n):\n    return [n]\nprint(f(1))\n': ('mutable or identity-bearing', ':5:7:'),
            'factory=cache\nprint(factory)\n': ('first-class cache factory', ':2:9:'),
        }
        for body, (reason, position) in boundaries.items():
            with self.subTest(source=body):
                result = transpile(head + body, TranspileOptions(filename='boundary.py'))
                self.assertFalse(result.success)
                text = '\n'.join(map(str, result.diagnostics))
                self.assertIn(reason, text)
                self.assertIn('boundary.py' + position, text)
