"""sys.maxsize is 2**63 - 1 on the 64-bit target."""
import unittest

from test_native_exception_handlers import compare


class NativeSysMaxsizeTests(unittest.TestCase):
    def test_maxsize(self):
        compare(self, 'import sys\nINF = sys.maxsize\nbest = INF\nfor x in map(int, input().split()):\n    best = min(best, x)\nprint(sys.maxsize, best, INF > 10**18, sys.maxsize // 2)\n'
                'from sys import maxsize\nprint(maxsize == INF, -maxsize - 1)\n', '5 3 9\n')


if __name__ == '__main__':
    unittest.main()
