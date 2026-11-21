"""for loops and comprehensions over sys.stdin and sys.stdin.buffer."""
import unittest

from test_native_exception_handlers import compare

STDIN = 'head\n1 2\n\n3 4 5\n6'

CASES = {
    'text_lines_after_input': 'import sys\nfirst = input()\ntotal = 0\nfor line in sys.stdin:\n    parts = line.split()\n    if not parts:\n        continue\n    total += sum(map(int, parts))\n    print(repr(line))\nprint(first, total)\n',
    'comprehension_lines': 'import sys\nrows = [line.rstrip("\\n") for line in sys.stdin]\nprint(rows)\n',
    'buffer_lines': 'import sys\nn = 0\nfor raw in sys.stdin.buffer:\n    n += len(raw)\n    print(raw)\nprint(n)\n',
}


class NativeStdinIterationTests(unittest.TestCase):
    def test_text_lines_after_input(self):
        compare(self, CASES['text_lines_after_input'], STDIN)

    def test_comprehension_lines(self):
        compare(self, CASES['comprehension_lines'], STDIN)

    def test_buffer_lines(self):
        compare(self, CASES['buffer_lines'], STDIN)
