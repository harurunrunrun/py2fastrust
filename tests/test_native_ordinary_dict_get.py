"""d.get(key, literal) stays on the ordinary path and matches CPython."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare

PROGRAMS = (
    'd = {}\nfor i in range(int(input())):\n    k = i * 7 % 11\n    d[k] = d.get(k, 0) + i\nprint(d, d.get(99, -1))\n',
    'd = {}\nfor w in input().split():\n    d[w] = d.get(w, 0) + 1\nprint(sorted(d.items()), d.get("zz", 0))\n',
    'd = {(1, 2): 3}\nprint(d.get((1, 2), 0), d.get((0, 0), -1))\n',
    'd = {"a": 1.5}\nprint(d.get("a", 0), d.get("b", 2.5))\n',
    'd = {1: "x"}\nprint(d.get(2, "y") + "z", d.get(1, "q"))\n',
    'd = {1: True}\nprint(d.get(1, False), d.get(3, False))\n',
)


class NativeOrdinaryDictGetTests(unittest.TestCase):
    def test_outputs(self):
        for source in PROGRAMS:
            with self.subTest(source=source):
                compare(self, source, '12\n')

    def test_counting_idiom_stays_ordinary(self):
        result = transpile(PROGRAMS[0], TranspileOptions(filename='count.py', license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertNotIn('ClassScope', result.rust_source)


if __name__ == '__main__':
    unittest.main()
