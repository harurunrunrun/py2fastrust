"""math.gcd and math.lcm with expanded integer arguments."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'expanded_gcd_lcm': ('from math import gcd, lcm\nimport math\na = [12, 18, 30]\nprint(gcd(*a), lcm(*a), math.gcd(*a, 4), gcd(*[]), lcm(*[]))\nprint(gcd(*[True, 4]), lcm(*[-4, 6]))\n', ''),
}


class NativeExpandedGcdTests(unittest.TestCase):
    def test_expanded_gcd_lcm(self):
        compare(self, *CASES['expanded_gcd_lcm'])
