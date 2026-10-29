"""Bytes integer grammar is ASCII; text parsing keeps its Unicode provider."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_unicode_tables import unicode_tables

RUNTIME = Path(__file__).resolve().parents[1] / "py2fastrust/runtime/integer.rs"
HARNESS = r"""
fn main(){use std::io::Read;let mut input=String::new();std::io::stdin().read_to_string(&mut input).unwrap();
for line in input.lines(){let fields=line.split('|').collect::<Vec<_>>();let bytes=fields[2].as_bytes().chunks(2).map(|pair|u8::from_str_radix(std::str::from_utf8(pair).unwrap(),16).unwrap()).collect::<Vec<_>>();let base=fields[1].parse().unwrap();let value=if fields[0]=="bytes"{Int::parse_ascii(&bytes,base)}else{Int::parse(std::str::from_utf8(&bytes).unwrap(),base)};match value{Ok(value)=>println!("{}",value),Err(_)=>println!("ERR")}}}
"""


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeAsciiIntegerBytesTests(unittest.TestCase):
    def test_shared_parser_preserves_bytes_and_unicode_grammar(self):
        cases = [("bytes", bytes([byte]), 10) for byte in range(256)]
        for value in (b"", b" ", b"+", b"-", b"0", b"00", b"01", b"0_0", b"0_1",
                      b"0x", b"0x10", b"0x_10", b"0x__10", b"0X_Ff", b"0b_11",
                      b"0o_77", b"0_0_0", b"_1", b"1_", b"1__2", b"1_2",
                      b" +1_234\v", b"\x1c1", b"1\x1f", b"\xa01", b"1\x7f", b"-"+b"9"*300):
            cases.extend(("bytes", value, base) for base in (0, 1, 2, 8, 10, 16, 36, 37))
        for value in ("٤٢", "\u2003٤٢\u2003", "٠x_Ff", "٠٠", "٠١", "\x1c1", "１_２３",
                      "-१२३", "\u00a01\u00a0", "𝟘𝟘", "𝟘𝟙", "١٢a", "٢_３"):
            cases.extend(("text", value.encode(), base) for base in (0, 2, 10, 16, 36))
        expected = []
        for kind, value, base in cases:
            try: expected.append(str(int(value if kind == "bytes" else value.decode(), base)))
            except ValueError: expected.append("ERR")
        data = "".join(f"{kind}|{base}|{value.hex()}\n" for kind, value, base in cases)
        with tempfile.TemporaryDirectory(prefix="pytors-ascii-parser-") as directory:
            source = Path(directory) / "parser.rs"
            source.write_text("const INT_BITS:u32=0;\n" + RUNTIME.read_text() + HARNESS)
            for release in (False, True):
                binary = Path(directory) / ("release" if release else "debug")
                built = subprocess.run(["rustc", "--edition=2021", "-A", "dead_code",
                                        *(["-O"] if release else []), str(source), "-o", str(binary)],
                                       capture_output=True, text=True, timeout=120)
                self.assertEqual(built.returncode, 0, built.stderr)
                actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=20)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(actual.stdout.splitlines(), expected)

    def test_direct_bytes_conversion_preserves_error_repr_without_unicode_tables(self):
        self.compare("import sys\nprint(int(sys.stdin.buffer.read()))\n")

    def test_class_bytes_conversion_preserves_error_repr_without_unicode_tables(self):
        self.compare("import sys\nclass Number:\n def __init__(self,value):self.value=value\n"
                     "value=Number(int(sys.stdin.buffer.read()))\nprint(value.value)\n")

    def compare(self, source):
        inputs = (b"42\n", b" \t\v\f\r\n-1_234 \t\n", "٤٢\n".encode(), b"\xff", b"1\x1c", b"")
        expected = [subprocess.run([sys.executable, "-I", "-S", "-c", source], input=data,
                                  capture_output=True, timeout=10) for data in inputs]
        with tempfile.TemporaryDirectory(prefix="pytors-ascii-bytes-") as directory:
            for integer in ("i64", "i128", "bigint"):
                for optimize in (False, True):
                    result = transpile(source, TranspileOptions(integer=integer, optimize=optimize,
                                           string_mode="unicode", license="none"))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    self.assertEqual(unicode_tables(result.rust_source), ())
                    self.assertNotIn("UNICODE LICENSE V3", result.rust_source)
                    rust = Path(directory) / "main.rs"
                    rust.write_text(result.rust_source)
                    for release in (False, True):
                        binary = Path(directory) / "main"
                        built = subprocess.run(["rustc", "--edition=2021", *(["-O"] if release else []),
                                                str(rust), "-o", str(binary)], capture_output=True,
                                               text=True, timeout=120)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        for data, reference in zip(inputs, expected):
                            with self.subTest(integer=integer,optimize=optimize,release=release,input=data):
                                actual = subprocess.run([str(binary)], input=data, capture_output=True,
                                                        timeout=10, env={"PATH":"/no-python-runtime"})
                                self.assertEqual((actual.returncode, actual.stdout),
                                                 (reference.returncode, reference.stdout), actual.stderr)
                                if reference.returncode:
                                    self.assertEqual(actual.stderr.splitlines()[-1],reference.stderr.splitlines()[-1])
                                else: self.assertEqual(actual.stderr,b"")


if __name__ == "__main__": unittest.main()
