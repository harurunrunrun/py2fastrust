"""Exact large products and bit operations across recursive limb boundaries."""
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

RUNTIME=Path(__file__).resolve().parents[1]/'py2fastrust/runtime/integer.rs'
HARNESS=r'''
fn main(){
 use std::io::{self,BufRead};
 for line in io::stdin().lock().lines(){
  let line=line.unwrap();let fields:Vec<&str>=line.split('\t').collect();
  let a=Int::parse_ascii(fields[1].as_bytes(),16).unwrap();let b=Int::parse_ascii(fields[2].as_bytes(),16).unwrap();
  let value=match fields[0]{"mul"=>a.mul(&b),"and"=>a.bitand(&b),"or"=>a.bitor(&b),_=>a.bitxor(&b)};
  println!("{}",value.radix(16,false));
 }
}
'''
def wrap(n,bits):return (n+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))if bits else n

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class LargeProductTests(unittest.TestCase):
    def test_products_and_mixed_sign_bits(self):
        rng=random.Random(27261112);pairs=[]
        for words in (1,4,31,32,33,63,64,65,127,128,129,255,256,257,511,512,513):
            p=1<<(32*words)
            pairs.extend([(p-1,p-1),(p+1,p-1),(p,p),(p+1,p+1),(p-1,1),(0,p-1)])
            pairs.extend((p+1,mask)for mask in (0,1,(1<<96)+1,(1<<127)-1))
            for other in (max(1,words//2),max(1,words//2+1),words,words+1,words*2,words*2+1):
                pairs.append((rng.getrandbits(words*32),rng.getrandbits(other*32)))
        pairs.extend((rng.getrandbits(64*32),rng.getrandbits(words*32))for words in (129,257,513,1025))
        pairs += [(rng.getrandbits(rng.randrange(2000,24000)),rng.getrandbits(rng.randrange(2000,24000)))for _ in range(40)]
        pairs=[(a*sa,b*sb)for a,b in pairs for sa,sb in ((1,1),(-1,1),(1,-1),(-1,-1))]
        with tempfile.TemporaryDirectory(prefix='pytors-large-product-')as folder:
            for bits in (0,64,128):
                commands=[];expected=[]
                for a,b in pairs:
                    x,y=wrap(a,bits),wrap(b,bits)
                    for name,value in (('mul',x*y),('and',x&y),('or',x|y),('xor',x^y)):
                        commands.append(f'{name}\t{a:x}\t{b:x}');expected.append(format(wrap(value,bits),'x'))
                rust=Path(folder,f'integer_{bits}.rs');rust.write_text(f'const INT_BITS:u32={bits};\n'+RUNTIME.read_text()+HARNESS)
                for optimized in (False,True):
                    binary=Path(folder,f'run_{bits}_{int(optimized)}');built=subprocess.run(['rustc','--edition=2021','-A','dead_code',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120);self.assertEqual(built.returncode,0,built.stderr)
                    ran=subprocess.run([str(binary)],input='\n'.join(commands)+'\n',capture_output=True,text=True,timeout=60)
                    with self.subTest(bits=bits,optimized=optimized):
                        self.assertEqual(ran.returncode,0,ran.stderr);actual=ran.stdout.splitlines();self.assertEqual(len(actual),len(expected))
                        for command,want,got in zip(commands,expected,actual):self.assertEqual(got,want,command[:100])

if __name__=='__main__':unittest.main()
