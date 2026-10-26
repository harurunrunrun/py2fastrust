"""Standalone byte construction and explicitly supported text codecs."""

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
class CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-codecs-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="codecs_wrapper.py"))
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

    def test_bytes_count_iterable_index_and_bytes_protocol(self):
        self.compare('''
            print(bytes(),bytes(0),bytes(3),bytes(False),bytes(True),bytes([0,1,127,128,255]),bytes(range(5)))
            print(bytes(source=(1,2,3)))
            class Index:
                def __index__(self):
                    print("index")
                    return 2
            class ByteMethod:
                def __bytes__(self):
                    print("bytes")
                    return b"method"
                def __index__(self):
                    print("wrong index")
                    return 7
            print(bytes(Index()),bytes(ByteMethod()),bytes([Index()]))
            class BadBytes:
                def __bytes__(self):
                    return "wrong"
            class BadIndex:
                def __index__(self):
                    return 1.5
            for value in [-1,1.5,None,[256],[-1],[1.0],BadBytes(),BadIndex()]:
                try: print(bytes(value))
                except TypeError: print("type")
                except ValueError: print("value")
            def values():
                print("first")
                yield 256
                print("second must not run")
                yield 1
            try: bytes(values())
            except ValueError: print("stopped")
        ''')

    def test_encoding_aliases_decoding_and_str_constructor(self):
        self.compare('''
            for encoding in ['utf8','utf_8','UTF 8','u8','cp65001']:
                value = "日本é🙂"
                encoded = bytes(value,encoding)
                print(encoded,encoded.decode(encoding),value.encode(encoding))
            for encoding in ['ascii','us-ascii','646','ANSI_X3.4_1968']:
                print(bytes('ascii',encoding),b'ascii'.decode(encoding))
            for encoding in ['latin1','latin_1','latin-1','iso8859-1','iso_8859_1','L1','cp819']:
                value = "éÿ"
                print(bytes(value,encoding),value.encode(encoding),b'\\xe9\\xff'.decode(encoding))
            print(bytes(source='日本',encoding='utf8'),bytes('日本',encoding='utf8',errors='strict'))
            print(str(b'\\xe9','latin1'),str(object=b'\\xe9',encoding='latin1'),str(b'abc',errors='replace'))
            print(str(),str(encoding='utf8'),str(errors='replace'),str(b'\\xff'))
            print('abc'.encode(errors='unknown'),b'abc'.decode(errors='unknown'))
            print('abc'.encode(encoding='ascii',errors='replace'),b'abc'.decode(encoding='ascii',errors='replace'))
            class Text(str):
                pass
            print('abc'.encode(Text('ascii')),b'abc'.decode(Text('ascii')))
        ''')

    def test_encode_errors_exception_fields_and_byte_ranges(self):
        self.compare('''
            for text in ['ASCII','éÿ','日本🙂','aé日本b','é日本']:
                for encoding in ['ascii','latin1','utf8']:
                    for errors in ['strict','ignore','replace','backslashreplace','xmlcharrefreplace']:
                        try: print(text.encode(encoding,errors))
                        except UnicodeEncodeError as error:
                            print(type(error).__name__,error.encoding,error.object,error.start,error.end,error.reason,error.args,str(error))
            for text,encoding in [('é','ascii'),('日本','latin1')]:
                try: text.encode(encoding,'unknown')
                except LookupError: print('lookup')
        ''')

    def test_invalid_utf8_and_ascii_error_spans(self):
        rng = random.Random(20261027)
        values = [bytes([value]) for value in range(256)]
        values += [b"a\xe1\x80b",b"\xed\xa0\x80",b"\xf0\x90\x80",b"\xe0\x80\x80",b"\xf4\x90\x80\x80",b"\xff\xfe",b"\xc2\x80",b"\xf0\x9f\x99\x82"]
        values += [bytes(rng.randrange(256) for _ in range(rng.randrange(1,9))) for _ in range(100)]
        self.compare(f"values={values!r}\n"+textwrap.dedent('''
            for value in values:
                for encoding in ['utf8','ascii','latin1']:
                    for errors in ['strict','ignore','replace','backslashreplace']:
                        try: print(repr(value.decode(encoding,errors)))
                        except UnicodeDecodeError as error:
                            print(type(error).__name__,error.encoding,error.object,error.start,error.end,error.reason,error.args,str(error))
        '''))

    def test_argument_validation_and_unknown_codecs(self):
        self.compare('''
            calls = [lambda:bytes('abc'),lambda:bytes(source='abc'),lambda:bytes(encoding='utf8'),lambda:bytes(errors='ignore'),lambda:bytes(3,errors='ignore'),lambda:bytes([1],encoding='ascii'),lambda:bytes('x',None),lambda:bytes('x','ascii',None),lambda:bytes(1,source=2),lambda:bytes('x','ascii',encoding='ascii'),lambda:bytes(1,2,3,4),lambda:bytes(bogus=1),lambda:'abc'.encode(None),lambda:b'abc'.decode(None),lambda:'abc'.encode(errors=None),lambda:b'abc'.decode(errors=None),lambda:'abc'.encode('ascii','strict','extra'),lambda:b'abc'.decode(encoding='ascii',bogus=1),lambda:str('abc','ascii'),lambda:str(object=b'a',encoding=None),lambda:str(b'a',object=b'b'),lambda:str(1,2,3,4)]
            for call in calls:
                try: print(call())
                except TypeError: print('type')
            for call in [lambda:'abc'.encode('unknown-codec'),lambda:b'abc'.decode('unknown-codec'),lambda:'é'.encode('ascii','unknown'),lambda:b'\\xff'.decode('utf8','unknown')]:
                try: print(call())
                except LookupError: print('lookup')
            for call in [lambda:'abc'.encode('\\0'),lambda:b'abc'.decode(errors='\\0')]:
                try: print(call())
                except ValueError: print('value')
            try: b'\\xff'.decode('utf8','xmlcharrefreplace')
            except TypeError: print('type')
        ''')

    def test_unsupported_buffers_codecs_and_error_handlers_are_explicit(self):
        source = '''
for call in [lambda:bytearray(),lambda:memoryview(b'a'),lambda:b'\\xff'.decode('utf8','surrogateescape'),lambda:'日本'.encode('ascii','namereplace')]:
    try: call()
    except NotImplementedError: print('unsupported')
for call in [lambda:'abc'.encode('utf16'),lambda:b'abc'.decode('utf16')]:
    try: call()
    except LookupError: print('unknown codec')
'''
        actual = subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=30)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,"unsupported\n"*4+"unknown codec\n"*2)


if __name__ == "__main__":
    unittest.main()
