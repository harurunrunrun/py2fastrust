"""Only an absolute literal syscall asm may use ordinary Rust dependencies."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from py2fastrust.rust_pruning import prune_rust_source_with_report

SOURCE=r'''
const WRITE_NUMBER:isize=1;
static PAYLOAD:&[u8]=b"retained operands\n";
fn payload_address()->*const u8{PAYLOAD.as_ptr()}
fn payload_count()->usize{PAYLOAD.len()}
fn referenced_symbol()->usize{17}
fn unrelated_helper()->usize{999}
fn main(){
 let mut result=WRITE_NUMBER;
 unsafe{::std::arch::asm!("syscall",inlateout("rax")result,
  in("rdi")1_usize,in("rsi")payload_address(),in("rdx")payload_count(),
  in("r8")referenced_symbol as *const (),lateout("rcx")_,lateout("r11")_,options(nostack));}
 assert_eq!(result,PAYLOAD.len()as isize);
}
'''


class SyscallPruningTests(unittest.TestCase):
    def test_actual_operands_and_symbol_addresses_remain_reachable(self):
        result=prune_rust_source_with_report(SOURCE)
        self.assertFalse(result.retained,result.reason)
        for name in ('payload_address','payload_count','referenced_symbol'):
            self.assertIn('fn '+name,result.source)
        self.assertIn('static PAYLOAD',result.source)
        self.assertIn('const WRITE_NUMBER',result.source)
        self.assertNotIn('fn unrelated_helper',result.source)
        self.assertIn('unrelated_helper',result.removed_functions)

    def test_other_macro_paths_templates_and_nested_macros_are_opaque(self):
        examples=[
            SOURCE.replace('::std::arch::asm!','asm!'),
            SOURCE.replace('::std::arch::asm!','std::arch::asm!'),
            SOURCE.replace('::std::arch::asm!','custom::std::arch::asm!'),
            SOURCE.replace('"syscall",','"nop",'),
            SOURCE.replace('"syscall",','"syscall","nop",'),
            SOURCE.replace('"syscall",','concat!("sys","call"),'),
            SOURCE.replace('in("rsi")payload_address()','in("rsi")opaque_operand!()'),
            SOURCE.replace('::std::arch::asm!','::std::arch::global_asm!'),
            SOURCE.replace('::std::arch::asm!','syscall_alias!'),
        ]
        for source in examples:
            with self.subTest(source=source):
                result=prune_rust_source_with_report(source)
                self.assertTrue(result.retained,result)
                self.assertEqual(result.source,source)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_original_and_pruned_real_syscall_program_execute_equally(self):
        target=subprocess.check_output(['rustc','-vV'],text=True)
        if 'host: x86_64-unknown-linux-'not in target:self.skipTest('Linux x86_64 syscall test')
        result=prune_rust_source_with_report(SOURCE)
        self.assertFalse(result.retained,result.reason)
        with tempfile.TemporaryDirectory(prefix='pytors-syscall-pruning-')as directory:
            for label,source in [('original',SOURCE),('pruned',result.source)]:
                path=Path(directory)/(label+'.rs');path.write_text(source)
                for optimized in (False,True):
                    binary=path.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                    self.assertEqual((run.returncode,run.stdout,run.stderr),(0,'retained operands\n',''))

if __name__=='__main__':unittest.main()
