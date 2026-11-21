"""printf-style formatting of literal format strings."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


CASES = {
    'directives_flags_and_precision': ('v = 42\nw = 2.5\nprint("%d %x %.3f %s" % (v, v, w, "ok"))\nprint("%5d|%-3s|%05.1f|%+d|% d|%#x|%#o|%X" % (v, "a", w, v, v, 255, 8, 255))\nprint("%s and %r" % ("x", "y"))\nprint("%d%%" % 50)\nprint("%.2e %g %G" % (12345.678, 0.0001, 1e20))\nprint("%d" % 3.9, "%i" % -2.5, "%s" % [1, 2], "%s" % True, "%d" % True)\nprint("%.2s|%10.3s|" % ("abcdef", "xyz123"))\nprint("total: %d" % (7,))\nn = 3\nprint("Case #%d: %s" % (n, "yes"))\n', ''),
    'argument_and_type_errors': ('for operand in [7, "x", 2.5]:\n    try:\n        print("%x" % operand)\n    except TypeError:\n        print("type", operand)\ntry:\n    print("%d %d" % (1,))\nexcept TypeError:\n    print("few")\ntry:\n    print("%d" % (1, 2))\nexcept TypeError:\n    print("many")\nprint("%s" % 2.5, "%d" % "x")\n', ''),
    'characters': ('print("%c%c%c" % (72, "i", True))\nprint("[%3c|%-3c|%.0c|%05c]" % (65, "b", 0x263A, "z"))\nfor operand in [-1, 0x110000, "xy", 1.5, None]:\n    try:\n        print("%c" % operand)\n    except TypeError as error:\n        print("TypeError", error)\n    except OverflowError as error:\n        print("OverflowError", error)\nprint("%c" % 10**30)\n', ''),
}


class NativePercentFormatTests(unittest.TestCase):
    def test_directives_flags_and_precision(self):
        compare(self, *CASES['directives_flags_and_precision'])

    def test_argument_and_type_errors(self):
        compare(self, *CASES['argument_and_type_errors'])

    def test_characters(self):
        compare(self, *CASES['characters'])

    def test_unimplemented_directives_are_positioned(self):
        for source in ('print("%*d" % (3, 4))\n', 'print("%(a)s" % {"a": 1})\n', 'print("%.3d" % 4)\n'):
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='percent.py'))
                self.assertFalse(result.success)
                text = '\n'.join(map(str, result.diagnostics))
                self.assertIn('printf-style format', text)
                self.assertIn('percent.py:1:7:', text)
