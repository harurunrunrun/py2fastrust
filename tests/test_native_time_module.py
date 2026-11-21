"""time module clocks and sleep, compared with CPython on clock-independent output."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeTimeModuleTests(unittest.TestCase):
    def test_clocks_measure_elapsed_work(self):
        compare(self, 'import time\nstart = time.time()\ntotal = 0\nfor i in range(200000):\n    total += i * i\nend = time.time()\n'
                'print(total, end >= start, type(end).__name__, end > 1.6e9)\n'
                'from time import perf_counter, monotonic, perf_counter_ns, monotonic_ns, time_ns\n'
                'a, b = perf_counter(), monotonic()\nc, d = perf_counter_ns(), monotonic_ns()\n'
                'print(perf_counter() >= a, monotonic() >= b, perf_counter_ns() >= c, monotonic_ns() >= d, type(c).__name__)\n'
                'print(time_ns() // 10**9 >= int(start) - 1)\n', '')

    def test_sleep_waits_and_converts_durations(self):
        compare(self, 'import time\nbefore = time.perf_counter()\ntime.sleep(0.02)\ntime.sleep(0)\ntime.sleep(False)\nprint(time.perf_counter() - before >= 0.02)\n'
                'for value in [-1, -0.5, float("nan"), 10**30, 1e300, "x", None]:\n    try:\n        time.sleep(value)\n    except ValueError as error:\n        print("ValueError", error)\n'
                '    except OverflowError as error:\n        print("OverflowError", error)\n    except TypeError as error:\n        print("TypeError", error)\n', '')

    def test_binding_errors_and_uncaught_sleep_error(self):
        compare(self, 'import time\nfor call in [lambda: time.time(1), lambda: time.sleep(), lambda: time.monotonic_ns(2)]:\n    try:\n        call()\n'
                '    except TypeError as error:\n        print(error)\nn = int(input())\ntime.sleep(n)\nprint("unreachable")\n', '-3\n')

    def test_source_instance_duration_is_positioned(self):
        result = transpile('import time\nclass D:\n    pass\ntime.sleep(D())\n', TranspileOptions(filename='tm.py'))
        self.assertFalse(result.success)
        self.assertIn('tm.py:4:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
