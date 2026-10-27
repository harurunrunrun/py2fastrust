"""Predicate projections stay scalar; count allocations in the real generated program."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile, TranspileOptions
from py2fastrust.aot import rust_mask


ALLOCATOR = r'''
struct PredicateCountingAllocator;
static PREDICATE_ALLOCATIONS:std::sync::atomic::AtomicUsize=std::sync::atomic::AtomicUsize::new(0);
unsafe impl std::alloc::GlobalAlloc for PredicateCountingAllocator {
    unsafe fn alloc(&self,layout:std::alloc::Layout)->*mut u8 {
        PREDICATE_ALLOCATIONS.fetch_add(1,std::sync::atomic::Ordering::Relaxed);
        std::alloc::GlobalAlloc::alloc(&std::alloc::System,layout)
    }
    unsafe fn dealloc(&self,ptr:*mut u8,layout:std::alloc::Layout) {
        std::alloc::GlobalAlloc::dealloc(&std::alloc::System,ptr,layout)
    }
    unsafe fn realloc(&self,ptr:*mut u8,layout:std::alloc::Layout,size:usize)->*mut u8 {
        PREDICATE_ALLOCATIONS.fetch_add(1,std::sync::atomic::Ordering::Relaxed);
        std::alloc::GlobalAlloc::realloc(&std::alloc::System,ptr,layout,size)
    }
}
#[global_allocator] static PREDICATE_ALLOCATOR:PredicateCountingAllocator=PredicateCountingAllocator;
fn main() {
    PREDICATE_ALLOCATIONS.store(0,std::sync::atomic::Ordering::Relaxed);
    predicate_measured_main();
    eprintln!("PREDICATE_ALLOCATIONS={}",PREDICATE_ALLOCATIONS.load(std::sync::atomic::Ordering::Relaxed));
}
'''


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativePredicateAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-predicate-allocations-')
        cls.counter=0

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def compile(self,source,mode,string_mode):
        result=transpile(source,TranspileOptions(integer=mode,string_mode=string_mode))
        self.assertTrue(result.success,result.diagnostics)
        rust=result.rust_source
        masked=rust_mask(rust)
        mains=list(re.finditer(r'\bfn\s+(main)\s*\(',masked))
        self.assertEqual(len(mains),1)
        position=mains[0].span(1)
        measured=rust[:position[0]]+'predicate_measured_main'+rust[position[1]:]+ALLOCATOR
        type(self).counter+=1
        path=Path(self.directory.name,f'program{self.counter}.rs');path.write_text(measured)
        binary=path.with_suffix('')
        compiled=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        return binary,rust

    def execute(self,binary,source,data):
        result=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=10)
        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,text=True,capture_output=True,timeout=10)
        self.assertEqual((result.returncode,result.stdout),(expected.returncode,expected.stdout),result.stderr)
        count=re.fullmatch(r'PREDICATE_ALLOCATIONS=(\d+)\n',result.stderr)
        self.assertIsNotNone(count,result.stderr)
        return int(count[1])

    def test_stream_predicate_does_not_allocate_a_string_per_character(self):
        source='text=input()\nprint(sum(char.isupper() for char in text))\n'
        for string_mode,pattern in (('ascii','Aa09_'),('unicode','Αβǅ猫𐵐')):
            for mode in ('i64','i128','bigint'):
                with self.subTest(mode=mode,string_mode=string_mode):
                    binary,rust=self.compile(source,mode,string_mode)
                    main=rust_mask(rust)[rust_mask(rust).rfind('fn main'):]
                    self.assertNotIn('char::from_u32',main)
                    self.assertIn('native_str_isupper_code',main)
                    small=self.execute(binary,source,pattern*20+'\n')
                    large=self.execute(binary,source,pattern*4000+'\n')
                    # Input buffering may grow logarithmically. A character
                    # materialization would add at least twenty thousand calls.
                    self.assertLess(large,200)
                    self.assertLessEqual(large-small,32)

    def test_index_predicate_uses_the_checked_codepoint_projection(self):
        source='text=input()\nprint(sum(text[i].isalpha() for i in range(len(text))))\n'
        for string_mode,pattern in (('ascii','Aa09_'),('unicode','Αβǅ猫𐵐')):
            for mode in ('i64','i128','bigint'):
                with self.subTest(mode=mode,string_mode=string_mode):
                    binary,rust=self.compile(source,mode,string_mode)
                    small=self.execute(binary,source,pattern*20+'\n')
                    large=self.execute(binary,source,pattern*4000+'\n')
                    self.assertLess(large,200)
                    self.assertLessEqual(large-small,32)

    def test_whole_isascii_reuses_physical_owner_metadata(self):
        source='text=input()\nn=int(input())\nprint(sum(text.isascii() for i in range(n)))\n'
        for mode in ('i64','i128','bigint'):
            with self.subTest(mode=mode):
                binary,rust=self.compile(source,mode,'unicode')
                self.assertNotIn('native_str_isascii(',rust)
                for pattern in ('A'*20000,'猫'*20000):
                    small=self.execute(binary,source,pattern+'\n1\n')
                    large=self.execute(binary,source,pattern+'\n20000\n')
                    self.assertLessEqual(large-small,8)


if __name__=='__main__':unittest.main()
