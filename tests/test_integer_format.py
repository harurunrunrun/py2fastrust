"""Integer presentation and arbitrary precision radix conversion versus CPython."""

from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

import test_runtime
from test_integer import wrap


RUNTIME = Path(__file__).resolve().parents[1] / "py2fastrust/runtime/integer.rs"
HARNESS = r'''
fn main() {
    use std::io::{self, BufRead};
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let fields: Vec<&str> = line.split('\t').collect();
        let value = Int::parse(fields[1], 10).unwrap();
        let result = if fields[0] == "radix" {
            Ok(Some(value.radix(fields[2].parse().unwrap(), fields[3] == "1")))
        } else {
            value.format_integer(fields[2])
        };
        match result {
            Ok(Some(text)) => println!("{}", text.bytes().map(|b| format!("{:02x}", b)).collect::<String>()),
            Ok(None) => println!("DELEGATE"),
            Err(error) => println!("ERR:{}", error.split(':').next().unwrap()),
        }
    }
}
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class IntegerFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-integer-format-")
        cls.binaries = {}
        for bits in (0, 64, 128):
            path = Path(cls.tmp.name) / f"format_{bits}.rs"
            path.write_text(f"const INT_BITS:u32={bits};\n" + RUNTIME.read_text() + HARNESS)
            binary = path.with_suffix("")
            result = subprocess.run(["rustc", "--edition=2021", "-O", "-A", "dead_code", str(path), "-o", str(binary)], capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.binaries[bits] = binary

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check_cases(self, bits, commands):
        lines, expected = [], []
        for operation, value, spec in commands:
            lines.append(f"{operation}\t{value}\t{spec}")
            n = wrap(value, bits)
            try:
                if operation == "radix":
                    base, upper = spec.split("\t")
                    text = format(n, {"2": "b", "8": "o", "16": "X" if upper == "1" else "x"}[base])
                else:
                    text = format(n, spec)
                expected.append(text.encode().hex())
            except Exception as error:
                expected.append("ERR:" + type(error).__name__)
        result = subprocess.run([str(self.binaries[bits])], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = result.stdout.splitlines()
        self.assertEqual(len(actual), len(expected))
        for case, got, want in zip(commands, actual, expected):
            self.assertEqual(got, want, (bits, case, bytes.fromhex(got) if not got.startswith("ERR:") and got != "DELEGATE" else got))

    def test_radix_boundaries_and_random_limbs(self):
        rng = random.Random(1746)
        values = [0, 1, -1]
        for power in (1, 31, 32, 33, 63, 64, 65, 95, 127, 128, 129, 200, 255, 256, 511, 1024, 4096):
            values += [sign * ((1 << power) + delta) for sign in (-1, 1) for delta in (-1, 0, 1)]
        values += [rng.getrandbits(rng.randrange(1, 6000)) * rng.choice((-1, 1)) for _ in range(100)]
        for bits in (0, 64, 128):
            self.check_cases(bits, [("radix", n, f"{base}\t{upper}") for n in values for base in (2, 8, 16) for upper in (0, 1)])

    def test_integer_specifications(self):
        rng = random.Random(74165)
        values = [0, 1, -1, 65, -65, 1234, -1234, 2**63, -(2**63), 2**127, -(2**127), 2**200 + 12345, -(2**200 + 12345), 2**1024]
        specs = ["", "d", "b", "o", "x", "X", "n", "+", " ", "#", "#X", "#,d", "_", "_x", ",d", "020,d", "#020_x", "0=020_x", "0>020_x", ">020_x", "*>020_x", "💠^90d", "=90d", "-^90x", "{>90d", "0<90d", "٠٩٠d", "９０d"]
        commands = [("format", n, spec) for n in values for spec in specs]
        for _ in range(500):
            n = rng.choice(values) if rng.randrange(2) else rng.getrandbits(rng.randrange(0, 1300)) * rng.choice((-1, 1))
            kind = rng.choice("bdoxXn")
            grouping = rng.choice(["", "_"] + ([","] if kind == "d" else [])) if kind != "n" else ""
            spec = rng.choice(["", "<", ">", "=", "^", "0=", "*>", "💠^"])
            spec += rng.choice(["", "+", "-", " "]) + rng.choice(["", "#"]) + rng.choice(["", "0"])
            spec += str(rng.randrange(0, 130)) + grouping + kind
            commands.append(("format", n, spec))
        for bits in (0, 64, 128):
            self.check_cases(bits, commands)

    def test_character_and_invalid_specifications(self):
        commands = [("format", value, spec) for value in (0, 65, 0x20ac, 0x1f600, 0x10ffff, -1, 0x110000, 2**200)
                    for spec in ("c", "8c", "05c", "💠^8c", "-c", "+c", "#c", "_c", ",c")]
        commands += [("format", 123, spec) for spec in ("s", "a", "q", "#s", "-z", "z", "zd", ".0d", ".5x", ".d", "..d", ",_d", "_,d", "_,", "__d", "#_n", ",x", "_,x", "#++d", "12dd", "99999999999999999999999999999d")]
        for bits in (0, 64, 128):
            self.check_cases(bits, commands)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class IntegerFormatIntegrationTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_bigint_builtins_and_format_routes(self):
        self.run_source('''
            for n in [0, 65, -65, 2**200 + 12345, -(2**200 + 12345)]:
                print(bin(n), oct(n), hex(n))
                for spec in ['', 'd', '#x', '#X', '020_x', '+#090x', '💠^90d', ',d']:
                    print(format(n, spec), n.__format__(spec), '{:#x}'.format(n))
                print(f'{n:#x}', f'{n:090,d}')
            for n in [2**63-1, -2**63]:
                print(bin(n), oct(n), hex(n), format(n, '#070x'))
            class Index:
                def __index__(self): return 2**200
            print(bin(Index()), oct(Index()), hex(Index()))
        ''', integer="bigint")


if __name__ == "__main__":
    unittest.main()
