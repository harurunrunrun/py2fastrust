"""Builtin real comparisons preserve integer precision and source effects."""
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from importlib.resources import files

import test_native_union_ordering as helpers


RELATIONS='a==b,a!=b,a<b,a<=b,a>b,a>=b,b==a,b!=a,b<a,b<=a,b>a,b>=a'
SCALAR='n=int(input())\nfor _ in range(n):\n a=int(input())\n b=float(input())\n print('+RELATIONS+')\n'


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class BigIntFloatComparisonExecution(unittest.TestCase):
 setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
 tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
 compile=helpers.NativeUnionOrderingTests.compile
 exercise=helpers.NativeUnionOrderingTests.exercise

 def test_all_six_relations_handle_boundaries_signed_zero_and_nan(self):
  integers=[0,1,-1,2,-2,(1<<53)-1,1<<53,(1<<53)+1,-((1<<53)+1),-(1<<63),(1<<63)-1]
  floats=[0.0,-0.0,0.5,-0.5,1.5,-1.5,float(1<<53),-float(1<<53),5e-324,-5e-324,
          1.7976931348623157e308,-1.7976931348623157e308,math.inf,-math.inf,math.nan]
  pairs=[(a,b)for a in integers for b in floats]
  data=str(len(pairs))+'\n'+''.join(str(a)+'\n'+repr(b)+'\n'for a,b in pairs)
  self.exercise(SCALAR,(data,))

 def test_large_magnitudes_limb_boundaries_and_random_binary64_bits(self):
  rng=random.Random(2026111201)
  integers=[sign*((1<<bits)+delta)for bits in (53,63,64,127,128,129,255,256,511,1023,1024,2048,4096)
            for sign in (-1,1)for delta in (-1,0,1)]
  floats=[0.0,-0.0,math.inf,-math.inf,math.nan,5e-324,-5e-324]
  floats.extend(float(sign)*(2.0**exponent)for sign in (-1,1)for exponent in (0,53,127,255,511,1023))
  pairs=[(a,rng.choice(floats))for a in integers]
  for _ in range(400):
   number=struct.unpack('>d',rng.getrandbits(64).to_bytes(8,'big'))[0]
   integer=rng.getrandbits(rng.randrange(0,5000))*rng.choice((-1,1))
   pairs.append((integer,number))
   if math.isfinite(number):pairs.extend((int(number)+delta,number)for delta in (-1,0,1))
  data=str(len(pairs))+'\n'+''.join(str(a)+'\n'+repr(b)+'\n'for a,b in pairs)
  self.exercise(SCALAR,(data,),modes=('bigint',))

 def test_finite_numeric_alternatives_compare_actual_scalar_payloads(self):
  source='flag=int(input())\na=int(input()) if flag else float(input())\nb=float(input())\nprint('+RELATIONS+')\n'
  self.exercise(source,('1\n9007199254740993\n9007199254740992\n','1\n1\nnan\n',
                        '0\nnan\nnan\n','0\n1.5\n1.5\n','1\n0\n-0.0\n'))

 def test_frame_scalar_comparisons_have_the_same_exact_contract(self):
  source='class Comparison:\n def run(self,a,b):return '+RELATIONS+'\n'
  source+='comparison=Comparison()\na=int(input())\nb=float(input())\nprint(comparison.run(a,b))\n'
  self.exercise(source,('9007199254740993\n9007199254740992\n','0\n-0.0\n','1\nnan\n','-1\n-inf\n'))
  self.exercise(source,(str(1<<2048)+'\n1.7976931348623157e308\n',),modes=('bigint',))

 def test_boolean_and_integer_alternatives_keep_numeric_equality(self):
  source='flag=int(input())\na=True if flag else 2\nb=float(input())\nprint('+RELATIONS+')\n'
  self.exercise(source,('0\n2.0\n','1\n1.0\n','1\nnan\n','0\n1.5\n'))

 def test_chained_comparisons_preserve_short_circuit_and_operand_effects(self):
  self.exercise('''def mark(tag,value):
 print(tag,end='|')
 return value
a=int(input())
b=float(input())
print(mark('first',a)<mark('second',b)<mark('third',a+1))
print(mark('fourth',a)==mark('fifth',b)==mark('sixth',a))
print(mark('seventh',a)!=mark('eighth',b)!=mark('ninth',a))
''',('1\n1.5\n','1\n1.0\n','1\nnan\n','9007199254740993\n9007199254740992\n'))

 def test_comparison_does_not_coerce_huge_integer_to_binary64(self):
  source='a=int(input())\nb=float(input())\nprint('+RELATIONS+')\n'
  self.exercise(source,(str(1<<4000)+'\ninf\n',str(-(1<<4000))+'\n-inf\n',
                        str(1<<4000)+'\n1e300\n'),modes=('bigint',))

 def test_zero_trip_loop_preserves_an_uninitialized_float_binding(self):
  source='n=int(input())\nfor _ in range(n):\n a=float(input())\nprint(a)\n'
  self.exercise(source,('0\n','1\n1.5\n','2\n1.5\n-0.0\n'))


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ExactIntegerFloatRuntime(unittest.TestCase):
 def test_comparison_uses_no_heap_storage_in_any_integer_mode(self):
  runtime=files('py2fastrust').joinpath('runtime','integer.rs').read_text()
  harness=r'''use std::alloc::{GlobalAlloc,Layout,System};
use std::sync::atomic::{AtomicUsize,Ordering};
static ALLOCATIONS:AtomicUsize=AtomicUsize::new(0);
struct Counting;
unsafe impl GlobalAlloc for Counting {
 unsafe fn alloc(&self,layout:Layout)->*mut u8{ALLOCATIONS.fetch_add(1,Ordering::SeqCst);unsafe{System.alloc(layout)}}
 unsafe fn dealloc(&self,pointer:*mut u8,layout:Layout){unsafe{System.dealloc(pointer,layout)}}
 unsafe fn realloc(&self,pointer:*mut u8,layout:Layout,size:usize)->*mut u8{ALLOCATIONS.fetch_add(1,Ordering::SeqCst);unsafe{System.realloc(pointer,layout,size)}}
}
#[global_allocator]static ALLOCATOR:Counting=Counting;
fn main(){
 let values=[Int::exact_small(0),Int::exact_small(1),Int::exact_small(-1),Int::exact_small(i128::MIN),
 Int::exact_from_f64(f64::MAX).unwrap(),Int::exact_from_f64(-f64::MAX).unwrap()];
 let floats=[0.0,-0.0,0.5,-0.5,5e-324,-5e-324,1.5,-1.5,f64::MAX,-f64::MAX,f64::INFINITY,f64::NEG_INFINITY,f64::NAN];
 ALLOCATIONS.store(0,Ordering::SeqCst);
 for _ in 0..100{
  for value in &values{for number in floats{std::hint::black_box(std::hint::black_box(value).cmp_f64(std::hint::black_box(number)));}}
 }
 let allocations=ALLOCATIONS.load(Ordering::SeqCst);
 println!("{}",allocations);
}
'''
  with tempfile.TemporaryDirectory(prefix='pytors-exact-real-')as directory:
   for bits in (0,64,128):
    for optimized in (False,True):
     source=Path(directory)/f'comparison_{bits}_{optimized}.rs'
     source.write_text('const INT_BITS:u32='+str(bits)+';\n'+runtime+harness)
     binary=source.with_suffix('')
     result=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(result.returncode,0,result.stderr)
     run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
     self.assertEqual((run.stdout,run.stderr,run.returncode),('0\n','',0))
