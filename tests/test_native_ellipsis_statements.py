"""An ``...`` expression statement is a placeholder that only loads a constant."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeEllipsisStatementTests(unittest.TestCase):
    def test_ordinary_placeholders(self):
        compare(self, '...\nn = int(input())\ndef todo(x):\n    ...\ndef body(x):\n    ...\n    return x * 2\nprint(todo(n), body(n))\nfor i in range(n):\n    ...\nprint("done")\n', '3\n')

    def test_framed_placeholders(self):
        compare(self, 'class Empty:\n    ...\nclass Item:\n    def later(self):\n        ...\n    def value(self):\n        return 5\n'
                'print(Item().later(), Item().value(), isinstance(Empty(), Empty))\ndef guarded(text):\n    try:\n        return int(text)\n    except ValueError:\n        ...\n    return -1\nprint(guarded("7"), guarded("x"))\n', '')

    def test_ellipsis_value_is_positioned(self):
        result = transpile('x = ...\nprint(x)\n', TranspileOptions(filename='ellipsis.py'))
        self.assertFalse(result.success)
        self.assertIn('ellipsis.py:1:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
