"""Sequence patterns in match statements, compared with CPython."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeMatchSequenceTests(unittest.TestCase):
    def test_command_words_with_stars_guards_and_alternatives(self):
        compare(self, '''def run(line):
    match line.split():
        case []:
            return "blank"
        case ["move", direction]:
            return "moving " + direction
        case ["grab", "the", _] | ["grab", _]:
            return "grabbing"
        case ["say", *words]:
            return "said " + "-".join(words) + " (" + str(len(words)) + ")"
        case [verb, *rest] if len(rest) >= 3:
            return verb + " with " + str(len(rest)) + " arguments"
        case [verb]:
            return "just " + verb
        case _:
            return "unknown"
for line in input().split(";"):
    print(run(line))
''', 'move up;grab the box;grab it;;say;say hi there;cast a b c;wait;x y\n')

    def test_tuples_nested_patterns_and_non_sequences(self):
        compare(self, '''def locate(point):
    match point:
        case (0, 0):
            return "origin"
        case (0, y):
            return "on y at " + str(y)
        case (x, y) if x == y:
            return "diagonal " + str(x)
        case (x, y):
            return str(x) + "," + str(y)
for point in [(0, 0), (0, 4), (3, 3), (5, -1)]:
    print(locate(point))
def ends(values):
    match values:
        case [first, second, *middle, last]:
            return first + second, len(middle), last
        case [only, *_]:
            return only, 0, only
        case _:
            return 0, 0, 0
print(ends([1, 2, 3, 4, 5]), ends([9]), ends([]), ends([1, 2, 3]))
for record in [(1, (2, 3)), (4, (5, 6))]:
    match record:
        case (a, (b, c)):
            print(a * b + c)
mixed = (7, "seven", 7.5)
match mixed:
    case (number, name, real):
        print(number, name, real)
match 5:
    case [x]:
        print("sequence")
    case 5:
        print("five")
match "ab":
    case [a, b]:
        print("strings are not sequences here")
    case _:
        print("string")
letters = tuple("abc")
match letters:
    case ("a", *others):
        print(others)
''', '')

    def test_union_subjects_stay_positioned(self):
        source = 'def f(flag):\n    value = [1, 2] if flag else 3\n    match value:\n        case [a, b]:\n            return a + b\n    return 0\nprint(f(True), f(False))\n'
        result = transpile(source, TranspileOptions(filename='match.py', license='none'))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code, 'E006')
        self.assertEqual(result.diagnostics[0].line, 4)


if __name__ == '__main__':
    unittest.main()
