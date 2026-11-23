"""Starred call arguments over source __iter__ objects, compared with CPython."""
import unittest

from test_native_exception_handlers import compare


class NativeStarredSourceIterableTests(unittest.TestCase):
    def test_print_expands_source_iterables(self):
        compare(self, '''class Grid:
    def __init__(self):
        self.rows = [[1, 2], [3], []]
    def __iter__(self):
        for row in self.rows:
            for value in row:
                yield value
class Countdown:
    def __init__(self, start):
        self.start = start
    def __iter__(self):
        current = self.start
        while current > 0:
            yield current
            current -= 1
grid = Grid()
print(*grid)
print("values:", *grid, sep=" | ")
print(*Countdown(3), *Countdown(0), "liftoff", end="!\\n")
''', '')


if __name__ == '__main__':
    unittest.main()
