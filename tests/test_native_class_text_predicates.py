"""str/bytes is*() predicates in programs selected for frames."""
import unittest

from test_native_exception_handlers import compare


NAMES = ('isupper', 'islower', 'isalpha', 'isalnum', 'isascii', 'isdecimal', 'isdigit', 'isnumeric', 'isspace', 'istitle', 'isidentifier')


def program(texts, header=''):
    rows = '\n'.join('    print(%r, text.%s())' % (name, name) for name in NAMES)
    return (header + 'class Box:\n    def __init__(self, text):\n        self.text = text\n'
            'for text in [' + ', '.join(texts) + ']:\n'
            '    print(repr(text), Box(text).text.find("a"))\n' + rows + '\n'
            'line = input()\nprint(line.isdigit(), line.strip().isdigit())\n')


class NativeClassTextPredicateTests(unittest.TestCase):
    def test_ascii_profile(self):
        texts = ['""', '"abc"', '"ABC"', '"Abc Def"', '"123"', '" \\t\\n"', '"a_1"', '"1a"', '"Hello World"']
        compare(self, program(texts), ' 42 \n')

    def test_unicode_profile(self):
        texts = ['"٣²"', '"½"', '"été"', '"Σα"', '"ǅx"', '"　"', '"日本"']
        compare(self, program(texts, '# pytors: --string-mode unicode\n'), ' 42 \n')

    def test_bytes_predicates(self):
        compare(self, 'class Box:\n    pass\nBox()\nfor raw in [b"", b"abc", b"ABC", b"12", b" \\t", b"Ab Cd", b"a1"]:\n'
                '    print(raw, raw.isupper(), raw.islower(), raw.isalpha(), raw.isalnum(), raw.isascii(), raw.isdigit(), raw.isspace(), raw.istitle())\n', '')


if __name__ == '__main__':
    unittest.main()
