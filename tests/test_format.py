"""Python 3.14 formatting, conversion, and precision regression tests."""

from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class FormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-format-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="format_wrapper.py"))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0], expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_ascii_conversion_repr_and_custom_repr(self):
        self.compare(r'''
            values = ["ASCII", "日本 café ß 🙂", ["日本", {"🙂": "é"}], "\\u1234\n\t\x01"]
            class Custom:
                def __repr__(self):
                    return "custom 日本é🙂"
            values.append(Custom())
            for value in values:
                print(ascii(value))
                print(f"{value!a}")
                print(f"{value!a:>40}")
                print(f"{value!r:*^40.12}")
                print(f"{value!s:<40.6}")
                print("{!a:>40}".format(value))
                print("{!r:*^40.12}".format(value))
                print("{!s:<40.6}".format(value))
        ''')

    def test_scientific_and_fixed_rounding(self):
        self.compare('''
            values = [0.0,-0.0,1.0,-1.0,1.23456789,-12.345,2.5,3.5,0.125,9.99999e-5,9.99999e5,1e-99,1e99,1e-308,1e308,5e-324]
            for value in values:
                for specification in ['e','E','.0e','.2E','.17e','f','F','.0f','.2f','.17f','#.0e','#.0f']:
                    print(format(value,specification))
                    print(f"{value:{specification}}")
        ''')

    def test_general_and_omitted_presentation(self):
        self.compare('''
            for value in [0.0,-0.0,1.0,12.0,123456.0,1.23456789,9.99999e-5,1.23e-4,1.23e-5,1e15,1e16,1e308,5e-324]:
                for specification in ['','10','.0','.1','.2','.6','g','G','n','.0g','.1g','.2g','.6g','.17g','#g','#.1g','#.6g','#.3']:
                    print(format(value,specification))
        ''')

    def test_sign_zero_fill_grouping_and_alignment(self):
        self.compare('''
            for value in [1.0,-0.0,-0.0001,12345.6789,-12345.6789,1.23e-5,float('inf'),float('-inf'),float('nan'),-float('nan')]:
                for specification in ['+010.2f',' 010.2f','0>+12.2f','=+12.2f','<010.2f','*^+20.2e','🙂^20.2f','z.2f','+z.2f','z.2g','_.6f',',.6f',',.6_f','_.6,f','.6_f','.6,f','+015,.2f','020,.2e','012,.2%','+.0%','.2G']:
                    print(format(value,specification))
        ''')

    def test_string_precision_unicode_fill_and_validation(self):
        self.compare('''
            for value in ['', 'abc', '日本🙂é']:
                for specification in ['','s','10','010','<10','>10','^10','🙂^10','.2','10.2s','05s','0>5','{^10','}>10']:
                    print(repr(format(value,specification)))
            for value in ['abc',1.0]:
                for specification in ['.','.f','.s','s','d','+5s','-5s','z5s','#s',',s','0=5','1.2.3f','1qq','_,f',',n']:
                    try: print(format(value,specification))
                    except ValueError: print('value error')
        ''')

    def test_random_binary_floats_with_explicit_precision(self):
        rng = random.Random(20261027)
        values = [rng.uniform(-1.0,1.0) * 10.0 ** rng.randrange(-300,301) for _ in range(150)]
        self.compare(f"values={values!r}\n"+textwrap.dedent('''
            for value in values:
                for specification in ['.0e','.6e','.17e','.0f','.6f','.17f','.0g','.6g','.17g']:
                    print(format(value,specification))
        '''))


if __name__ == "__main__":
    unittest.main()
