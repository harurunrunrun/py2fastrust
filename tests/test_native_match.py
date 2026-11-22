"""match statements with value, singleton, capture, wildcard and or-patterns."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


CASES = {
    'values_captures_guards': ('def describe(n):\n    match n:\n        case 0:\n            return "zero"\n        case 1 | 2 | 3:\n            return "small"\n        case big if big > 100:\n            return "big " + str(big)\n        case None:\n            return "none"\n        case _:\n            return "other"\nfor v in [0, 2, 150, 50]:\n    print(describe(v))\ncommand = input().strip()\nmatch command:\n    case "go":\n        print("going")\n    case "stop" | "halt":\n        print("stopping")\n    case other:\n        print("unknown", other)\nx = 5\nmatch x:\n    case y if y < 0:\n        print("neg")\nprint(y)\nflag = True\nmatch flag:\n    case True:\n        print("yes")\n    case False:\n        print("no")\n', 'halt\n'),
}


class NativeMatchTests(unittest.TestCase):
    def test_values_captures_guards(self):
        compare(self, *CASES['values_captures_guards'])

    def test_structural_patterns_are_positioned(self):
        for source in ('match {1: 2}:\n    case {1: a}:\n        print(a)\n',
                       'match 3:\n    case int():\n        print(1)\n',
                       'match 3:\n    case (1 as x) | (2 as x):\n        print(x)\n'):
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='match.py'))
                self.assertFalse(result.success)
                text = '\n'.join(map(str, result.diagnostics))
                self.assertIn('patterns need structural extraction', text)
                self.assertIn('match.py:2:', text)
