import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StandardLibraryTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_bisect_public_api_and_custom_key(self):
        self.run_source('''
            import bisect
            a = [1, 2, 2, 4]
            print(bisect.bisect_left(a, 2), bisect.bisect_right(a, 2), bisect.bisect(a, 3))
            bisect.insort_left(a, 2)
            bisect.insort_right(a, 3)
            bisect.insort(a, 5)
            print(a)
            records = [(1, "a"), (3, "b")]
            bisect.insort(records, (2, "c"), key=lambda x: x[0])
            print(records, bisect.bisect_left(records, 3, key=lambda x: x[0]))
            try:
                bisect.bisect_left(a, 2, -1)
            except ValueError:
                print("negative lo")
        ''')

    def test_deep_recursion_uses_heap_frames(self):
        self.run_source('''
            import sys
            sys.setrecursionlimit(10000)
            def descend(n):
                return 0 if n == 0 else descend(n-1) + 1
            print(descend(5000))
        ''')


if __name__ == "__main__":
    unittest.main()
