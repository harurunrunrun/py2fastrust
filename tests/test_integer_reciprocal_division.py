"""Large exact division across normalized reciprocal and block boundaries."""
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

RUNTIME = Path(__file__).resolve().parents[1] / 'py2fastrust/runtime/integer.rs'
HARNESS = r'''
fn main() {
    use std::io::{self, BufRead};
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let fields: Vec<&str> = line.split('\t').collect();
        let a = Int::parse_ascii(fields[1].as_bytes(), 16).unwrap();
        if fields[0] == "inverse" {
            let words = a.magnitude();
            let normalized = Int::nat_shl(&words, words.last().unwrap().leading_zeros() as usize);
            println!("{}", Int::exact_parts(false, Int::nat_reciprocal(&normalized)).radix(16, false));
            continue;
        }
        let b = Int::parse_ascii(fields[2].as_bytes(), 16).unwrap();
        if fields[0].starts_with("mutate") {
            let mut target = if fields[0] == "mutate_unique" {
                Int::exact_parts(false, b.magnitude().into_owned())
            } else { b.clone() };
            for _ in 0..3 { let _ = a.divmod(&target).unwrap(); }
            assert_eq!(target, b);
            if let (IntRepr::Big { digits: x, .. }, IntRepr::Big { digits: y, .. }) = (&target.0, &b.0) {
                use std::hash::{Hash, Hasher};
                let (mut first, mut second) = (std::collections::hash_map::DefaultHasher::new(), std::collections::hash_map::DefaultHasher::new());
                x.hash(&mut first); y.hash(&mut second); assert_eq!(first.finish(), second.finish());
            }
            let mask = Int::parse_ascii(fields[3].as_bytes(), 16).unwrap();
            target.bitop_assign(&mask, fields[4].parse().unwrap());
            let (q, r) = a.divmod(&target).unwrap();
            println!("{}\t{}\t{}\t{}", b.radix(16, false), target.radix(16, false), q.radix(16, false), r.radix(16, false));
            continue;
        }
        let first_remainder = if fields[0] == "mod_first" { Some(a.modulo(&b).unwrap()) } else { None };
        let (q, r) = a.divmod(&b).unwrap();
        let remainder = match first_remainder { Some(value) => value, None => a.modulo(&b).unwrap() };
        let (hot_q, hot_r) = a.divmod(&b).unwrap();
        assert_eq!(q, hot_q); assert_eq!(r, hot_r);
        println!("{}\t{}\t{}", q.radix(16, false), r.radix(16, false), remainder.radix(16, false));
    }
}
'''


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ReciprocalDivisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='pytors-reciprocal-')
        cls.binaries = {}
        path = Path(cls.tmp.name) / 'reciprocal.rs'
        path.write_text('const INT_BITS:u32=0;\n' + RUNTIME.read_text() + HARNESS)
        for optimized in (False, True):
            binary = Path(cls.tmp.name) / ('release' if optimized else 'debug')
            result = subprocess.run(['rustc', '--edition=2021', '-A', 'dead_code',
                                     *(['-O'] if optimized else []), str(path), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.binaries[optimized] = binary

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, rows, optimized):
        commands, expected = zip(*rows)
        result = subprocess.run([str(self.binaries[optimized])], input='\n'.join(commands) + '\n',
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = result.stdout.splitlines()
        self.assertEqual(len(actual), len(expected), result.stderr)
        for index, (want, got) in enumerate(zip(expected, actual)):
            self.assertEqual(got, want, f'row={index}; optimized={optimized}')

    def test_normalized_integer_reciprocals(self):
        rng = random.Random(2026111701)
        rows = []
        for words in (1, 2, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255, 256, 257, 511, 512, 513, 1024):
            for top_bits in (1, 16, 31, 32):
                bits = (words - 1) * 32 + top_bits
                for value in (1 << (bits - 1), (1 << bits) - 1, rng.getrandbits(bits - 1) | (1 << (bits - 1))):
                    shift = (-value.bit_length()) % 32
                    want = (1 << (64 * words)) // (value << shift)
                    rows.append((f'inverse\t{value:x}', format(want, 'x')))
        for optimized in (False, True):
            self.check(rows if optimized else rows[::7], optimized)

    def test_quotient_blocks_remainders_and_signs(self):
        rng = random.Random(2026111702)
        rows = []
        for words in (255, 256, 257, 511, 512, 513, 1023, 1024, 1025):
            for top_bits in (1, 16, 31, 32):
                size = (words - 1) * 32 + top_bits
                divisor = rng.getrandbits(size - 1) | (1 << (size - 1))
                for quotient_words in (127, 128, 129, words - 1, words, words + 1, 2 * words, 2 * words + 1):
                    quotient = rng.getrandbits(quotient_words * 32) | 1
                    remainder = rng.choice((0, 1, divisor - 1, rng.randrange(divisor)))
                    dividend = quotient * divisor + remainder
                    for sa, sb in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                        a, b = sa * dividend, sb * divisor
                        q, r = divmod(a, b)
                        rows.append((f'pair\t{a:x}\t{b:x}', f'{q:x}\t{r:x}\t{r:x}'))
        # Sparse values expose leading quotient blocks and fixed zero padding.
        for words in (256, 257, 512, 513, 1024):
            for divisor in (1 << (words * 32 - 1), (1 << (words * 32)) - 1):
                for quotient in (1, (1 << (32 * words)) - 1, 1 << (64 * words)):
                    for remainder in (0, 1, divisor - 1):
                        value = quotient * divisor + remainder
                        rows.append((f'pair\t{value:x}\t{divisor:x}', f'{quotient:x}\t{remainder:x}\t{remainder:x}'))
        self.check(rows, True)
        self.check(rows[::79], False)

    def test_reciprocals_do_not_affect_value_hash_or_survive_mutation(self):
        rng = random.Random(2026111704)
        rows = []
        for words in (256, 257, 512, 513, 1024):
            bits = words * 32
            b = rng.getrandbits(bits - 1) | (1 << (bits - 1)) | 1
            a = rng.getrandbits(bits * 2) | (1 << (bits * 2))
            for mask in (1, (1 << (bits - 1)), 1 << bits, (1 << bits) - 1):
                for op, target in ((0, b & mask), (1, b | mask), (2, b ^ mask)):
                    if not target: continue
                    q, r = divmod(a, target)
                    for name in ('mutate_shared', 'mutate_unique'):
                        rows.append((f'{name}\t{a:x}\t{b:x}\t{mask:x}\t{op}', f'{b:x}\t{target:x}\t{q:x}\t{r:x}'))
        self.check(rows, True)
        self.check(rows[::17], False)

    def test_large_first_divisions_and_unbalanced_blocks(self):
        rng = random.Random(2026111705)
        rows = []
        for words in (2047, 2048, 2049, 4096, 4097, 8192):
            for leading_bits in (1, 32):
                bits = (words - 1) * 32 + leading_bits
                b = rng.getrandbits(bits - 1) | (1 << (bits - 1))
                for quotient_words in (words - 1, words + 1, words * 3):
                    q = rng.getrandbits(quotient_words * 32) | 1
                    r = rng.randrange(b)
                    a = b * q + r
                    for first, second in ((a, b), (-a, -b)):
                        quotient, remainder = divmod(first, second)
                        rows.append((f'pair\t{first:x}\t{second:x}', f'{quotient:x}\t{remainder:x}\t{remainder:x}'))
        self.check(rows, True)
        self.check(rows[::13], False)

    def test_short_quotient_prefixes_and_one_high_estimates(self):
        rng = random.Random(2026111803)
        rows = []
        for words in (2047, 2048, 2049, 4096, 8192):
            for extra in (127, 128, 129, words // 4, words // 2 - 3,
                          words // 2 - 2, words // 2 - 1, words // 2):
                for top_bits in (1, 32):
                    bits = (words - 1) * 32 + top_bits
                    divisor = rng.getrandbits(bits - 1) | (1 << (bits - 1)) | 1
                    value = rng.getrandbits((words + extra) * 32 - 1) | (1 << ((words + extra) * 32 - 1))
                    for sa, sb in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                        x, y = sa * value, sb * divisor
                        q, r = divmod(x, y)
                        for name in ('pair', 'mod_first'):
                            rows.append((f'{name}\t{x:x}\t{y:x}', f'{q:x}\t{r:x}\t{r:x}'))
            # A zero low numerator prefix and a nonzero low divisor make the
            # initial quotient exactly one too high. Decrement crosses zeros.
            for extra in (128, words // 2 - 2):
                b = (1 << ((words - 1) * 32)) + 1
                q = (1 << (extra * 32)) - 1
                for r in (0, 1, b - 1):
                    a = q * b + r
                    for name in ('pair', 'mod_first'):
                        rows.append((f'{name}\t{a:x}\t{b:x}', f'{q:x}\t{r:x}\t{r:x}'))
        self.check(rows, True)
        self.check(rows[::83], False)
