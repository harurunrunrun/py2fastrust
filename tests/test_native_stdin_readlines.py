"""sys.stdin.readlines() and sys.stdin.buffer.readlines() read every remaining line."""
import unittest

from test_native_exception_handlers import compare

STDIN = 'head\n1 2\n\n3 4 5\n6'


class NativeStdinReadlinesTests(unittest.TestCase):
    def test_text_lines_after_input(self):
        compare(self, 'import sys\nfirst = input()\nlines = sys.stdin.readlines()\nprint(first, len(lines), lines)\n'
                'total = 0\nfor line in lines:\n    total += sum(map(int, line.split()))\nprint(total, sys.stdin.readlines())\n', STDIN)

    def test_buffer_lines(self):
        compare(self, 'import sys\nrows = sys.stdin.buffer.readlines()\nprint(rows, sum(len(row) for row in rows))\n', STDIN)

    def test_empty_input(self):
        compare(self, 'import sys\nprint(sys.stdin.readlines())\n', '')


if __name__ == '__main__':
    unittest.main()
