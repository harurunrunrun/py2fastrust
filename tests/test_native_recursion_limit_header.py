"""The usual sys.setrecursionlimit header stays on the ordinary native path."""
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


CASES = {
    'reader_and_limit_header': ('''import sys
input = sys.stdin.readline
sys.setrecursionlimit(10**6)
n = int(input())
values = list(map(int, input().split()))
print(n, sum(values))
''', '3\n4 5 6\n'),
    'shifted_limit_and_unused_recursion': ('''import sys
sys.setrecursionlimit(1 << 25)
def unused(n):
    if n == 0:
        return 0
    return unused(n - 1)
print("ready")
''', ''),
}


class RecursionLimitHeaderTests(unittest.TestCase):
    def test_reader_and_limit_header(self):
        compare(self, *CASES['reader_and_limit_header'])

    def test_shifted_limit_and_unused_recursion(self):
        compare(self, *CASES['shifted_limit_and_unused_recursion'])

    def test_header_does_not_select_frames(self):
        source = CASES['shifted_limit_and_unused_recursion'][0]
        with patch('py2fastrust.native_classes.try_generate_classes', side_effect=AssertionError('frame path')):
            result = transpile(source, TranspileOptions(license='none'))
        self.assertTrue(result.success, result.diagnostics)

    def test_unproved_limits_are_positioned(self):
        for source in ('import sys\nsys.setrecursionlimit(5)\nprint(1)\n',
                       'import sys\nn=10**6\nsys.setrecursionlimit(n)\nprint(1)\n'):
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='limit.py'))
                self.assertFalse(result.success)
                text = '\n'.join(map(str, result.diagnostics))
                self.assertIn('setrecursionlimit', text)
                self.assertIn('limit.py:', text)
