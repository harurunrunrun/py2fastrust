"""open(0) reads standard input with universal newlines."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare

DATA = '3\r\n1 2\r3\n\n4 5\r\n6'


class NativeOpenStdinTests(unittest.TestCase):
    def test_read_split(self):
        compare(self, 'n, *a = map(int, open(0).read().split())\nprint(n, sum(a), a)\n', DATA)

    def test_read_translates_newlines(self):
        compare(self, 'text = open(0).read()\nprint(repr(text), text.splitlines())\n', DATA)

    def test_line_iteration(self):
        compare(self, 'for line in open(0):\n    print(repr(line))\n', DATA)
        compare(self, 'rows = [line.split() for line in open(0)]\nprint(rows)\n', DATA)

    def test_readline_then_rest(self):
        compare(self, 'f = open(0)\nfirst = f.readline()\nsecond = f.readline()\nprint(repr(first), repr(second), f.readlines(), repr(f.read()), repr(f.readline()))\n', DATA)
        compare(self, 'f = open(0)\nprint(repr(f.readline()), repr(f.read()))\n', 'a\rb\r\nc')
        compare(self, 'print(open(0).readlines())\n', '')

    def test_mixed_readers_are_positioned(self):
        for source in ('x = input()\nprint(open(0).read())\n', 'for i in range(2):\n    print(open(0).read())\n', 'print(open("data.txt").read())\n'):
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='o.py'))
                self.assertFalse(result.success)
                self.assertIn('o.py:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
