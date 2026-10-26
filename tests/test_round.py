"""Decimal rounding, numeric return types, and the user __round__ protocol."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class RoundTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_integer_rounding_and_bigint_precision(self):
        self.run_source('''
            values = [0, 1, -1, 15, 25, 35, -15, -25, -35,
                      100000000000000000000000000000000000000000000012345]
            for value in values:
                for digits in [None, -1000, -40, -5, -2, -1, 0, 1, 1000]:
                    result = round(value, digits)
                    print(result, type(result).__name__)
            print(round(True), round(False, -1))
            print(round(10**1000 + 15, -1))
        ''', integer="bigint")

    def test_float_decimal_ties_signed_zero_and_extremes(self):
        self.run_source('''
            import math
            values = [2.675, -2.675, 1.005, 0.125, 0.375, -0.0,
                      5e-324, -5e-324, 1.2345678901234567,
                      1.7976931348623157e308]
            for value in values:
                for digits in [None, -400, -309, -308, -2, 0, 2, 15, 323, 400]:
                    try:
                        result = round(value, digits)
                        print(result, type(result).__name__,
                              math.copysign(1, result) if isinstance(result, float) else 0)
                    except Exception as error:
                        print(type(error).__name__)
            for value in [float("inf"), -float("inf"), float("nan")]:
                for digits in [None, 0]:
                    try:
                        print(round(value, digits))
                    except Exception as error:
                        print(type(error).__name__)
        ''', integer="bigint")

    def test_keywords_indices_and_custom_protocol(self):
        self.run_source('''
            class Digits:
                def __index__(self):
                    print("index")
                    return 2
            class Rounded:
                def __round__(self, *args):
                    print("round", args)
                    return "custom"
            class IntValue(int):
                pass
            print(round(2.675, ndigits=Digits()))
            print(round(number=125, ndigits=-1))
            print(round(Rounded()), round(Rounded(), None), round(Rounded(), 3))
            print(round(IntValue(125), -1), type(round(IntValue(125))).__name__)
            for thunk in [lambda: round(), lambda: round(1, 2, 3),
                          lambda: round(1, 2, ndigits=3), lambda: round(1, missing=3),
                          lambda: round(1, 1.5), lambda: round("1")]:
                try:
                    thunk()
                except Exception as error:
                    print(type(error).__name__)
        ''')


if __name__ == "__main__":
    unittest.main()
