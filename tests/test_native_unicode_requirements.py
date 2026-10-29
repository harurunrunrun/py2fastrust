"""Unicode data is selected by operations, independently of optional pruning."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_unicode_tables import unicode_tables


INTEGER_CLASS = '''class Counter:
    def __init__(self, value):
        self.value = value
    def take(self):
        return self.value
item = Counter(42)
print(item.take())
'''

INTEGER_RECURSION = '''def total(n):
    if n == 0:
        return 0
    return n + total(n - 1)
print(total(20))
'''

FLOAT_CLASS = '''class Real:
    def __init__(self):
        self.value = 1.25
value = Real()
print(value.value)
'''


class NativeUnicodeRequirementTests(unittest.TestCase):
    def test_numeric_programs_do_not_request_unicode_data(self):
        sources = ("print(40 + 2)\n", "print([1, 2, 3])\n",
                   "print(12345678901234567890123456789012345678901234567890)\n",
                   'print("ZEROES RANGES TEXT_PRINTABLE")\n',
                   INTEGER_CLASS, INTEGER_RECURSION, FLOAT_CLASS)
        for source in sources:
            for mode in ("i64", "i128", "bigint"):
                for optimize in (False, True):
                    with self.subTest(source=source, integer=mode, optimize=optimize):
                        result = transpile(source, TranspileOptions(integer=mode, optimize=optimize,
                                           string_mode="unicode", license="none"))
                        self.assertTrue(result.success, result.diagnostics)
                        self.assertEqual(tuple(table.name for table in unicode_tables(result.rust_source)), ())
                        self.assertNotIn("// UNICODE LICENSE V3", result.rust_source)

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_numeric_runtime_without_unicode_data_executes(self):
        self.compare(INTEGER_CLASS)
        self.compare(INTEGER_RECURSION)
        self.compare(FLOAT_CLASS)
        values = [sign * ((1 << bit) + offset)
                  for bit in (127, 128, 129, 255, 256, 511, 512)
                  for sign in (-1, 1) for offset in (-1, 0, 1)]
        self.compare("print(" + ",".join(map(str, values)) + ")\n", modes=("bigint",))

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_codepoint_indexing_does_not_require_property_tables(self):
        self.compare("s=input()\nprint(s[0], len(s))\n", inputs=("猫🐈é\n", "a\n"))

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_binary_integer_input_does_not_require_unicode_properties(self):
        source = "import sys\nprint(sum(map(int,sys.stdin.buffer.read().split())))\n"
        self.compare(source, inputs=("1 2 -3\n", "٤٢\n"))

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_class_byte_conversion_uses_the_ascii_parser(self):
        for literal in ("b'12_345'", "b'\\xa0'"):
            source = '''class Number:
    def __init__(self, data):
        self.value = int(data)
value = Number(''' + literal + ''')
print(value.value)
'''
            self.compare(source)

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_live_unicode_repr_and_numeric_parsing_preserve_data(self):
        source = '''class Texts:
    def __init__(self):
        self.values = ["猫", "\\u200b", "'", "\\x00"]
value = Texts()
print(value.values)
'''
        self.compare(source, require_tables=True)
        source = '''class Number:
    def __init__(self, value):
        self.value = value
value = Number(int(input()))
print(value.value * value.value)
'''
        self.compare(source, inputs=("٤٢\n", "\u2003123\u2003\n", "猫\u200b\n"),
                     require_tables=True)

    def compare(self, source, inputs=("",), modes=("i64", "i128", "bigint"),
                require_tables=False):
        expected = [subprocess.run([sys.executable, "-c", source], input=data,
                                  capture_output=True, text=True, timeout=10)
                    for data in inputs]
        with tempfile.TemporaryDirectory(prefix="pytors-unicode-dependencies-") as directory:
            root = Path(directory)
            for mode in modes:
                for optimize in (False, True):
                    result = transpile(source, TranspileOptions(integer=mode, optimize=optimize,
                                       string_mode="unicode", license="none"))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(bool(unicode_tables(result.rust_source)), require_tables)
                    self.assertEqual("// UNICODE LICENSE V3" in result.rust_source, require_tables)
                    path = root / "main.rs"
                    path.write_text(result.rust_source, encoding="utf-8")
                    for release in (False, True):
                        with self.subTest(integer=mode, optimize=optimize, release=release):
                            binary = root / "main"
                            build = subprocess.run(["rustc", "--edition=2021",
                                                    *(["-O"] if release else []), str(path),
                                                    "-o", str(binary)], capture_output=True,
                                                   text=True, timeout=120)
                            self.assertEqual(build.returncode, 0, build.stderr)
                            for data, reference in zip(inputs, expected):
                                actual = subprocess.run([str(binary)], input=data,
                                    capture_output=True, text=True, timeout=10,
                                    env={"PATH": "/unavailable", "PYTHONPATH": "/unavailable"})
                                self.assertEqual((actual.returncode, actual.stdout),
                                                 (reference.returncode, reference.stdout),
                                                 actual.stderr + reference.stderr)
                                if reference.returncode:
                                    self.assertEqual(actual.stderr.splitlines()[-1],
                                                     reference.stderr.splitlines()[-1])
