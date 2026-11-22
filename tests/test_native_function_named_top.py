"""A function named "top" keeps its own locals (symtable reports them as global; see frontend)."""
import unittest

from test_native_exception_handlers import compare


class FunctionNamedTopTests(unittest.TestCase):
    def test_parameters_and_locals_on_both_paths(self):
        body = ('def bottom(x):\n print(8)\n return 10//x\ndef middle(x):\n return bottom(x-2)\n'
                'def top(x):\n y = middle(x)\n return y + x\nprint(1)\nprint(top(int(input())))\n')
        for source in (body, 'class Marker:\n pass\n' + body):
            for data in ('4\n', '2\n'):
                with self.subTest(source=source[:20], stdin=data):
                    compare(self, source, data)

    def test_declared_global_inside_top(self):
        compare(self, 'class Marker:\n pass\ng = 5\ndef top():\n global g\n g += 1\n return g\nprint(top(), g)\n', '')


if __name__ == '__main__':
    unittest.main()
