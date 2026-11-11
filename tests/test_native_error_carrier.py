"""Native success values use a compact carrier without allocating an error."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust.native_error_support import RUNTIME


HARNESS = r'''
use std::alloc::{GlobalAlloc,Layout,System};
use std::sync::atomic::{AtomicUsize,Ordering};
struct Counter;
static ALLOCATIONS:AtomicUsize=AtomicUsize::new(0);
unsafe impl GlobalAlloc for Counter {
 unsafe fn alloc(&self,layout:Layout)->*mut u8 {
  ALLOCATIONS.fetch_add(1,Ordering::Relaxed);unsafe{System.alloc(layout)}
 }
 unsafe fn dealloc(&self,pointer:*mut u8,layout:Layout){unsafe{System.dealloc(pointer,layout)}}
}
#[global_allocator] static ALLOCATOR:Counter=Counter;
fn main(){
 assert_eq!(std::mem::size_of::<NativeError>(),std::mem::size_of::<usize>());
 assert!(std::mem::size_of::<Result<u64,NativeError>>()<=2*std::mem::size_of::<usize>());
 let before=ALLOCATIONS.load(Ordering::Relaxed);
 let value=std::hint::black_box(Ok::<u64,NativeError>(41));
 assert_eq!(value.unwrap(),41);
 assert_eq!(ALLOCATIONS.load(Ordering::Relaxed),before);
 let before=ALLOCATIONS.load(Ordering::Relaxed);
 let mut error=native_error(String::new(),17,"origin");
 assert_eq!(ALLOCATIONS.load(Ordering::Relaxed),before+1);
 assert_eq!(error.line,17);assert_eq!(error.function,"origin");
 error.message="ValueError: original".to_owned();error.frames.push((23,"caller"));
 let mut snapshot=error.clone();snapshot.message="TypeError: copy".to_owned();snapshot.frames.push((31,"copy"));
 assert_eq!(error.message,"ValueError: original");assert_eq!(error.frames,vec![(23,"caller")]);
 assert_eq!(snapshot.frames,vec![(23,"caller"),(31,"copy")]);
 let result=native_at::<u64>(Err("ValueError: input".to_owned()),7,"parse");
 let error=result.unwrap_err();assert_eq!(error.line,7);assert_eq!(error.function,"parse");
 assert_eq!(error.message,"ValueError: input");assert!(error.frames.is_empty());
}
'''


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeErrorCarrierTests(unittest.TestCase):
    def test_physical_abi_allocation_and_snapshot_value_semantics(self):
        with tempfile.TemporaryDirectory(prefix='pytors-error-carrier-') as directory:
            path=Path(directory)/'carrier.rs'
            path.write_text(RUNTIME+HARNESS)
            for optimized in (False,True):
                with self.subTest(optimized=optimized):
                    binary=Path(directory)/('optimized' if optimized else 'debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O'] if optimized else []),
                        str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,'',''))
