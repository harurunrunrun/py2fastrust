"""Integer window fusion keeps width, signs, evaluation order and exceptions."""
from pathlib import Path
import random,shutil,subprocess,tempfile,unittest
import test_native_lambda_callbacks as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IntegerWindowTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_direct_scalar_generation_keeps_call_order(self):
        self.exercise('''x = int(input())
def count():
 print("count")
 return int(input())
print(x >> count() & 255)
print(31 & (x >> 2))
''',('1234567\n7\n','-7654321\n7\n','0\n-1\n'))

    def test_scalar_and_list_windows_in_both_operand_orders(self):
        self.exercise('''class Box:
 def __init__(self):self.a=[1234567,-7654321]
box=Box()
a=box.a
x,k=map(int,input().split())
print(x >> k & 31, 255 & (x >> k))
print(a[0] >> k & 255, 127 & (a[-1] >> k))
''',('1234567 0\n','-7654321 7\n','-1 95\n','0 -1\n'))

    def test_callback_changes_value_only_after_old_integer_is_read(self):
        self.exercise('''class Box:
 def __init__(self):self.a=[127]
box=Box()
a=box.a
def shift():
 a[0]=0
 print("shift")
 return int(input())
print(a[0] >> shift() & 31,a)
''',('2\n','-1\n'))

    def test_index_error_precedes_shift_error_and_zero_mask_does_not_hide_error(self):
        self.exercise('''class Box:
 def __init__(self):self.a=[7,9]
box=Box()
a=box.a
i,k=map(int,input().split())
print(a[i] >> (1 // k) & 0)
''',('0 1\n','0 0\n','2 0\n','0 -1\n'))

    def test_random_windows_across_limb_boundaries(self):
        runtime=Path(__file__).resolve().parents[1]/'py2fastrust/runtime/integer.rs'
        harness=r'''
fn main(){use std::io::{self,BufRead};
 for line in io::stdin().lock().lines(){let line=line.unwrap();let words:Vec<&str>=line.split_whitespace().collect();
  let a=Int::parse_ascii(words[0].as_bytes(),16).unwrap();let k=Int::parse_ascii(words[1].as_bytes(),16).unwrap();let mask=u128::from_str_radix(words[2],16).unwrap();
  match a.shr_mask(&k,mask){Ok(n)=>println!("{}",n.radix(16,false)),Err(e)=>println!("{}",e)}
 }
}
'''
        def normalize(value,bits):return(value+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))if bits else value
        rng=random.Random(48962611);cases=[]
        for length in (0,1,31,32,33,127,128,129,1023,4096,10001):
            values=(0,1<<length,(1<<length)-1,rng.getrandbits(length))
            for value in values:
                for sign in (-1,1):
                    for shift in (-1,0,1,31,32,33,127,128,129,length,length+1,2**256):
                        for mask in (0,1,255,(1<<127)-1):cases.append((sign*value,shift,mask))
        with tempfile.TemporaryDirectory(prefix='pytors-window-')as folder:
            for bits in (0,64,128):
                commands=[];expected=[]
                for a,k,mask in cases:
                    x,s=normalize(a,bits),normalize(k,bits);commands.append(f'{a:x} {k:x} {mask:x}')
                    expected.append('ValueError: negative shift count'if s<0 else format(normalize((x>>s)&normalize(mask,bits),bits),'x'))
                rust=Path(folder)/f'window_{bits}.rs';rust.write_text(f'const INT_BITS:u32={bits};\n'+runtime.read_text()+harness)
                for optimized in (False,True):
                    binary=Path(folder)/f'run_{bits}_{optimized}'
                    build=subprocess.run(['rustc','--edition=2021','-A','dead_code',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    ran=subprocess.run([str(binary)],input='\n'.join(commands)+'\n',text=True,capture_output=True,timeout=20)
                    self.assertEqual(ran.returncode,0,ran.stderr);actual=ran.stdout.splitlines();self.assertEqual(len(actual),len(expected))
                    for command,want,got in zip(commands,expected,actual):self.assertEqual(got,want,command[:80])


if __name__=='__main__':unittest.main()
