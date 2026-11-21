"""print(..., file=sys.stderr) writes the rendered line to standard error."""
import unittest

from test_native_exception_handlers import compare


class NativePrintStderrTests(unittest.TestCase):
    def test_debug_output(self):
        compare(self, 'import sys\nn = int(input())\nprint("debug", n, [n, n * 2], file=sys.stderr)\nprint(n + 1)\nprint("x", "y", sep="-", end="!\\n", file=sys.stderr)\nprint("same", file=sys.stdout)\n', '4\n')
        compare(self, 'from sys import stderr\nfor i in range(3):\n    print(i, file=stderr)\nprint("done")\n', '')


if __name__ == '__main__':
    unittest.main()
