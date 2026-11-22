"""__name__, __qualname__ and __module__ of source classes, compared with CPython."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeClassNameMetadataTests(unittest.TestCase):
    def test_names_through_classes_instances_and_nesting(self):
        compare(self, '''class Registry:
    class Entry:
        pass
class Animal:
    def kind(self):
        return type(self).__name__
class Cat(Animal):
    pass
pets = [Animal(), Cat(), Cat()]
for pet in pets:
    print(pet.kind(), type(pet).__qualname__, type(pet).__module__)
print(Registry.Entry.__qualname__, Registry.Entry.__name__, Registry.__module__)
print(f"<{type(pets[1]).__name__}>", Cat.__name__ + "!", type(5).__name__)
''', '')

    def test_class_body_bindings_of_metadata_stay_positioned(self):
        result = transpile('class Odd:\n    __qualname__ = "Even"\nprint(Odd.__qualname__)\n',
                           TranspileOptions(filename='meta.py', license='none'))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code, 'E006')
        self.assertIsNotNone(result.diagnostics[0].line)


if __name__ == '__main__':
    unittest.main()
