"""__name__ and __qualname__ of source functions, compared with CPython."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeFunctionNameMetadataTests(unittest.TestCase):
    def test_names_of_functions_lambdas_nested_and_class_functions(self):
        compare(self, '''def area(w, h):
    return w * h
def factory():
    def made():
        return 1
    return made
class Tools:
    @staticmethod
    def scale(x):
        return x * 3
    def act(self):
        return 0
square = lambda v: v * v
for function in [area, factory]:
    print(function.__name__, function.__qualname__)
print(factory().__qualname__, square.__name__, Tools.scale.__qualname__, Tools.act.__qualname__)
print(f"{area.__name__}(2, 5) = {area(2, 5)}", area.__name__.upper())
''', '')

    def test_function_name_writes_stay_positioned(self):
        result = transpile('def f():\n    pass\nf.__name__ = "g"\nprint(f.__name__)\n',
                           TranspileOptions(filename='names.py', license='none'))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code, 'E006')
        self.assertEqual(result.diagnostics[0].line, 3)


if __name__ == '__main__':
    unittest.main()
