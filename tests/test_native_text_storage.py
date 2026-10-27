"""Physical text snapshots and warmed literal/index caches allocate no storage."""
from importlib.resources import files
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust.native_cached_text import HELPERS


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeTextStorageTests(unittest.TestCase):
    def test_shared_snapshots_and_warmed_literal_reads_do_not_allocate(self):
        kernel=files('py2fastrust').joinpath('runtime','native_text.rs').read_text()
        probe=r'''
use std::alloc::{GlobalAlloc,Layout,System};
use std::sync::atomic::{AtomicUsize,Ordering};
struct Counting;
static ALLOCATIONS:AtomicUsize=AtomicUsize::new(0);
unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self,layout:Layout)->*mut u8 {ALLOCATIONS.fetch_add(1,Ordering::Relaxed);unsafe{System.alloc(layout)}}
    unsafe fn dealloc(&self,pointer:*mut u8,layout:Layout){unsafe{System.dealloc(pointer,layout)}}
    unsafe fn realloc(&self,pointer:*mut u8,layout:Layout,length:usize)->*mut u8 {
        ALLOCATIONS.fetch_add(1,Ordering::Relaxed);unsafe{System.realloc(pointer,layout,length)}
    }
}
#[global_allocator]static ALLOCATOR:Counting=Counting;
fn literal()->NativeText {
    static VALUE:NativeTextLiteral=NativeTextLiteral::new("あ🙂éxあ🙂éxあ🙂éx");
    NativeText::literal(&VALUE)
}
fn main(){
    let owner=NativeText::from("あ🙂éx".repeat(200));
    let alias=owner.clone();
    assert_eq!(alias.codepoint_len(),800);
    assert_eq!(native_text_get(&alias,1).unwrap().as_str(),"🙂");
    assert_eq!(native_text_get(&literal(),1).unwrap().as_str(),"🙂");
    let before=ALLOCATIONS.load(Ordering::Relaxed);
    for index in 0..10000 {
        let snapshot=std::hint::black_box(owner.clone());
        std::hint::black_box(snapshot.codepoint_len());
        std::hint::black_box(native_text_get(&snapshot,index%800).unwrap());
        std::hint::black_box(native_text_codepoint(&snapshot,index%800).unwrap());
        let value=std::hint::black_box(literal());
        std::hint::black_box(value.codepoint_len());
        std::hint::black_box(native_text_get(&value,index%12).unwrap());
        std::hint::black_box(native_text_codepoint(&value,index%12).unwrap());
    }
    assert_eq!(ALLOCATIONS.load(Ordering::Relaxed),before);
    let changed=NativeText::from(owner.clone().into_string()+"!");
    assert_eq!(owner,alias);
    assert_eq!(changed.codepoint_len(),owner.codepoint_len()+1);
}
'''
        with tempfile.TemporaryDirectory(prefix='pytors-text-storage-')as directory:
            path=Path(directory,'main.rs');path.write_text('const NATIVE_TEXT_UNICODE:bool=true;\n'+kernel+'\n'+HELPERS+probe)
            binary=path.with_suffix('')
            built=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
