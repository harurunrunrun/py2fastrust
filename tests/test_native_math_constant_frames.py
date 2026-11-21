"""Reads of math.pi, e, tau, inf and nan select the framed module data."""
import unittest

from test_native_exception_handlers import compare


class NativeMathConstantFrameTests(unittest.TestCase):
    def test_module_attributes(self):
        compare(self, 'import math\nr = int(input())\nprint(math.pi * r * r, math.e, math.tau, math.inf > r, -math.inf, math.nan != math.nan)\n'
                'best = math.inf\nfor v in [5, 3, 9]:\n    best = min(best, v)\nprint(best, math.sqrt(r) < math.inf)\n', '3\n')

    def test_imported_names_and_alias(self):
        compare(self, 'from math import pi as P, inf\nimport math as m\nprint(round(P, 5), inf, m.e ** 2, f"{m.pi:.10f}")\n', '')


if __name__ == '__main__':
    unittest.main()
