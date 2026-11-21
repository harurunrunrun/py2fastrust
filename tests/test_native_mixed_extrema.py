"""min/max over int and float candidates keep the original winning object."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'infinity_distances': ('INF=float("inf")\nprint(min(INF,3),max(2,2.0),min(1,1.0))\nd=[INF]*3\nd[0]=0\nprint(min(d),d)\nn = 4\ndist = [INF] * n\ndist[0] = 0\nfor i in range(1, n):\n    dist[i] = min(dist[i], dist[i - 1] + 2)\nprint(dist, max(dist), min(3, 2.5, 7))\n', ''),
}


class NativeMixedExtremaTests(unittest.TestCase):
    def test_infinity_distances(self):
        compare(self, *CASES['infinity_distances'])
