"""Empty-body source exception subclasses, compared with CPython."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeUserExceptionTests(unittest.TestCase):
    def test_handlers_follow_the_source_hierarchy(self):
        compare(self, '''class ConfigError(Exception):
    """Raised for bad settings."""
class MissingSetting(ConfigError):
    pass
class Unknown(LookupError):
    ...
def load(name):
    if name == "":
        raise MissingSetting("name is empty")
    if name.startswith("?"):
        raise Unknown(name, len(name))
    if name == "!":
        raise MissingSetting
    return name.upper()
for item in ["port", "", "?x", "!"]:
    try:
        print(load(item))
    except ConfigError as error:
        print("config:", error)
    except LookupError as error:
        print("lookup:", error)
print(ConfigError, isinstance(MissingSetting("a"), ConfigError), isinstance(Unknown(), ConfigError))
print(repr(Unknown("k", 2)), str(MissingSetting()), repr(MissingSetting("only")))
''', '')

    def test_builtin_handlers_catch_source_subclasses_and_tracebacks(self):
        compare(self, '''class Done(Exception):
    pass
class Level1(ValueError):
    pass
class Level2(Level1):
    pass
def scan(rows):
    try:
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if cell < 0:
                    raise Done
    except Done:
        return r, c
    return None
print(scan([[1, 2], [3, -4]]), scan([[5]]))
def descend(n):
    if n == 0:
        raise Level2("bottom")
    return descend(n - 1)
try:
    descend(3)
except (TypeError, Level1) as error:
    print("value family:", error)
try:
    int("nope")
except Level1:
    print("never")
except ValueError as error:
    print("plain value error:", error)
try:
    raise Level1("outer")
finally:
    print("cleanup")
''', '')

    def test_unsupported_exception_classes_stay_positioned(self):
        sources = {
            'class Info(Exception):\n    def __init__(self, code):\n        self.code = code\nraise Info(1)\n': 1,
            'class Stop2(StopIteration):\n    pass\nraise Stop2\n': 1,
            'class E(Exception):\n    pass\nE = ValueError\nraise E\n': 3,
            'class print(Exception):\n    pass\nraise print\n': 1,
        }
        for source, line in sources.items():
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='errors.py', license='none'))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code, 'E006')
                self.assertEqual(result.diagnostics[0].line, line)


if __name__ == '__main__':
    unittest.main()
