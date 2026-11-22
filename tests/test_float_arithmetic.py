"""Float floor/mod/divmod agree with CPython at binary64 boundaries."""

import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
import test_runtime


def bits(value):
    return struct.unpack('>Q',struct.pack('>d',value))[0]


def number(bit_pattern):
    return struct.unpack('>d',struct.pack('>Q',bit_pattern))[0]


def cases():
    values=[0.0,-0.0,1.0,-1.0,2.0,-2.0,0.1,-0.1,1e-323,-1e-323,
            5e-324,-5e-324,sys.float_info.min,-sys.float_info.min,
            sys.float_info.max,-sys.float_info.max,float('inf'),-float('inf'),float('nan')]
    pairs=[(left,right) for left in values for right in values]
    pairs.extend((left,right) for right in (.1,.2,.3,1.1,1e-20,1e20)
                 for left in (math.nextafter(10*right,-math.inf),10*right,math.nextafter(10*right,math.inf),
                              -math.nextafter(10*right,-math.inf),-10*right,-math.nextafter(10*right,math.inf)))
    rng=random.Random(0xD1F10A7)
    pairs.extend((number(rng.getrandbits(64)),number(rng.getrandbits(64))) for _ in range(2500))
    return pairs


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FloatArithmeticTests(unittest.TestCase):
    run_source=test_runtime.RuntimeTests.run_source

    def test_binary64_helper_matches_cpython_bits_debug_release(self):
        # The oracle is CPython's independent implementation, not a repeated
        # Python transcription of the Rust algorithm under test.
        source=Path(__file__).resolve().parents[1]/'py2fastrust/runtime/float_arithmetic.rs'
        helper=source.read_text().split('\nimpl Runtime {',1)[0]
        harness='''
            use std::io::{self,BufRead};
            type PyResult<T>=Result<T,String>;
            fn pyerr(kind:&str,message:&str)->String{format!("{kind}: {message}")}
        '''+helper+'''
            fn show(value:f64)->String{if value.is_nan(){"nan".into()}else{format!("{:016x}",value.to_bits())}}
            fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();
                let mut fields=line.split_whitespace();
                let left=f64::from_bits(u64::from_str_radix(fields.next().unwrap(),16).unwrap());
                let right=f64::from_bits(u64::from_str_radix(fields.next().unwrap(),16).unwrap());
                match float_div_mod(left,right){Ok((q,r))=>println!("{} {}",show(q),show(r)),Err(_)=>println!("ZeroDivisionError")}
            }}
        '''
        values=cases()
        input_text=''.join(f'{bits(a):016x} {bits(b):016x}\n' for a,b in values)
        expected=[]
        for a,b in values:
            try:
                quotient,remainder=divmod(a,b)
                expected.append(' '.join('nan' if math.isnan(x) else f'{bits(x):016x}' for x in (quotient,remainder)))
            except ZeroDivisionError:expected.append('ZeroDivisionError')
        with tempfile.TemporaryDirectory(prefix='float-arithmetic-bits-') as directory:
            path=Path(directory);target=path/'bits.rs';target.write_text(harness)
            for optimized in (False,True):
                with self.subTest(release=optimized):
                    binary=path/('release' if optimized else 'debug')
                    compiled=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(binary),*(['-O'] if optimized else [])],capture_output=True,text=True,timeout=90)
                    self.assertEqual(compiled.returncode,0,compiled.stderr)
                    actual=subprocess.run([str(binary)],input=input_text,capture_output=True,text=True,check=True)
                    self.assertEqual(actual.stdout.splitlines(),expected)

if __name__=='__main__':unittest.main()
