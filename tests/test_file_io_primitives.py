"""CPython-oracle tests for checked descriptor ownership and binary buffering."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
fn main(){
    let arguments:Vec<String>=std::env::args().collect();
    let path=&arguments[2];
    std::fs::write(path,b"abcd").unwrap();
    let file=std::fs::OpenOptions::new().read(true).write(true).open(path).unwrap();
    let raw=std::rc::Rc::new(std::cell::RefCell::new(FileRaw::owned(file,true,true)));
    let mut buffer=FileBuffer::new(raw.clone(),4);
    match arguments[1].as_str(){
        "sync"=>{
            let first=buffer.read(Some(1),false,false).unwrap();
            println!("{} {} {}",String::from_utf8(first).unwrap(),buffer.tell().unwrap(),raw.borrow_mut().seek(0,1).unwrap());
            buffer.flush().unwrap();println!("{} {}",buffer.tell().unwrap(),raw.borrow_mut().seek(0,1).unwrap());
            buffer.write(b"XZ").unwrap();println!("{}",buffer.tell().unwrap());
            buffer.seek(0,0).unwrap();println!("{}",String::from_utf8(buffer.read(None,false,false).unwrap()).unwrap());
            buffer.truncate(3).unwrap();buffer.seek(0,0).unwrap();println!("{}",String::from_utf8(buffer.read(None,false,false).unwrap()).unwrap());
            buffer.close().unwrap();buffer.close().unwrap();
            println!("{}",buffer.read(Some(0),false,false).unwrap_err().kind);
        },
        "lines"=>{
            buffer.write(b"a\nbc\nlast").unwrap();buffer.seek(0,0).unwrap();
            for _ in 0..4 {println!("{}",String::from_utf8(buffer.read(None,true,false).unwrap()).unwrap().replace('\n',"\\n"));}
            buffer.seek(0,0).unwrap();buffer.read(Some(1),false,false).unwrap();
            println!("{}",String::from_utf8(buffer.read(Some(20),false,true).unwrap()).unwrap().replace('\n',"\\n"));
            println!("{}",String::from_utf8(buffer.read(Some(20),false,true).unwrap()).unwrap().replace('\n',"\\n"));
            buffer.close().unwrap();
        },
        "fd"=>{
            let fd=raw.borrow().fileno().unwrap();
            let mut borrowed=FileRaw::descriptor(fd,false,true,true).unwrap();
            borrowed.close().unwrap();
            let mut byte=[0];raw.borrow_mut().read(&mut byte).unwrap();println!("{}",byte[0]);
            let mut alias=FileRaw::descriptor(fd,true,true,true).unwrap();alias.close().unwrap();
            let error=raw.borrow_mut().read(&mut byte).unwrap_err();println!("{} {}",error.kind,error.attributes["errno"].clone().as_test_integer());
            let error=raw.borrow_mut().close().unwrap_err();println!("{}",error.kind);
            raw.borrow_mut().close().unwrap();
            let error=FileRaw::descriptor(-1,false,true,false).unwrap_err();println!("{} None",error.kind);
            // Closing a second wrapper for the same descriptor must not leave
            // an OwnedFd which aborts when the original wrapper is destroyed.
        },
        _=>panic!("unknown case"),
    }
}
impl Value {
    fn as_test_integer(&self)->i128 {match self{Value::Int(value)=>value.to_i128().unwrap(),_=>panic!("expected errno")}}
}
'''


@unittest.skipUnless(shutil.which('rustc')and sys.platform=='linux','64-bit Unix Rust target required')
class FileIoPrimitiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='pytors-file-primitives-')
        base=transpile('',TranspileOptions(optimize=False)).rust_source
        base=base.replace('fn main() {','fn original_program_main() {',1)
        if 'enum FileHandle' not in base:
            base+='\n'+(ROOT/'py2fastrust/runtime/file_io.rs').read_text()
        base+='\n'+HARNESS
        cls.binaries=[]
        for optimized in (False,True):
            path=Path(cls.tmp.name)/f'main-{int(optimized)}.rs';path.write_text(base)
            binary=path.with_suffix('')
            compiled=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=180)
            if compiled.returncode:raise AssertionError(compiled.stderr)
            cls.binaries.append(binary)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def compare(self,name,python):
        for index,binary in enumerate(self.binaries):
            with self.subTest(optimized=index):
                path=Path(self.tmp.name)/f'{name}-{index}.dat'
                reference=subprocess.run([sys.executable,'-I','-c',python,str(path)],capture_output=True,text=True,timeout=10)
                self.assertEqual(reference.returncode,0,reference.stderr)
                actual=subprocess.run([str(binary),name,str(path)],capture_output=True,text=True,timeout=10)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout,reference.stdout)

    def test_read_write_switch_flush_seek_and_truncate(self):
        self.compare('sync',r'''
import sys
path=sys.argv[1]
with open(path,'wb')as f:f.write(b'abcd')
f=open(path,'r+b',buffering=4)
print(f.read(1).decode(),f.tell(),f.raw.tell())
f.flush();print(f.tell(),f.raw.tell())
f.write(b'XZ');print(f.tell())
f.seek(0);print(f.read().decode())
f.truncate(3);f.seek(0);print(f.read().decode())
f.close();f.close()
try:f.read(0)
except Exception as e:print(type(e).__name__)
''')

    def test_line_boundaries_short_reads_and_single_raw_read(self):
        self.compare('lines',r'''
import sys
path=sys.argv[1]
with open(path,'wb')as f:f.write(b'abcd')
f=open(path,'r+b',buffering=4)
f.write(b'a\nbc\nlast');f.seek(0)
for _ in range(4):print(f.readline().decode().replace('\n',r'\n'))
f.seek(0);f.read(1)
print(f.read1(20).decode().replace('\n',r'\n'))
print(f.read1(20).decode().replace('\n',r'\n'))
f.close()
''')

    def test_shared_descriptors_closefd_and_invalid_numbers_never_abort(self):
        self.compare('fd',r'''
import sys
path=sys.argv[1]
with open(path,'wb')as f:f.write(b'abcd')
f=open(path,'r+b',buffering=0)
borrowed=open(f.fileno(),'r+b',buffering=0,closefd=False)
borrowed.close();print(f.read(1)[0])
alias=open(f.fileno(),'r+b',buffering=0);alias.close()
try:f.read(1)
except Exception as e:print(type(e).__name__,e.errno)
try:f.close()
except Exception as e:print(type(e).__name__)
f.close()
try:open(-1,'rb',buffering=0)
except Exception as e:print(type(e).__name__,getattr(e,'errno',None))
''')
