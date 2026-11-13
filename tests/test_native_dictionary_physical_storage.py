"""Live-only copy, physical remapping and original canonical-key properties."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROBE=r'''
use std::cell::{Cell,RefCell};use std::rc::Rc;use std::hash::{Hash,Hasher};
struct Canonical{value:i64,representative:usize,clones:Rc<Cell<usize>>}
impl Clone for Canonical{fn clone(&self)->Self{self.clones.set(self.clones.get()+1);Self{value:self.value,representative:self.representative,clones:self.clones.clone()}}}
impl PartialEq for Canonical{fn eq(&self,other:&Self)->bool{self.value==other.value}}
impl Eq for Canonical{}
impl Hash for Canonical{fn hash<H:Hasher>(&self,state:&mut H){self.value.hash(state);}}
struct Payload{value:i64,clones:Rc<Cell<usize>>,shared:Rc<RefCell<Vec<i64>>>}
impl Clone for Payload{fn clone(&self)->Self{self.clones.set(self.clones.get()+1);Self{value:self.value,clones:self.clones.clone(),shared:self.shared.clone()}}}
fn make(value:i64,clones:&Rc<Cell<usize>>,shared:&Rc<RefCell<Vec<i64>>>)->Payload{Payload{value,clones:clones.clone(),shared:shared.clone()}}
fn canonical(value:i64,clones:&Rc<Cell<usize>>,representative:usize)->Canonical{Canonical{value,representative,clones:clones.clone()}}
fn main(){
 let payload_clones=Rc::new(Cell::new(0));let key_clones=Rc::new(Cell::new(0));let shared=Rc::new(RefCell::new(vec![7]));
 let mut source=NativeKeyDict::<i64,Payload,Canonical>::new();
 for key in 0..4096{source.set(key,canonical(key,&key_clones,key as usize+17),make(key,&payload_clones,&shared)).unwrap();}
 for key in 0..4095{source.delete(&canonical(key,&key_clones,usize::MAX));}
 let query_count=Cell::new(0);let copied=source.try_python_copy(|key|{query_count.set(query_count.get()+1);canonical(*key,&key_clones,usize::MAX)}).unwrap();
 assert_eq!(payload_clones.get(),1);assert_eq!(key_clones.get(),1);assert_eq!(copied.len(),1);assert_eq!(copied.get(&canonical(4095,&key_clones,0)).unwrap().value,4095);
 assert_eq!(copied.index.keys().next().unwrap().representative,4112);
 let mut fresh=std::collections::HashMap::<Canonical,usize,NativeKeyBuildHasher>::with_hasher(source.index.hasher().clone());fresh.try_reserve(1).unwrap();assert_eq!(copied.index.capacity(),fresh.capacity());
 CHECK_COPY_STORAGE
 shared.borrow_mut().push(9);assert_eq!(*copied.entries.iter().next().unwrap().1.shared.borrow(),vec![7,9]);
 let before_payload=payload_clones.get();let before_keys=key_clones.get();
 TRIGGER_COMPACTION
 assert_eq!(payload_clones.get(),before_payload);assert_eq!(key_clones.get(),before_keys);
 CHECK_COMPACT_STORAGE
 assert_eq!(source.get(&canonical(4095,&key_clones,0)).unwrap().value,4095);
 let mut copied_again=source.try_constructor_copy(|key|canonical(*key,&key_clones,usize::MAX)).unwrap();
 assert_eq!(copied_again.len(),source.len());assert_eq!(payload_clones.get(),before_payload+source.len());
 copied_again.clear();assert_eq!(copied_again.len(),0);assert_eq!(copied_again.index.capacity(),0);
 CHECK_CLEAR_STORAGE
 let empty=copied_again.try_python_copy(|key|canonical(*key,&key_clones,usize::MAX)).unwrap();assert!(empty.is_empty());assert_eq!(empty.index.capacity(),0);
 println!("ok");
}
'''


DENSE_COPY_PROBE=r'''
use std::cell::Cell;use std::rc::Rc;use std::hash::{Hash,Hasher};
use std::sync::atomic::{AtomicUsize,Ordering};
static ALLOCS:AtomicUsize=AtomicUsize::new(0);
static FAIL_ON:AtomicUsize=AtomicUsize::new(0);
struct TrackedAllocator;
unsafe impl std::alloc::GlobalAlloc for TrackedAllocator{
 unsafe fn alloc(&self,layout:std::alloc::Layout)->*mut u8{let current=ALLOCS.fetch_add(1,Ordering::SeqCst)+1;if FAIL_ON.load(Ordering::SeqCst)==current{return std::ptr::null_mut();}std::alloc::System.alloc(layout)}
 unsafe fn dealloc(&self,ptr:*mut u8,layout:std::alloc::Layout){std::alloc::System.dealloc(ptr,layout)}
 unsafe fn realloc(&self,ptr:*mut u8,layout:std::alloc::Layout,size:usize)->*mut u8{let current=ALLOCS.fetch_add(1,Ordering::SeqCst)+1;if FAIL_ON.load(Ordering::SeqCst)==current{return std::ptr::null_mut();}std::alloc::System.realloc(ptr,layout,size)}
}
#[global_allocator]static ALLOCATOR:TrackedAllocator=TrackedAllocator;
#[derive(Clone)]struct Canonical{value:i64,representative:usize,hashes:Rc<Cell<usize>>}
impl PartialEq for Canonical{fn eq(&self,other:&Self)->bool{self.value==other.value}}impl Eq for Canonical{}
impl Hash for Canonical{fn hash<H:Hasher>(&self,state:&mut H){self.hashes.set(self.hashes.get()+1);self.value.hash(state)}}
fn key(value:i64,hashes:&Rc<Cell<usize>>,representative:usize)->Canonical{Canonical{value,representative,hashes:hashes.clone()}}
fn main(){
 let hashes=Rc::new(Cell::new(0));
 for count in [1,3,4,7,8,14,15,28,29,55,56,112,113,4000]{
  let mut source=NativeKeyDict::<i64,Rc<Cell<i64>>,Canonical>::new();
  for value in 0..count{source.set(value,key(value,&hashes,value as usize+97),Rc::new(Cell::new(value))).unwrap();}
  assert!(source.entries.index_unerased);hashes.set(0);ALLOCS.store(0,Ordering::SeqCst);
  let copied=source.try_python_copy(|value|key(*value,&hashes,usize::MAX)).unwrap();
  let allocations=ALLOCS.load(Ordering::SeqCst);assert_eq!(allocations,EXPECTED_ALLOCATIONS);
  assert_eq!(hashes.get(),0);assert_eq!(copied.index.capacity(),source.index.capacity());
  for stored in copied.index.keys(){assert_eq!(stored.representative,stored.value as usize+97);}
  for failure in 1..=EXPECTED_ALLOCATIONS{
   ALLOCS.store(0,Ordering::SeqCst);FAIL_ON.store(failure,Ordering::SeqCst);
   let failed=source.try_python_copy(|value|key(*value,&hashes,usize::MAX));FAIL_ON.store(0,Ordering::SeqCst);
   assert!(failed.is_err());assert_eq!(source.len(),count as usize);
  }
  source.get(&key(0,&hashes,0)).unwrap().set(99);assert_eq!(copied.get(&key(0,&hashes,0)).unwrap().get(),99);
  let mut popped=source.try_python_copy(|value|key(*value,&hashes,usize::MAX)).unwrap();
  native_dict_popitem(&mut popped.entries,&mut popped.index,|value|key(*value,&hashes,usize::MAX)).unwrap();assert!(!popped.entries.index_unerased);
  popped.clear();assert!(popped.entries.index_unerased);assert_eq!(popped.index.capacity(),0);
  if count>1{
   assert!(source.delete(&key(0,&hashes,0)));source.set(0,key(0,&hashes,9000),Rc::new(Cell::new(100))).unwrap();
   assert!(!source.entries.index_unerased);CHECK_NO_HOLES hashes.set(0);
   let copied=source.try_python_copy(|value|key(*value,&hashes,usize::MAX)).unwrap();assert!(hashes.get()>=count as usize);
   assert!(copied.entries.index_unerased);assert_eq!(copied.index.get_key_value(&key(0,&hashes,0)).unwrap().0.representative,9000);
  }
 }
 let mut oversized=NativeKeyDict::<i64,i64,Canonical>::new();oversized.set(1,key(1,&hashes,123),2).unwrap();oversized.index.try_reserve(100000).unwrap();
 hashes.set(0);let copied=oversized.try_constructor_copy(|value|key(*value,&hashes,usize::MAX)).unwrap();assert!(hashes.get()>0);assert!(copied.index.capacity()<oversized.index.capacity());
 let mut fresh=std::collections::HashMap::<Canonical,usize,NativeKeyBuildHasher>::with_hasher(oversized.index.hasher().clone());fresh.try_reserve(1).unwrap();assert_eq!(copied.index.capacity(),fresh.capacity());
 println!("ok");
}
'''


def products(layout):
    from py2fastrust.native_ordered_entries import DENSE_HELPERS,ORDERED_HELPERS,POSITIONED_HELPERS,POPITEM_HELPER
    from py2fastrust.native_key_containers import HELPERS
    helpers={'dense':DENSE_HELPERS,'ordered':ORDERED_HELPERS,'positioned':POSITIONED_HELPERS}[layout]
    if layout=='dense':
        copy='assert_eq!(copied.entries.len(),1);'
        trigger='source.set(9000,canonical(9000,&key_clones,9017),make(9000,&payload_clones,&shared)).unwrap();'
        compact='assert_eq!(source.entries.len(),2);'
        clear='assert_eq!(copied_again.entries.capacity(),0);'
    else:
        copy='assert_eq!(copied.entries.slots.len(),1);assert_eq!(source.entries.slots.len(),4096);'
        trigger=''
        if layout=='positioned':
            copy+='assert_eq!(copied.entries.positions.len(),1);assert_eq!(copied.entries.table_size,8);'
            trigger='while source.entries.usable>0{source.set(9000,canonical(9000,&key_clones,9017),make(9000,&payload_clones,&shared)).unwrap();source.delete(&canonical(9000,&key_clones,0));}'
        trigger+='source.set(9000,canonical(9000,&key_clones,9017),make(9000,&payload_clones,&shared)).unwrap();'
        compact='assert_eq!(source.entries.slots.len(),2);assert_eq!(source.entries.free,NATIVE_ENTRY_NONE);'
        clear='assert_eq!(copied_again.entries.slots.capacity(),0);'
    code=PROBE.replace('CHECK_COPY_STORAGE',copy).replace('TRIGGER_COMPACTION',trigger).replace('CHECK_COMPACT_STORAGE',compact).replace('CHECK_CLEAR_STORAGE',clear)
    return '#![allow(dead_code,unused_variables,unused_mut)]\n'+helpers+POPITEM_HELPER+HELPERS+code


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DictionaryPhysicalStorageTests(unittest.TestCase):
    def test_dense_live_copy(self):self.check('dense')
    def test_ordered_live_copy_and_density_compaction(self):self.check('ordered')
    def test_positioned_live_copy_and_cp_resize_compaction(self):self.check('positioned')
    def test_dense_copy_uses_preallocated_bulk_index_and_owned_payloads(self):
        for layout in ('dense','ordered','positioned'):
            with self.subTest(layout=layout):self.check(layout,dense=True)
    def test_dense_carrier_rejects_untracked_vec_erasure(self):
        code=products('dense');prefix=code[:code.index('use std::cell::{Cell,RefCell};')]
        source=prefix+"fn invalid(mut entries:NativeDictionaryEntries<i64>){entries.swap_remove(0);entries.truncate(0);entries.retain(|_|true);entries.drain(..); }fn main(){}"
        with tempfile.TemporaryDirectory(prefix='pytors-dense-api-')as directory:
            path=Path(directory)/'kernel.rs';path.write_text(source)
            built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(Path(directory)/'invalid')],text=True,capture_output=True,timeout=120)
            self.assertNotEqual(built.returncode,0)
            self.assertGreaterEqual(built.stderr.count('cannot borrow data in dereference'),4,built.stderr)
    def check(self,layout,dense=False):
        with tempfile.TemporaryDirectory(prefix='pytors-physical-dict-')as directory:
            source=Path(directory)/'kernel.rs';code=products(layout)
            if dense:
                prefix=code[:code.index('use std::cell::{Cell,RefCell};')]
                code=prefix+DENSE_COPY_PROBE.replace('EXPECTED_ALLOCATIONS','3'if layout=='positioned'else'2').replace('CHECK_NO_HOLES','assert_eq!(source.entries.free,NATIVE_ENTRY_NONE);'if layout!='dense'else'')
            source.write_text(code)
            for optimized in (False,True):
                binary=Path(directory)/('opt'if optimized else'debug')
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                ran=subprocess.run([str(binary)],text=True,capture_output=True,timeout=15)
                self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(0,'ok\n',''))


if __name__=='__main__':unittest.main()
