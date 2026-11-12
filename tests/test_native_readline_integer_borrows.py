"""Scoped integer-word views preserve text/binary readline protocols."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import test_native_class_iterators as iterator_tests
from test_streaming_io import PipeSession
from py2fastrust import transpile,TranspileOptions

CASES={
 'text_lines': '''import sys
read=sys.stdin.readline
n,q=map(int,read().split())
values=list(map(int,read().split()))
for _ in range(q):
    left,right=map(int,read().split())
    print(sum(values[left:right]))
''',
 'binary_alias_main': '''import sys
def main():
    input=sys.stdin.buffer.readline
    n,q=map(int,input().split())
    values=list(map(int,input().split()))
    for _ in range(q):
        left,right=map(int,input().split())
        print(sum(values[left:right]))
if __name__=='__main__':main()
''',
 'text_eof_list': 'import sys\nread=sys.stdin.readline\na=list(map(int,read().split()))\nb=list(map(int,read().split()))\nprint(a,b)\n',
 'binary_eof_unpack': 'import sys\na,b=map(int,sys.stdin.buffer.readline().split())\nprint(a,b)\n',
 'text_saved_line': 'import sys\nread=sys.stdin.readline\nfirst=read()\na,b=map(int,read().split())\nprint(repr(first),a,b)\n',
 'binary_stored_map': 'import sys\nread=sys.stdin.buffer.readline\nvalues=map(int,read().split())\nother=read()\nprint(list(values),other)\n',
 'binary_separator_reads': '''import sys
read=sys.stdin.buffer.readline
def separator():
    print(read())
    return None
a,b=map(int,read().split(separator()))
print(a,b)
''',
 'text_callback_reads': '''import sys
read=sys.stdin.readline
def convert(value):return int(value)+int(read())
a,b=map(convert,read().split())
print(a,b)
''',
 'text_sizes': 'import sys\nread=sys.stdin.readline\nfirst=read(0)\na,b=map(int,read(3).split())\ntail=read()\nvalues=list(map(int,read().split()))\nprint(repr(first),a,b,repr(tail),values)\n',
 'binary_sizes': 'import sys\nread=sys.stdin.buffer.readline\nfirst=read(0)\na,b=map(int,read(3).split())\ntail=read()\nvalues=list(map(int,read(-2).split()))\nprint(first,a,b,tail,values)\n',
 'binary_then_text': 'import sys\na,b=map(int,sys.stdin.buffer.readline().split())\nc,d=map(int,sys.stdin.readline().split())\nprint(a,b,c,d)\n',
 'text_then_binary': 'import sys\na=list(map(int,sys.stdin.readline().split()))\nb=list(map(int,sys.stdin.buffer.readline().split()))\nprint(a,b)\n',
 'unicode_reader': 'import sys\na,b=map(int,sys.stdin.readline().split())\nprint(a,b)\n',
 'invalid_extra_binary': 'import sys\na,b=map(int,sys.stdin.buffer.readline().split())\nprint(a,b)\n',
 'helper_function': 'import sys\nread=sys.stdin.buffer.readline\ndef pair():\n a,b=map(int,read().split())\n return a+b\nprint(pair(),pair())\n',
 'pure_literal': 'a,b=map(int,"1 2".split())\nprint(a,b)\n',
}
INPUTS={
 'text_lines':'4 3\n5 -2 7 9\n0 4\n1 3\n2 2\n',
 'binary_alias_main':'4 3\r\n5 -2 7 9\r\n0 4\r\n1 3\r\n2 2\r\n',
 'text_eof_list':'1 2\n',
 'text_saved_line':'retained\n3 4\n',
 'binary_stored_map':'1 2 3\nretained\n',
 'binary_separator_reads':'3 4\nseparator called\n',
 'text_callback_reads':'3 4\n10\n20\n',
 'text_sizes':'1 2 suffix\n3 4\n',
 'binary_sizes':'1 2 suffix\n3 4\n',
 'binary_then_text':'1 2\n3 4\n',
 'text_then_binary':'1 2\n3 4\n',
 'unicode_reader':'１２\u2003-３\n',
 'invalid_extra_binary':'1 2 invalid\n',
 'helper_function':'1 2\n3 4\n',
}
KNOWN_GAPS={
 'binary_separator_reads':(4,'callee=reader_bytes'),
 'text_callback_reads':(3,'callee=reader_text'),
 'text_sizes':(3,"Source: 'read(0)'"),
}
# Keep alias failures visible, while independently exercising the supported
# canonical-member spellings with exactly the same callback/input effects.
CASES['direct_separator_reads']=CASES['binary_separator_reads'].replace('print(read())','print(sys.stdin.buffer.readline())')
CASES['direct_callback_reads']=CASES['text_callback_reads'].replace('int(read())','int(sys.stdin.readline())')
CASES['sized_plain_print']=CASES['text_sizes'].replace('print(repr(first),a,b,repr(tail),values)','print(first,a,b,tail,values,sep="|")')
for new,old in (('direct_separator_reads','binary_separator_reads'),('direct_callback_reads','text_callback_reads'),('sized_plain_print','text_sizes')):
    INPUTS[new]=INPUTS[old]
CASES['text_final_line']=CASES['text_eof_list']
INPUTS['text_final_line']='1 2'
CASES['binary_final_line']='import sys\na,b=map(int,sys.stdin.buffer.readline().split())\nprint(a,b)\n'
INPUTS['binary_final_line']='1 2'
CASES['binary_vertical_tab']=CASES['binary_final_line']
INPUTS['binary_vertical_tab']='1\v2\f\t \n'
CASES['helper_invalid']=CASES['helper_function']
INPUTS['helper_invalid']='1 invalid\n3 4\n'

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ReadlineIntegerBorrowTests(unittest.TestCase):
    cases=CASES
    inputs=INPUTS
    check=iterator_tests.IteratorExecutionTests.check
    def guard_or_check(self,name):
        result=transpile(CASES[name],TranspileOptions(integer='i64',filename='iterator_case.py',license='none'))
        if result.success:
            self.check(name)
        else:
            line,detail=KNOWN_GAPS[name]
            self.assertTrue(result.diagnostics)
            self.assertTrue(any(item.code=='E006'and item.line==line and detail in item.message
                                for item in result.diagnostics),result.diagnostics)
    def test_text_lines(self):self.check('text_lines')
    def test_binary_alias_main(self):self.check('binary_alias_main')
    def test_text_eof_list(self):self.check('text_eof_list')
    def test_binary_eof_unpack(self):self.check('binary_eof_unpack')
    def test_text_saved_line(self):self.check('text_saved_line')
    def test_binary_stored_map(self):self.check('binary_stored_map')
    def test_binary_separator_reads(self):self.guard_or_check('binary_separator_reads')
    def test_text_callback_reads(self):self.guard_or_check('text_callback_reads')
    def test_text_sizes(self):self.guard_or_check('text_sizes')
    def test_binary_sizes(self):self.check('binary_sizes')
    def test_binary_then_text(self):self.check('binary_then_text')
    def test_text_then_binary(self):self.check('text_then_binary')
    def test_unicode_reader(self):self.check('unicode_reader')
    def test_invalid_extra_binary(self):self.check('invalid_extra_binary')
    def test_helper_function(self):self.check('helper_function')
    def test_pure_literal(self):self.check('pure_literal')
    def test_direct_separator_reads(self):self.check('direct_separator_reads')
    def test_direct_callback_reads(self):self.check('direct_callback_reads')
    def test_sized_plain_print(self):self.check('sized_plain_print')
    def test_text_final_line(self):self.check('text_final_line')
    def test_binary_final_line(self):self.check('binary_final_line')
    def test_binary_vertical_tab(self):self.check('binary_vertical_tab')
    def test_helper_invalid(self):self.check('helper_invalid')
    def test_error_restoration_and_large_line_release(self):
        # A direct contract harness exercises recovery in the scoped helpers.
        # Python try/except currently chooses a different native frame path.
        reference='''import sys
for _ in range(8):
    try:
        a,b=map(int,sys.stdin.buffer.readline().split())
        print(a,b)
    except ValueError:print("error")
for _ in range(2):
    try:
        a,b=map(int,sys.stdin.readline().split())
        print(a,b)
    except ValueError:print("error")
'''
        data=b'x'*1100000+b'\n4 5\n\xff 6\n7\v8\n9\n10 11\n12 13 14 invalid\n15 16\ninvalid 19\n20 21'
        cp=subprocess.run([sys.executable,'-I','-S','-c',reference],input=data,capture_output=True,timeout=15)
        self.assertEqual(cp.returncode,0,cp.stderr)
        seed='import sys\na,b=map(int,sys.stdin.buffer.readline().split())\nvalues=list(map(int,sys.stdin.readline().split()))\nprint(a+b+sum(values))\n'
        result=transpile(seed,TranspileOptions(integer='i64',license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.rust_source.count('fn main()'),1)
        harness=r'''
fn reader_failure(message:String)->NativeError {
    native_at::<()>(Err(message),1,"<module>").unwrap_err()
}
fn byte_pair(input:&mut NativeInput)->Result<[NativeInt;2],NativeError>{
    input.with_byte_line(reader_failure,|line|{
        let words=NativeByteWords::new(line,None,-1).map_err(reader_failure)?;
        native_unpack_integer_words::<2,_,_,_>(words,|word|native_io_parse_bytes(word).map_err(reader_failure),reader_failure)
    })
}
fn text_pair(input:&mut NativeInput)->Result<[NativeInt;2],NativeError>{
    input.with_text_line(reader_failure,|line|{
        let words=NativeWords::new(line,None,-1).map_err(reader_failure)?;
        native_unpack_integer_words::<2,_,_,_>(words,|word|native_parse_integer(word).map_err(reader_failure),reader_failure)
    })
}
fn main(){
    let mut input=NativeInput::new();
    for index in 0..8 {
        match byte_pair(&mut input){Ok([a,b])=>println!("{} {}",a,b),Err(_)=>println!("error")}
        if index==0 {assert!(input.line.capacity()<1100000);}
    }
    for _ in 0..2 {
        match text_pair(&mut input){Ok([a,b])=>println!("{} {}",a,b),Err(_)=>println!("error")}
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='pytors-reader-recovery-')as directory:
            rust=Path(directory)/'main.rs'
            rust.write_text(result.rust_source.replace('fn main()','fn generated_entry()',1)+harness)
            binary=Path(directory)/'native'
            built=subprocess.run(['rustc','--edition=2021','-O',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],input=data,capture_output=True,timeout=15,env={**os.environ,'PATH':'/no-python-runtime'})
            self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(0,cp.stdout,b''))
    def test_invalid_utf8_binary_stays_bytes(self):
        source='import sys\na,b=map(int,sys.stdin.buffer.readline().split())\nprint(a,b)\n'
        filename='reader_case.py';data=b'\xff 2\n'
        cp=subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,filename],input=data,capture_output=True,timeout=10)
        self.assertNotEqual(cp.returncode,0)
        failure=json.loads(cp.stderr)
        result=transpile(source,TranspileOptions(integer='i64',filename=filename,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        with tempfile.TemporaryDirectory(prefix='pytors-byte-reader-')as directory:
            rust=Path(directory)/'main.rs';rust.write_text(result.rust_source);binary=Path(directory)/'native'
            built=subprocess.run(['rustc','--edition=2021','-O',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],input=data,capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
            self.assertEqual((ran.returncode,ran.stdout),(cp.returncode,cp.stdout))
            self.assertEqual(ran.stderr.decode().splitlines()[-1],failure['message'])
    def test_readline_does_not_implicitly_flush(self):
        source='import sys\nprint("pending")\na,b=map(int,sys.stdin.buffer.readline().split())\nprint(a+b)\n'
        result=transpile(source,TranspileOptions(integer='i64',license='none'))
        self.assertTrue(result.success,result.diagnostics)
        with tempfile.TemporaryDirectory(prefix='pytors-reader-pipe-')as directory:
            rust=Path(directory)/'main.rs';rust.write_text(result.rust_source);binary=Path(directory)/'native'
            built=subprocess.run(['rustc','--edition=2021','-O',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            child=PipeSession([str(binary)],{**os.environ,'PATH':'/no-python-runtime'})
            try:
                child.quiet()
                child.send(b'1 2\n')
                observed,error=child.finish()
                self.assertEqual(observed,b'pending\n3\n')
                self.assertEqual(error,b'')
            finally:child.close()
