"""Parse every power-of-two input base across limb, sign and lexical boundaries."""
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
  let base=fields[1].parse().unwrap();
  let result=if fields[0]=="ascii"{Int::parse_ascii(fields[2].as_bytes(),base)}else{Int::parse(fields[2],base)};
  match result{Ok(value)=>println!("{}",value.radix(16,false)),Err(error)=>println!("ERR:{}",error.split(':').next().unwrap())}
 }
}
'''

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PowerBaseParsingTests(unittest.TestCase):
    def test_all_power_bases_and_both_text_decoders(self):
        rng=random.Random(261112);alphabet='0123456789abcdefghijklmnopqrstuv';raw=[]
        lengths=(1,2,6,7,8,9,10,11,12,13,15,16,17,31,32,33,63,64,65,95,96,97,127,128,129,255,256,257,1024)
        for base in (2,4,8,16,32):
            for count in lengths:
                text=''.join(rng.choice(alphabet[:base])for _ in range(count))
                for sign in ('','-','+'):
                    raw.append((sign+text,base))
                    raw.append((sign+'0000'+'_'.join(text),base))
                    if base in (2,8,16):
                        prefix={2:'0b',8:'0o',16:'0x'}[base]
                        raw.append((sign+prefix+'_'+text,0));raw.append((sign+prefix+'_'+text,base))
        raw += [(text,base)for base in (0,2,4,8,16,32,36)for text in ('','+','-','_','0_','1__0','1_','0x','0x_','0b_','00','00_0','01','-00000','1z','0xg','0b2','٠x_١','\u2003123\u2003')]
        raw += [('f'*100000,16),('-'+'a5'*50000,16),('0x_'+'0'*100000+'1',0),('0'*100000,32),('1'+'0'*100000,2),('f'*100000+'_',16)]
        with tempfile.TemporaryDirectory(prefix='pytors-power-base-')as folder:
            for bits in (0,64,128):
                commands=[];expected=[]
                for decoder in ('text','ascii'):
                    for text,base in raw:
                        commands.append(f'{decoder}\t{base}\t{text}')
                        try:
                            value=int(text if decoder=='text'else text.encode(),base)
                            if bits:value=(value+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))
                            expected.append(format(value,'x'))
                        except ValueError:expected.append('ERR:ValueError')
                rust=Path(folder,f'integer_{bits}.rs');rust.write_text(f'const INT_BITS:u32={bits};\n'+RUNTIME.read_text()+HARNESS)
                for optimized in (False,True):
                    binary=Path(folder,f'run_{bits}_{int(optimized)}');built=subprocess.run(['rustc','--edition=2021','-A','dead_code',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120);self.assertEqual(built.returncode,0,built.stderr)
                    ran=subprocess.run([str(binary)],input='\n'.join(commands)+'\n',capture_output=True,text=True,timeout=30)
                    with self.subTest(bits=bits,optimized=optimized):
                        self.assertEqual(ran.returncode,0,ran.stderr)
                        actual=ran.stdout.splitlines();self.assertEqual(len(actual),len(expected))
                        for command,want,got in zip(commands,expected,actual):self.assertEqual(got,want,command[:120])

if __name__=='__main__':unittest.main()
