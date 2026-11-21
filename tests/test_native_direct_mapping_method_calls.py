"""Direct d.get(...) / d.setdefault(...) calls do not allocate a bound-method object."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare

SOURCE = ('d = {}\nfor i in range(int(input())):\n    k = i * 7 % 11\n    d[k] = d.get(k, 0) + i\n    d.setdefault(-k, []).append(i)\n'
          'print(sorted(d.items(), key=lambda kv: kv[0]))\nf = d.get\nprint(f(3), f(99, "none"))\n')


class NativeDirectMappingMethodTests(unittest.TestCase):
    def test_output(self):
        compare(self, SOURCE.replace('d[k] = d.get(k, 0) + i\n    d.setdefault(-k, []).append(i)\n', 'd[k] = d.get(k, 0) + i\n'), '30\n')
        compare(self, 'g = {}\nfor i in range(5):\n    g.setdefault(i % 2, []).append(i)\nprint(g, g.get(0), g.get(7))\n', '')

    def test_direct_calls_build_the_method_by_value(self):
        source = 'd = {}\nfor i in range(10):\n    d[i % 3] = d.get(i % 3, 0) + 1\nprint(d)\n'
        result = transpile(source, TranspileOptions(filename='direct.py', license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertNotIn('Rc::new(NativeMappingMethod', result.rust_source)


if __name__ == '__main__':
    unittest.main()
