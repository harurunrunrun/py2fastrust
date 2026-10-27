"""Differential tests for the std-only integer runtime, independent of the execution backend."""
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest


RUNTIME = Path(__file__).resolve().parents[1] / "py2fastrust/runtime/integer.rs"
HARNESS = r'''
fn main() {
    use std::io::{self, BufRead};
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let f: Vec<&str> = line.split('\t').collect();
        let run = || -> Result<String, String> {
            let op = f[0];
            if op == "parse" { return Int::parse(f[1], f[2].parse().unwrap()).map(|x| x.to_string()); }
            if op == "fromfloat" {
                return Int::from_f64(f64::from_bits(u64::from_str_radix(f[1], 16).unwrap())).map(|x| x.to_string());
            }
            if op == "roundfloat" {
                let value = f64::from_bits(u64::from_str_radix(f[1], 16).unwrap());
                return Int::round_float_decimal(value, &Int::parse(f[2], 10)?)
                    .map(|x| format!("{:016x}", x.to_bits()));
            }
            let a = Int::parse(f[1], 10)?;
            if op == "cmpfloat" {
                let value = f64::from_bits(u64::from_str_radix(f[2], 16).unwrap());
                return Ok(match a.cmp_f64(value) {
                    Some(std::cmp::Ordering::Less) => "-1",
                    Some(std::cmp::Ordering::Equal) => "0",
                    Some(std::cmp::Ordering::Greater) => "1",
                    None => "unordered",
                }.to_string());
            }
            if op == "float" { return Ok(format!("{:016x}", a.to_f64().to_bits())); }
            if op == "neg" { return Ok(a.neg().to_string()); }
            if op == "abs" { return Ok(a.abs().to_string()); }
            if op == "invert" { return Ok(a.invert().to_string()); }
            if op == "bits" { return Ok(format!("{},{}", a.bit_length(), a.bit_count())); }
            let b = Int::parse(f[2], 10)?;
            Ok(match op {
                "add" => a.add(&b).to_string(),
                "sub" => a.sub(&b).to_string(),
                "mul" => a.mul(&b).to_string(),
                "divmod" => { let (q, r) = a.divmod(&b)?; format!("{},{}", q, r) },
                "and" => a.bitand(&b).to_string(),
                "or" => a.bitor(&b).to_string(),
                "xor" => a.bitxor(&b).to_string(),
                "shl" => a.shl(&b)?.to_string(),
                "shr" => a.shr(&b)?.to_string(),
                "pow" => a.pow(&b)?.to_string(),
                "modpow" => a.modpow(&b, &Int::parse(f[3], 10)?)?.to_string(),
                "ratio" => format!("{:016x}", a.ratio(&b)?.to_bits()),
                "round" => a.round_decimal(&b).to_string(),
                "cmp" => (if a < b { -1 } else if a == b { 0 } else { 1 }).to_string(),
                _ => panic!("unknown operation"),
            })
        };
        match run() {
            Ok(result) => println!("{}", result),
            Err(error) => println!("ERR:{}", error.split(':').next().unwrap()),
        }
    }
}
'''


def wrap(n, bits):
    if not bits:
        return n
    n %= 1 << bits
    return n if n < 1 << (bits - 1) else n - (1 << bits)


def float_bits(value):
    return struct.pack(">d", value).hex()


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class IntegerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-integer-")
        cls.binaries = {}
        source = RUNTIME.read_text()
        for bits in (0, 64, 128):
            rs = Path(cls.tmp.name) / f"integer_{bits}.rs"
            rs.write_text(f"const INT_BITS: u32 = {bits};\n" + source + HARNESS)
            binary = rs.with_suffix("")
            subprocess.run(["rustc", "--edition=2021", "-O", "-A", "dead_code", str(rs), "-o", str(binary)], check=True, capture_output=True, text=True)
            cls.binaries[bits] = binary

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check_cases(self, bits, cases):
        commands, expected = zip(*cases)
        result = subprocess.run([str(self.binaries[bits])], input="\n".join(commands) + "\n", text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = result.stdout.splitlines()
        self.assertEqual(len(actual), len(expected), result.stderr)
        for command, want, got in zip(commands, expected, actual):
            self.assertEqual(got, str(want), f"int_bits={bits}; {command}")

    def test_arithmetic_and_bitwise(self):
        rng = random.Random(20261026)
        boundary = [0, 1, -1]
        for power in (1, 31, 32, 33, 63, 64, 65, 95, 127, 128, 129, 255, 256, 511):
            boundary += [sign * ((1 << power) + d) for sign in (-1, 1) for d in (-1, 0, 1)]
        pairs = [(a, b) for a in boundary for b in (-1, 0, 1, 2, -(1 << 63))]
        pairs += [(rng.getrandbits(rng.randrange(1, 1800)) * rng.choice((-1, 1)), rng.getrandbits(rng.randrange(1, 1600)) * rng.choice((-1, 1))) for _ in range(450)]
        for bits in (0, 64, 128):
            cases = []
            for x, y in pairs:
                a, b = wrap(x, bits), wrap(y, bits)
                for op, result in (("add", a + b), ("sub", a - b), ("mul", a * b), ("and", a & b), ("or", a | b), ("xor", a ^ b)):
                    cases.append((f"{op}\t{x}\t{y}", wrap(result, bits)))
                if b:
                    q, r = divmod(a, b)
                    expected = f"{wrap(q, bits)},{wrap(r, bits)}"
                else:
                    expected = "ERR:ZeroDivisionError"
                cases.append((f"divmod\t{x}\t{y}", expected))
                cases.append((f"cmp\t{x}\t{y}", (a > b) - (a < b)))
            for x in boundary:
                a = wrap(x, bits)
                cases += [(f"neg\t{x}", wrap(-a, bits)), (f"abs\t{x}", wrap(abs(a), bits)), (f"invert\t{x}", wrap(~a, bits)), (f"bits\t{x}", f"{a.bit_length()},{a.bit_count()}")]
            self.check_cases(bits, cases)

    def test_long_division_trial_correction(self):
        rng = random.Random(317032)
        cases = []
        for _ in range(1500):
            limbs = rng.randrange(2, 32)
            b = rng.getrandbits(limbs * 32 - rng.randrange(0, 32)) | 1
            q = rng.getrandbits(rng.randrange(0, 900))
            r = rng.randrange(b)
            a = q * b + r
            for sa, sb in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                quotient, remainder = divmod(a * sa, b * sb)
                cases.append((f"divmod\t{a * sa}\t{b * sb}", f"{quotient},{remainder}"))
        self.check_cases(0, cases)

    def test_decimal_rounding_uses_exact_integer_and_binary_float_values(self):
        rng = random.Random(673594)
        values = [0, 1, -1, 15, 25, 35, -15, -25, -35,
                  (1 << 63) - 1, -(1 << 63), (1 << 127) - 1,
                  10**400 + 12345, -(10**400 + 55555)]
        values += [rng.getrandbits(rng.randrange(1, 1800)) * rng.choice((-1, 1))
                   for _ in range(150)]
        floating = [0.0, -0.0, 2.675, -2.675, 1.005, 0.125, 0.375,
                    1.2345678901234567, 1.7976931348623157e308,
                    -1.7976931348623157e308, 5e-324, -5e-324,
                    float("inf"), -float("inf"), float("nan")]
        floating += [struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
                     for _ in range(350)]
        for bits in (0, 64, 128):
            cases = []
            for raw in values:
                number = wrap(raw, bits)
                for raw_digits in (-10**60, -600, -400, -100, -38, -19, -3, -2, -1,
                                   0, 1, 10**60):
                    digits = wrap(raw_digits, bits)
                    # CPython materializes 10**(-ndigits), even when its
                    # exponent is enormous. Use the mathematical zero here.
                    expected = 0 if digits < -10000 else round(number, digits)
                    cases.append((f"round\t{raw}\t{raw_digits}", wrap(expected, bits)))
            for number in floating:
                for raw_digits in (-10**60, -400, -309, -308, -25, -1, 0,
                                   1, 2, 15, 23, 307, 323, 324, 400, 10**60):
                    digits = wrap(raw_digits, bits)
                    try:
                        expected = float_bits(round(number, digits))
                    except OverflowError:
                        expected = "ERR:OverflowError"
                    cases.append((f"roundfloat\t{float_bits(number)}\t{raw_digits}", expected))
            self.check_cases(bits, cases)

    def test_shifts_and_powers(self):
        rng = random.Random(65535)
        for bits in (0, 64, 128):
            cases = []
            for _ in range(180):
                x = rng.getrandbits(rng.randrange(0, 600)) * rng.choice((-1, 1))
                shift = rng.choice((-1, 0, 1, 31, 32, 63, 64, 127, 128, 511, 1000))
                a = wrap(x, bits)
                for op, value in (("shl", a << max(shift, 0)), ("shr", a >> max(shift, 0))):
                    expected = "ERR:ValueError" if shift < 0 else wrap(value, bits)
                    cases.append((f"{op}\t{x}\t{shift}", expected))
            for base in (-100, -2, -1, 0, 1, 2, 100):
                for exponent in (0, 1, 2, 31, 64, 129):
                    cases.append((f"pow\t{base}\t{exponent}", wrap(pow(base, exponent), bits)))
            cases.extend([(f"shr\t-42\t{1 << 60}", -1), (f"shr\t42\t{1 << 60}", 0)])
            self.check_cases(bits, cases)

    def test_modular_power(self):
        rng = random.Random(19088743)
        for bits in (0, 64, 128):
            cases = []
            for _ in range(160):
                raw = (rng.getrandbits(180) * rng.choice((-1, 1)), rng.choice((-129, -31, -1, 0, 1, 2, 128)), rng.getrandbits(150) * rng.choice((-1, 1)))
                a, b, modulus = (wrap(x, bits) for x in raw)
                try:
                    expected = wrap(pow(a, b, modulus), bits)
                except ValueError:
                    expected = "ERR:ValueError"
                cases.append(("modpow\t" + "\t".join(map(str, raw)), expected))
            for modulus in (-1, 0, 1, -(1 << 63), -(1 << 127)):
                for base in (-2, -1, 0, 1, 2, 3):
                    for exponent in (-129, -1, 0, 129, -(1 << 127)):
                        a, b, m = (wrap(x, bits) for x in (base, exponent, modulus))
                        try:
                            expected = wrap(pow(a, b, m), bits)
                        except ValueError:
                            expected = "ERR:ValueError"
                        cases.append((f"modpow\t{base}\t{exponent}\t{modulus}", expected))
            self.check_cases(bits, cases)

    def test_parse(self):
        samples = [("0", 0), ("00", 0), ("0_0", 0), ("0x_FF", 0), ("-0b1_010", 0), ("+0o177", 0), ("123_456", 10), ("  -42  ", 10), ("１２３", 10), ("١٢٣", 10), ("ff", 16), ("zZ", 36), ("0x1", 16), ("０x_FF", 0), ("٠b١١", 0), ("０x1", 16)]
        invalid = [("", 0), ("010", 0), ("_1", 0), ("1_", 10), ("1__0", 10), ("0x__1", 0), ("0b2", 0), ("1.0", 10), ("1", 1), ("0x1", 10)]
        for bits in (0, 64, 128):
            cases = [(f"parse\t{s}\t{base}", wrap(int(s, base), bits)) for s, base in samples]
            cases += [(f"parse\t{s}\t{base}", "ERR:ValueError") for s, base in invalid]
            for power in (63, 64, 127, 128, 1000):
                for offset in (-1, 0, 1):
                    for sign in (-1, 1):
                        x = sign * ((1 << power) + offset)
                        cases.append((f"parse\t{x}\t10", wrap(x, bits)))
            self.check_cases(bits, cases)

    def test_exact_integer_float_comparisons(self):
        rng = random.Random(7654321)
        pairs = [(0, 0.0), (0, -0.0), (0, 0.5), (0, -0.5), (0, math.inf), (0, -math.inf), (0, math.nan), (0, float(1 << 64)), (0, float(1 << 128))]
        for power in (52, 53, 63, 64, 127, 128, 1023):
            for offset in (-1, 0, 1):
                pairs.append(((1 << power) + offset, float(1 << power)))
                pairs.append((-((1 << power) + offset), -float(1 << power)))
        pairs += [(rng.getrandbits(rng.randrange(0, 1300)) * rng.choice((-1, 1)), struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]) for _ in range(400)]
        for bits in (0, 64, 128):
            cases = []
            for raw, value in pairs:
                n = wrap(raw, bits)
                expected = "unordered" if math.isnan(value) else (n > value) - (n < value)
                cases.append((f"cmpfloat\t{raw}\t{float_bits(value)}", expected))
            self.check_cases(bits, cases)

    def test_float_conversions(self):
        rng = random.Random(4660)
        values = [0.0, -0.0, 1.0, -1.5, math.inf, -math.inf, math.nan, 1e100, -1e100, 1e308, 5e-324]
        values += [struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0] for _ in range(400)]
        integers = [0, 1, -1]
        for exponent in (52, 53, 54, 63, 127, 128, 1023, 1024, 2000):
            integers += [sign * ((1 << exponent) + offset) for offset in (-1, 0, 1) for sign in (-1, 1)]
        integers += [rng.getrandbits(rng.randrange(0, 1300)) * rng.choice((-1, 1)) for _ in range(200)]
        for bits in (0, 64, 128):
            cases = []
            for value in values:
                expected = "ERR:ValueError" if math.isnan(value) else "ERR:OverflowError" if math.isinf(value) else wrap(int(value), bits)
                cases.append((f"fromfloat\t{float_bits(value)}", expected))
            for raw in integers:
                n = wrap(raw, bits)
                try:
                    value = float(n)
                except OverflowError:
                    value = -math.inf if n < 0 else math.inf
                cases.append((f"float\t{raw}", float_bits(value)))
            self.check_cases(bits, cases)

    def test_integer_true_division_rounding(self):
        rng = random.Random(11259375)
        pairs = [(0, -1), (-(1 << 127), -1), (1 << 2000, 1 << 2000), ((1 << 1024) - (1 << 970), 1), (1, 1 << 1074), (1, 1 << 1075), (3, 1 << 1076), (3, 1 << 1075)]
        pairs += [(rng.getrandbits(rng.randrange(0, 2400)) * rng.choice((-1, 1)), rng.getrandbits(rng.randrange(0, 2400)) * rng.choice((-1, 1))) for _ in range(500)]
        # Adversarial half-way values exercise nearest-even and carry into exponent.
        pairs += [((1 << exponent) + offset, 1 << rng.randrange(0, 1200)) for exponent in (53, 54, 127, 1023, 1024) for offset in (-3, -1, 0, 1, 3)]
        for bits in (0, 64, 128):
            cases = []
            for x, y in pairs:
                a, b = wrap(x, bits), wrap(y, bits)
                try:
                    expected = float_bits(a / b)
                except OverflowError:
                    expected = "ERR:OverflowError"
                except ZeroDivisionError:
                    expected = "ERR:ZeroDivisionError"
                cases.append((f"ratio\t{x}\t{y}", expected))
            self.check_cases(bits, cases)


if __name__ == "__main__":
    unittest.main()
