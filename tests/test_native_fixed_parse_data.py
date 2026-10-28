"""Independent exhaustive CPython decimal/whitespace oracles for fixed parsers."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest

from py2fastrust.native_integer_parsing import render_helpers

SEED=1469598103934665603;PRIME=1099511628211;MASK=(1<<64)-1


def mark(value):return 0x9e3779b97f4a7c15 if value is None else ((value*131)+1)&MASK


def update(state,value):return ((state^mark(value))*PRIME)&MASK


def parse(text):
    try:return int(text)
    except ValueError:return None


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeFixedParseDataTests(unittest.TestCase):
    def execute(self,body,bits=64):
        source=f'#![allow(dead_code)]\ntype NativeInt=i{bits};\n'+render_helpers("unicode")+f'''
fn step(state:u64,value:Option<NativeInt>)->u64{{
 let value=match value{{None=>0x9e3779b97f4a7c15_u64,Some(value)=>(value as u64).wrapping_mul(131).wrapping_add(1)}};
 (state^value).wrapping_mul({PRIME}_u64)
}}
'''+body
        with tempfile.TemporaryDirectory(prefix='pytors-fixed-parse-data-')as directory:
            path=Path(directory,'data.rs');path.write_text(source);binary=path.with_suffix('')
            built=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary)],text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr);return int(result.stdout)

    @unittest.skipUnless(sys.implementation.name=='cpython'and sys.version_info[:2]==(3,14)and unicodedata.unidata_version=='16.0.0','pinned CPython Unicode16 oracle is required')
    def test_every_unicode_scalar_decimal_and_trailing_whitespace(self):
        expected=SEED
        for code in range(0x110000):
            if 0xd800<=code<=0xdfff:continue
            char=chr(code);single=parse(char)
            expected=update(update(update(expected,single),single),parse('1'+char))
        body=f'''
fn main(){{
 let mut state={SEED}_u64;
 for code in 0..=0x10ffff_u32{{
  if let Some(character)=char::from_u32(code){{
   let mut buffer=[0_u8;8];buffer[0]=b'1';
   let length=character.encode_utf8(&mut buffer[1..5]).len();
   state=step(state,native_parse_integer(std::str::from_utf8(&buffer[1..1+length]).unwrap()).ok());
   state=step(state,native_parse_integer_codepoint(code).ok());
   state=step(state,native_parse_integer(std::str::from_utf8(&buffer[..1+length]).unwrap()).ok());
  }}
 }}
 println!("{{}}",state);
}}
'''
        for bits in (64,128):
            with self.subTest(bits=bits):self.assertEqual(self.execute(body,bits),expected)

    def test_every_byte_and_pair_sign_digit_and_whitespace_rules(self):
        expected=update(SEED,parse(b''))
        for byte in range(256):expected=update(expected,parse(bytes([byte])))
        for a in range(256):
            for b in range(256):expected=update(expected,parse(bytes([a,b])))
        body=f'''
fn main(){{
 let mut state=step({SEED}_u64,native_fixed_parse_ascii(&[]));
 for byte in 0..=255_u8{{state=step(state,native_fixed_parse_ascii(&[byte]));}}
 for a in 0..=255_u8{{for b in 0..=255_u8{{state=step(state,native_fixed_parse_ascii(&[a,b]));}}}}
 println!("{{}}",state);
}}
'''
        for bits in (64,128):
            with self.subTest(bits=bits):self.assertEqual(self.execute(body,bits),expected)


if __name__=='__main__':unittest.main()
