"""str.splitlines, partition and rpartition compared with CPython."""
import unittest

from test_native_exception_handlers import compare


class NativeTextPartitionTests(unittest.TestCase):
    def test_splitlines(self):
        compare(self, 'import sys\nfor s in ["", "a", "a\\n", "a\\nb", "a\\r\\nb\\rc\\n\\n", "\\n\\n", "x\\x0by\\x0cz\\x1cw", "end\\r"]:\n'
                '    print(s.splitlines(), s.splitlines(True), s.splitlines(keepends=False))\n'
                'lines = sys.stdin.read().splitlines()\nprint(len(lines), lines)\n', 'first line\r\nsecond\n\nlast')

    def test_partition(self):
        compare(self, 'for s in ["key=value", "a=b=c", "plain", "=x", "x="]:\n    print(s.partition("="), s.rpartition("="))\n'
                'head, sep, tail = input().partition(" ")\nprint(repr(head), repr(sep), repr(tail))\n'
                'try:\n    "abc".partition("")\nexcept ValueError as error:\n    print(error)\n', 'hello big world\n')


if __name__ == '__main__':
    unittest.main()
