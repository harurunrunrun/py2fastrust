"""Complete Unicode 16 NFKC data plus composition/ordering differential tests."""

from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
fn points(value:&str)->String{value.chars().map(|ch|format!("{:x}",ch as u32)).collect::<Vec<_>>().join(",")}
fn main(){
    use std::io::{self,BufRead};
    for line in io::stdin().lock().lines(){let line=line.unwrap();
        if line=="all-scalars" {
            for point in 0..=0x10ffff {if let Some(ch)=char::from_u32(point){
                let value=ch.to_string();let normalized=text_nfkc(&value);
                if value!=normalized{println!("{:x}\t{}",point,points(&normalized));}
            }}println!("DONE");
        }else{
            let input:String=line.split(',').filter(|s|!s.is_empty()).map(|s|char::from_u32(u32::from_str_radix(s,16).unwrap()).unwrap()).collect();
            println!("{}",points(&text_nfkc(&input)));
        }
    }
}
'''


def points(value):
    return ",".join(f"{ord(ch):x}" for ch in value)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="py2fastrust-normalization-")
        source = Path(cls.temporary.name) / "normalization.rs"
        source.write_text((ROOT / "py2fastrust/runtime/normalization.rs").read_text()
                          + (ROOT / "py2fastrust/runtime/normalization_tables.rs").read_text() + HARNESS)
        cls.binary = source.with_suffix("")
        result = subprocess.run(["rustc", "--edition=2021", "-O", str(source), "-o", str(cls.binary)],
                                text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_every_unicode_scalar(self):
        result = subprocess.run([str(self.binary)], input="all-scalars\n", capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = []
        for point in range(sys.maxunicode + 1):
            if 0xD800 <= point <= 0xDFFF:
                continue
            source = chr(point)
            normalized = unicodedata.normalize("NFKC", source)
            if source != normalized:
                expected.append(f"{point:x}\t{points(normalized)}")
        self.assertEqual(result.stdout.splitlines(), expected + ["DONE"])

    def test_composition_exclusions_hangul_and_canonical_order(self):
        rng = random.Random(345096)
        samples = ["", "ascii_identifier", "𝒾𝒻", "ａｎｎｏｔａｔｉｏｎｓ", "K", "ﬃ",
                   "A\u030a\u0301", "\u0301\u0327a", "a\u0301\u0327", "\u0344",
                   "\u1100\u1161\u11a8", "\uac00\u11a8"]
        combining = [chr(point) for point in range(0x110000) if unicodedata.combining(chr(point))]
        decomposable = [chr(point) for point in range(0x110000)
                        if not 0xD800 <= point <= 0xDFFF and unicodedata.decomposition(chr(point))]
        for _ in range(4000):
            source = rng.choice(decomposable) + "".join(rng.choices(combining, k=rng.randrange(1, 12)))
            samples.extend([source, unicodedata.normalize("NFKD", source)])
        samples += ["a" + "".join(sorted(combining, key=unicodedata.combining, reverse=True)) * 10]
        data = "\n".join(map(points, samples)) + "\n"
        result = subprocess.run([str(self.binary)], input=data, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [points(unicodedata.normalize("NFKC", value)) for value in samples])

    def test_tables_are_reproducible(self):
        subprocess.run([sys.executable, "tools/generate_normalization.py", "--check"],
                       cwd=ROOT, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
