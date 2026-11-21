"""Constants of the canonical string module."""
import unittest

from test_native_exception_handlers import compare


class NativeStringModuleTests(unittest.TestCase):
    def test_constants(self):
        compare(self, 'import string\nfor name in ["whitespace", "ascii_lowercase", "ascii_uppercase", "ascii_letters", "digits", "hexdigits", "octdigits", "punctuation", "printable"]:\n    pass\n'
                'print(repr(string.whitespace), string.ascii_lowercase, string.ascii_uppercase, string.ascii_letters)\n'
                'print(string.digits, string.hexdigits, string.octdigits, repr(string.punctuation), repr(string.printable))\n'
                'idx = {c: i for i, c in enumerate(string.ascii_lowercase)}\ns = input()\nprint([idx[c] for c in s], "".join(string.ascii_uppercase[idx[c]] for c in s))\n', 'hello\n')

    def test_from_import(self):
        compare(self, 'from string import ascii_lowercase as al, digits\nprint(al.index("z"), digits[::-1], len(al))\n', '')


if __name__ == '__main__':
    unittest.main()
