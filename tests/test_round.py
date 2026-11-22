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

if __name__ == "__main__":
    unittest.main()
