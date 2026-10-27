"""Decoded string subclasses use the same codec and buffer rules as str."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
import test_codecs as codec_tests


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StrSubclassDecodingTests(unittest.TestCase):
    setUpClass = classmethod(codec_tests.CodecTests.setUpClass.__func__)
    tearDownClass = classmethod(codec_tests.CodecTests.tearDownClass.__func__)
    compare = codec_tests.CodecTests.compare

    def test_native_new_and_inherited_constructors_decode_buffers(self):
        self.compare(r'''
            class Text(str):
                pass
            class Child(Text):
                pass
            class Bytes(bytes):
                pass
            for cls in [Text, Child]:
                for value in [b'caf\xe9', Bytes(b'caf\xe9'), bytearray(b'caf\xe9'), memoryview(b'caf\xe9')]:
                    item = cls(value, 'latin1')
                    print(type(item).__name__, repr(item), item.upper(), isinstance(item, str))
                print(repr(cls(object=b'\xffx', encoding='ascii', errors='replace')))
                print(repr(str.__new__(cls, b'\xffx', errors='ignore')))
                print(repr(cls(encoding='utf8')), repr(cls(errors='replace')))
            item = str.__new__(Text, 'value')
            print(type(item).__name__, str.__new__(Text, item) is item)
            class Custom(Text):
                def __init__(self, *args, **kwargs):
                    print('init', len(args), sorted(kwargs))
                    self.marker = 7
            value = Custom(b'hello', encoding='ascii')
            print(value, value.marker)
        ''')

    def test_decode_failures_and_constructor_binding(self):
        self.compare(r'''
            class Text(str):
                pass
            calls = [
                lambda: Text(b'\xff', 'ascii'),
                lambda: Text(b'x', 'missing-encoding'),
                lambda: Text(b'x', 7),
                lambda: Text(b'x', 'ascii', 7),
                lambda: Text(b'x', 'ascii', 'strict', None),
                lambda: Text(b'x', object=b'y'),
                lambda: Text(b'x', 'ascii', encoding='utf8'),
                lambda: Text(b'x', invalid=1),
                lambda: Text('x', 'ascii'),
                lambda: Text(memoryview(b'abcdef')[::2], 'ascii'),
                lambda: str.__new__(int, b'x', 'ascii'),
            ]
            for call in calls:
                try:
                    call()
                except Exception as error:
                    print(type(error).__name__)
            print(Text(b'\xffx', 'ascii', 'backslashreplace'))
        ''')

    def test_python_buffer_callbacks_and_overridden_string_conversion(self):
        self.compare(r'''
            import gc
            class Text(str):
                pass
            class Provider:
                def __buffer__(self, flags):
                    print('buffer', flags)
                    gc.collect()
                    return memoryview(b'caf\xe9')
                def __release_buffer__(self, view):
                    print('release', bytes(view))
                    gc.collect()
            print(Text(Provider(), 'latin1'))
            class Source(str):
                def __str__(self):
                    print('str callback')
                    gc.collect()
                    return Text('changed')
            item = Text(Source('original'))
            print(type(item).__name__, repr(item))
        ''')

    def test_all_integer_modes_debug_release_standalone(self):
        source = """class Text(str):
 pass
value = Text(memoryview(bytes([99, 97, 102, 233])), 'latin1')
value.note = 'decoded'
print(type(value).__name__, repr(value), value.note, value.upper())
print(Text(bytearray([255, 120]), encoding='ascii', errors='backslashreplace'))
try:
 Text(bytes([255]), 'ascii')
except UnicodeDecodeError as error:
 print(error.encoding, error.start, error.end, error.reason)
"""
        expected = subprocess.run([sys.executable, "-I", "-c", source],
                                  capture_output=True, text=True, check=True).stdout
        with tempfile.TemporaryDirectory(prefix="pytors-str-decode-profiles-") as directory:
            root = Path(directory)
            for integer in ("i64", "i128", "bigint"):
                for optimized in (False, True):
                    with self.subTest(integer=integer, optimized=optimized):
                        result = transpile(source, TranspileOptions(integer=integer, filename="main.py"))
                        self.assertTrue(result.success, result.diagnostics)
                        rust = root / "main.rs"
                        rust.write_text(result.rust_source)
                        binary = root / "main"
                        command = ["rustc", "--edition=2021", str(rust), "-o", str(binary)]
                        if optimized:
                            command.append("-O")
                        compiled = subprocess.run(command, capture_output=True, text=True, timeout=120)
                        self.assertEqual(compiled.returncode, 0, compiled.stderr)
                        executed = subprocess.run([str(binary)], capture_output=True, text=True,
                                                  timeout=30, env={"PATH": "/nonexistent"})
                        self.assertEqual(executed.returncode, 0, executed.stderr)
                        self.assertEqual(executed.stdout, expected)


if __name__ == "__main__":
    unittest.main()
