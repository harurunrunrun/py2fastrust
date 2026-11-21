"""Item assignment to tuples, strings and other immutable builtins raises TypeError."""
import unittest

from test_native_exception_handlers import compare


class NativeImmutableItemAssignmentTests(unittest.TestCase):
    def test_caught_errors(self):
        compare(self, 'def value():\n    print("value")\n    return 9\ndef index():\n    print("index")\n    return 0\n'
                't = (3, 1, 4)\ntry:\n    t[index()] = value()\nexcept TypeError as error:\n    print(error)\n'
                's = "abc"\ntry:\n    s[1] = "x"\nexcept TypeError as error:\n    print(error)\nnested = ((1, 2), (3, 4))\ntry:\n    nested[0][1] = 5\nexcept TypeError as error:\n    print(error)\nprint(t, s, nested)\n', '')

    def test_uncaught_error(self):
        compare(self, 't = (3, 1, 4, 1, 5)\nt[0] = 9\nprint("unreachable")\n', '')


if __name__ == '__main__':
    unittest.main()
