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

    def test_protocol_dispatch_overrides_side_effects_and_complex_unchanged(self):
        source=textwrap.dedent('''
            events=[]
            class F(float):pass
            for a,b in [(1.,.1),(-1.,.1),(0.,-3.),(-0.,3.),(-2.,float('inf')),(2.,-float('inf'))]:
                x=F(a);y=F(b)
                print(x//y,x%y,divmod(x,y),float.__divmod__(x,y))
                print(float.__floordiv__(x,y),float.__mod__(x,y),float.__rdivmod__(y,x))
            class Left(float):
                def __floordiv__(self,other):events.append('left floor');return 'floor'
                def __mod__(self,other):events.append('left mod');return 'mod'
                def __divmod__(self,other):events.append('left divmod');return NotImplemented
            class Right(float):
                def __rdivmod__(self,other):events.append('right divmod');return 'reflected'
            print(Left(1)//Right(.1),Left(1)%Right(.1),divmod(Left(1),Right(.1)),events)
            events.clear()
            def left():events.append('left evaluated');return F(1.)
            def right():events.append('right evaluated');return F(0.)
            for op in ('floor','mod','divmod'):
                try:
                    if op=='floor':left()//right()
                    elif op=='mod':left()%right()
                    else:divmod(left(),right())
                except Exception as error:print(type(error).__name__,str(error),events);events.clear()
            class C(complex):pass
            for value in (1j,C(1j)):
                for action in (lambda:value//2,lambda:value%2,lambda:divmod(value,2)):
                    try:action()
                    except Exception as error:print(type(error).__name__)
            print(divmod(17,3),divmod(-17,3),divmod(17,-3))
        ''')
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_vm_all_modes_debug_release_randomized_and_special_values(self):
        source=textwrap.dedent('''
            import sys
            for line in sys.stdin:
                left,right=map(float,line.split())
                try:print(left//right,left%right,divmod(left,right))
                except Exception as error:print(type(error).__name__,str(error))
        ''')
        input_text=''.join(repr(a)+' '+repr(b)+'\n' for a,b in cases())
        expected=subprocess.run([sys.executable,'-I','-c',source],input=input_text,capture_output=True,text=True,check=True).stdout
        with tempfile.TemporaryDirectory(prefix='float-arithmetic-standalone-') as directory:
            path=Path(directory);empty=path/'empty';empty.mkdir()
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,optimize=False,filename='float_math.py'))
                self.assertTrue(result.success,result.diagnostics)
                target=path/(integer+'.rs');target.write_text(result.rust_source)
                for optimized in (False,True):
                    with self.subTest(integer=integer,release=optimized):
                        binary=path/(integer+('-release' if optimized else '-debug'))
                        compiled=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(binary),*(['-O'] if optimized else [])],capture_output=True,text=True,timeout=150)
                        self.assertEqual(compiled.returncode,0,compiled.stderr)
                        environment=dict(os.environ,PATH=str(path/'no-tools'))
                        environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
                        actual=subprocess.run([str(binary)],cwd=empty,env=environment,input=input_text,capture_output=True,text=True,timeout=30)
                        self.assertEqual(actual.returncode,0,actual.stderr)
                        self.assertEqual(actual.stdout,expected)


if __name__=='__main__':unittest.main()
