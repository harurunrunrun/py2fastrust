"""Assignment expressions in conditions, loops and comprehensions."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'conditions_loops_and_comprehensions': ('a=[1,2,3]\nif (n:=len(a))>2:\n    print(n)\nwhile (x:=a.pop())>1:\n    print(x)\nprint([y for v in a if (y:=v*2)>0])\n', ''),
}


class NativeAssignmentExpressionTests(unittest.TestCase):
    def test_conditions_loops_and_comprehensions(self):
        compare(self, *CASES['conditions_loops_and_comprehensions'])
