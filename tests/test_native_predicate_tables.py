"""Exhaustive independent CPython oracles for pinned codepoint/byte helpers."""
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest

from py2fastrust.native_text_predicates import STR_PREDICATES,BYTES_PREDICATES,render_helpers

MASK=(1<<64)-1
SEED=1469598103934665603
PRIME=1099511628211


def update(state,key,bits):return ((state^((key<<16)|bits))*PRIME)&MASK


class PinnedPredicateDataTests(unittest.TestCase):
    @unittest.skipUnless(sys.version_info[:2]==(3,14) and unicodedata.unidata_version=='16.0.0','pinned CPython Unicode 16 generator is required')
    def test_titlecase_table_matches_its_pinned_generator(self):
        root=Path(__file__).resolve().parents[1]
        generate=runpy.run_path(str(root/'tools/generate_native_titlecase.py'))['generate']
        self.assertEqual((root/'py2fastrust/runtime/native_titlecase_16.rs').read_text(),generate())


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativePredicateTableTests(unittest.TestCase):
    def run_rust(self,source):
        with tempfile.TemporaryDirectory(prefix='pytors-predicate-data-') as directory:
            path=Path(directory,'main.rs');path.write_text('#![allow(dead_code,unused_parens)]\n'+source)
            binary=path.with_suffix('')
            built=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(actual.returncode,0,actual.stderr)
            return int(actual.stdout)

    @unittest.skipUnless(sys.version_info[:2]==(3,14) and unicodedata.unidata_version=='16.0.0','CPython Unicode 16 oracle is required')
    def test_every_unicode_scalar_codepoint_matches_cpython(self):
        names=tuple(sorted(STR_PREDICATES))
        helpers=render_helpers({('str',name,True) for name in names},'unicode')
        bits='|'.join(f'((native_str_{name}_code(code) as u64)<<{index})' for index,name in enumerate(names))
        rust=helpers+f'''
fn main() {{
 let mut state={SEED}_u64;
 for code in 0..=0x10ffff_u32 {{
  if (0xd800..=0xdfff).contains(&code){{continue;}}
  let bits={bits};
  state=(state^(((code as u64)<<16)|bits)).wrapping_mul({PRIME}_u64);
 }}
 println!("{{}}",state);
}}
'''
        expected=SEED
        methods=[getattr(str,name) for name in names]
        for code in range(0x110000):
            if 0xd800<=code<=0xdfff:continue
            value=chr(code);flags=sum(method(value)<<index for index,method in enumerate(methods))
            expected=update(expected,code,flags)
        self.assertEqual(self.run_rust(rust),expected)

    def test_every_byte_and_pair_matches_cpython(self):
        names=tuple(sorted(BYTES_PREDICATES));helpers=render_helpers({('bytes',name,False)for name in names},'unicode')
        bits='|'.join(f'((native_bytes_{name}(value) as u64)<<{index})'for index,name in enumerate(names))
        rust=helpers+f'''
fn mask(value:&[u8])->u64{{{bits}}}
fn step(state:u64,key:u64,value:&[u8])->u64{{(state^((key<<16)|mask(value))).wrapping_mul({PRIME}_u64)}}
fn main() {{
 let mut state=step({SEED}_u64,65536,&[]);
 for a in 0..=255_u8{{state=step(state,65793+a as u64,&[a]);}}
 for a in 0..=255_u8{{for b in 0..=255_u8{{state=step(state,(a as u64)*256+b as u64,&[a,b]);}}}}
 println!("{{}}",state);
}}
'''
        methods=[getattr(bytes,name)for name in names]
        def flags(value):return sum(method(value)<<index for index,method in enumerate(methods))
        expected=update(SEED,65536,flags(b''))
        for a in range(256):expected=update(expected,65793+a,flags(bytes([a])))
        for a in range(256):
            for b in range(256):expected=update(expected,a*256+b,flags(bytes([a,b])))
        self.assertEqual(self.run_rust(rust),expected)


if __name__=='__main__':unittest.main()
