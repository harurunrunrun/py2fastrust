"""Conservative Rust definitions are removed without altering retained bytes."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.rust_pruning import prune_rust_source,prune_rust_source_with_report


class RustPruningTests(unittest.TestCase):
    def test_function_type_cycles_and_all_comment_bytes_are_preserved(self):
        source='''// LICENSE: sample\n// Original Python: import sys\n#![allow(dead_code)]
struct Dead { unused:i32 }
impl Dead { fn new()->Self {Self{unused:3}} }
// This comment must survive the removed function.
#[inline]
fn dead_one()->i32 { /* nested /* original */ notice */ dead_two() }
fn dead_two()->i32 { // internal comment\n dead_one() }
const ANSWER:i32=42;
fn used()->i32 {ANSWER}
fn main(){println!("{}",used());}
'''
        result=prune_rust_source_with_report(source)
        self.assertIsNone(result.reason)
        self.assertLess(result.after_bytes,result.before_bytes)
        self.assertNotIn('fn dead_one',result.source);self.assertNotIn('fn dead_two',result.source)
        self.assertNotIn('struct Dead',result.source);self.assertNotIn('impl Dead',result.source)
        self.assertIn('Dead::new',result.removed_functions)
        for comment in ['// LICENSE: sample\n','// Original Python: import sys\n','// This comment must survive the removed function.\n','/* nested /* original */ notice */','// internal comment\n']:
            self.assertIn(comment,result.source)
        self.assertIn('const ANSWER:i32=42;',result.source)
        self.assertIn('fn used()->i32 {ANSWER}',result.source)
        self.assertIn('fn main(){println!("{}",used());}',result.source)
    def test_implicit_named_format_captures_and_raw_literals(self):
        source='''const ANSWER:i32=42;
const WIDTH:usize=5;
fn dead()->i32 {7}
fn main(){let s=r###"literal { } // \" text"###;println!("{ANSWER:WIDTH$}|{s}");}
'''
        result=prune_rust_source(source)
        self.assertIn('const ANSWER',result);self.assertIn('const WIDTH',result)
        self.assertIn('r###"literal { } // " text"###',result)
        self.assertNotIn('fn dead',result)
    def test_documentation_and_public_exports_remain_attached_to_items(self):
        source='''/// Original documentation.
fn documented()->i32 {7}
pub fn public_entry()->i32 {documented()}
fn dead()->i32{9}
fn main(){}
'''
        result=prune_rust_source(source)
        self.assertIn('/// Original documentation.\nfn documented()',result)
        self.assertIn('pub fn public_entry()',result)
        self.assertNotIn('fn dead',result)
    def test_documented_impl_and_empty_impl_remain_valid(self):
        source='''struct Documented;
/// Keep this implementation documentation.
impl Documented {fn member()->usize{7}}
struct Empty;
/// Keep an empty implementation too.
impl Empty {}
fn main(){}
'''
        result=prune_rust_source(source)
        self.assertIn('/// Keep this implementation documentation.\nimpl Documented',result)
        self.assertIn('fn member()',result)
        self.assertIn('/// Keep an empty implementation too.\nimpl Empty {}',result)
        self.assertIn('struct Empty;',result)

    def test_unknown_macros_attributes_linkage_and_identifiers_fail_closed(self):
        sources=[
            'macro_rules! m {()=>{helper()}} fn helper(){} fn main(){m!()}',
            'fn main(){unknown!();}',
            '#[no_mangle] pub extern "C" fn external(){} fn main(){}',
            '#[custom_attribute] fn hidden(){} fn main(){}',
            '#[derive(CustomDerive)] struct Hidden; fn main(){}',
            'fn main(){println!(concat!("{AN","SWER}"));} const ANSWER:i32=3;',
            'fn main(){println!(env!("FORMAT"));} const ANSWER:i32=3;',
            'fn r#type(){} fn main(){r#type()}',
            'impl<T:for<\'a> Fn(&\'a str)> Holder<T>{fn f(){}} fn main(){}',
            'fn library_only(){}',
        ]
        for source in sources:
            with self.subTest(source=source):
                result=prune_rust_source_with_report(source)
                self.assertTrue(result.retained,result.reason);self.assertEqual(result.source,source)
    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_trait_defaults_aliases_blankets_drop_and_inherent_function_pointers(self):
        source='''#![allow(dead_code)]
use std::sync::atomic::{AtomicUsize,Ordering};
static DROPS:AtomicUsize=AtomicUsize::new(0);
fn value()->usize{7}
struct Inner;
impl std::fmt::Debug for Inner {fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{write!(f,"{}",value())}}
#[derive(Debug)]
struct Live{inner:Inner}
impl Live {fn new()->Self{Self{inner:Inner}} fn number(&self)->usize{value()} fn unused(&self)->usize{999}}
impl Drop for Live {fn drop(&mut self){DROPS.fetch_add(1,Ordering::SeqCst);}}
struct Dead;
impl Dead {fn new()->Self{Self} fn number(&self)->usize{999}}
trait Answer {fn answer(&self)->usize;fn defaulted(&self)->usize{self.answer()+1}}
struct Base(usize);
type Alias=Base;
impl Answer for Alias{fn answer(&self)->usize{self.0}}
impl Alias {fn increase(&mut self){self.0+=1;}}
trait ArrayAnswer{fn array_answer(&self)->usize;}
impl<T> ArrayAnswer for [T;1]{fn array_answer(&self)->usize{value()}}
struct Holder<F:Fn()->usize>(F);
impl<F:Fn()->usize> Holder<F>{fn call(&self)->usize{(self.0)()}}

thread_local!{static FLAG:std::cell::Cell<usize>=const{std::cell::Cell::new(3)};}
fn main(){
 {let x=Live::new();let pointer:fn(&Live)->usize=Live::number;println!("{:?} {}",x,pointer(&x));}
 let mut x=Base(2);x.increase();println!("{} {} {}",x.defaulted(),[1].array_answer(),DROPS.load(Ordering::SeqCst));
 FLAG.with(|flag|println!("{}",flag.get()));
 println!("{}",Holder(||value()).call());
}
'''
        result=prune_rust_source_with_report(source)
        self.assertIsNone(result.reason)
        self.assertNotIn('struct Dead',result.source);self.assertNotIn('fn unused',result.source)
        with tempfile.TemporaryDirectory(prefix='pytors-prune-traits-')as directory:
            path=Path(directory)/'main.rs';path.write_text(result.source);binary=path.with_suffix('')
            built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stderr)
            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual(actual.returncode,0,actual.stderr);self.assertEqual(actual.stdout,'Live { inner: 7 } 7\n4 7 1\n3\n7\n')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class GeneratedRustPruningTests(unittest.TestCase):
    def test_generated_native_samples_keep_semantics_and_remove_helpers(self):
        cases=[('print(1+2)\n',''),('n=int(input())\nprint(n*n)\n','12\n'),('x={1:2}\nprint(x[1])\n','')]
        with tempfile.TemporaryDirectory(prefix='pytors-prune-samples-')as directory:
            for index,(source,data)in enumerate(cases):
                # Keep an unpruned fixture even when transpile prunes by default.
                with patch('py2fastrust.rust_pruning.prune_rust_source',lambda rust:rust):
                    original=transpile(source)
                self.assertTrue(original.success,original.diagnostics)
                result=prune_rust_source_with_report(original.rust_source);self.assertIsNone(result.reason)
                self.assertNotIn('fn native_pow(',result.source)
                self.assertLess(result.after_bytes,result.before_bytes)
                self.assertEqual(original.rust_source.count('// LICENSE:'),result.source.count('// LICENSE:'))
                for text in ['// LICENSE:','The licence','Original Python source']:
                    if text in original.rust_source:self.assertIn(text,result.source)
                path=Path(directory)/f'case{index}.rs';path.write_text(result.source,encoding='utf-8');binary=path.with_suffix('')
                built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies'})
                expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=15)
                self.assertEqual(actual.returncode,expected.returncode,actual.stderr);self.assertEqual(actual.stdout,expected.stdout)
    def test_native_output_is_pruned_and_pruning_is_idempotent(self):
        source='n=int(input())\nprint(n*n)\n'
        result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('fn native_pow(',result.rust_source)
        self.assertNotIn('fn native_shl(',result.rust_source)
        self.assertEqual(prune_rust_source(result.rust_source),result.rust_source)
    def test_all_integer_modes_and_build_profiles_standalone(self):
        source='n=int(input())\nprint(n*n)\n'
        environment={**os.environ,'PATH':'/pytors-no-runtime-dependencies'}
        with tempfile.TemporaryDirectory(prefix='pytors-prune-profiles-')as directory:
            for integer in ['i64','i128','bigint']:
                original=transpile(source,TranspileOptions(integer=integer));self.assertTrue(original.success,original.diagnostics)
                result=prune_rust_source_with_report(original.rust_source);self.assertIsNone(result.reason)
                for optimized in [False,True]:
                    with self.subTest(integer=integer,optimized=optimized):
                        path=Path(directory)/(integer+('_optimized'if optimized else'_debug')+'.rs');path.write_text(result.source,encoding='utf-8');binary=path.with_suffix('')
                        command=['rustc','--edition=2021',str(path),'-o',str(binary)]+(['-O']if optimized else[])
                        built=subprocess.run(command,capture_output=True,text=True,timeout=180)
                        self.assertEqual(built.returncode,0,built.stderr)
                        for data in ['12\n','-3\n','0\n']:
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=15,env=environment)
                            expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=15)
                            self.assertEqual(actual.returncode,expected.returncode,actual.stderr);self.assertEqual(actual.stdout,expected.stdout)
