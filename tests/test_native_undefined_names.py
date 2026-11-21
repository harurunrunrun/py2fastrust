"""Reading a global name that nothing binds raises NameError when the read executes."""
import unittest

from test_native_exception_handlers import compare


class NativeUndefinedNameTests(unittest.TestCase):
    def test_runtime_name_errors(self):
        for source in ('print(1)\nprint(missing)\n', 'print_numbers()\n', 'two = add_one(1)\nprint(two)\n',
                       'def g(flag):\n    if flag:\n        return undefined_value\n    return 0\nprint(g(False))\nprint(g(True))\n',
                       'try:\n    print(nothing)\nexcept NameError as error:\n    print("caught", error)\n'):
            with self.subTest(source=source):
                compare(self, source, '')


if __name__ == '__main__':
    unittest.main()
