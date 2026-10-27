"""Valid unsupported Unicode literals differ from malformed source syntax."""
import ast
import shutil
import subprocess
import unittest
import test_codecs

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class UnicodeDiagnosticTests(unittest.TestCase):
    setUpClass = classmethod(test_codecs.CodecTests.setUpClass.__func__)
    tearDownClass = classmethod(test_codecs.CodecTests.tearDownClass.__func__)
    compare = test_codecs.CodecTests.compare

    def test_valid_unsupported_surrogates_have_positioned_unsupported_errors(self):
        literals = [r"'\ud800'", r"u'\udfff'", r"'\U0000d800'",
                    r'f"\ud800{x}"', r't"\ud800"']
        for literal in literals:
            ast.parse(literal, 'literal.py', mode='eval')
        source = ('x=1\nfor literal in ' + repr(literals) + ':\n'
                  ' try: compile(literal,"literal.py","eval")\n'
                  ' except NotImplementedError as error:\n'
                  '  print("surrogates are not supported" in str(error),'
                  ' "literal.py:1" in str(error), "column " in str(error))\n')
        result = subprocess.run([str(self.binary)], input=source, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'True True True\n' * len(literals))

    def test_raw_bytes_valid_scalars_and_invalid_escapes_keep_their_rules(self):
        self.compare(r'''
            values=[r"r'\ud800'",r"b'\ud800'",r"'\ud7ff'",r"'\ue000'",r"'\U0010ffff'"]
            for value in values:
                print(repr(eval(value)))
            for value in [r"'\uABC'",r"'\U00110000'",r"'\xX0'"]:
                try:compile(value,'invalid.py','eval')
                except SyntaxError as error:print(type(error).__name__)
        ''')

    def test_aot_surrogate_diagnostics_keep_original_source_location(self):
        result = transpile(r"value='\ud800'" + '\n', TranspileOptions(filename='original.py'))
        self.assertFalse(result.success)
        diagnostic = result.diagnostics[0]
        self.assertEqual((diagnostic.filename, diagnostic.line, diagnostic.column), ('original.py', 1, 7))
        self.assertIn('surrogates are not supported', diagnostic.message)


if __name__ == '__main__':
    unittest.main()
