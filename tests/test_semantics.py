"""Regression cases spanning control flow, object identity and namespaces."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class SemanticsTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_comprehension_closures_and_walrus_scope(self):
        self.run_source('''
            x = 99
            def f():
                print(x)
                functions = [lambda: i for i in range(3)]
                print([g() for g in functions])
                values = [(last := i*i) for i in range(4)]
                print(values, last, x)
                return list((last := last + 1) for _ in range(2))
            print(f())
            print(x)
            print([(outside := i) for i in range(2)], outside)
        ''')

if __name__ == "__main__":
    unittest.main()
