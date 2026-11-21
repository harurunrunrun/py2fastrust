"""enumerate over text in framed programs compiles without warnings."""
import unittest

from test_native_exception_handlers import compare


class NativeEnumerateTextTests(unittest.TestCase):
    def test_enumerate_text(self):
        compare(self, 'class Marker:\n    pass\nidx = {c: i for i, c in enumerate(input())}\nprint(idx)\nfor i, c in enumerate("abc", 1):\n    print(i, c)\n'
                'print(list(enumerate([5, 6], 1)), next(enumerate("x")))\n', 'hello\n')


if __name__ == '__main__':
    unittest.main()
