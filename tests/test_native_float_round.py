"""round() of binary64 values: ties to even, digits bounds and result kinds."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'float_round': ('vals = [2.5, 3.5, -2.5, 0.125, 2.675, 1234.5678, -1250.0, 1350.0, 15.0, 25.0, -0.4, 5e-324, 0.0, -0.0, 123456789.123]\nfor v in vals:\n    print(round(v), round(v, 2), round(v, 0), round(v, -1), round(v, -2), round(v, -3), round(v, 400), round(v, -400))\nprint(round(float("inf"), 2), round(-float("inf"), -1))\nfor bad in [float("inf"), float("nan")]:\n    try:\n        round(bad)\n    except OverflowError:\n        print("overflow")\n    except ValueError:\n        print("value")\nprint(round(1e300, 2), round(1e300, -298), round(9.5e15, -15))\n', ''),
}


class NativeFloatRoundTests(unittest.TestCase):
    def test_float_round(self):
        compare(self, *CASES['float_round'])
