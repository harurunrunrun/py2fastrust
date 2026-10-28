"""Generated-local liveness preserves effects, errors and destructor timing."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.rust_cleanup import cleanup_rust_source_with_report,cleanup_rust_source


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class RustCleanupTests(unittest.TestCase):
    def compare(self,source,arguments=((),),profiles=(False,)):
        report=cleanup_rust_source_with_report(source)
        self.assertFalse(report.retained,report.reason)
        self.assertEqual(cleanup_rust_source(report.source),report.source)
        with tempfile.TemporaryDirectory(prefix="pytors-rust-cleanup-")as directory:
            for release in profiles:
                programs=[]
                for label,text in (("before",source),("after",report.source)):
                    path=Path(directory)/(label+str(release)+".rs");path.write_text(text)
                    binary=path.with_suffix("")
                    built=subprocess.run(["rustc","--edition=2021",*(["-O"]if release else[]),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(built.returncode,0,built.stderr)
                    programs.append(binary)
                for args in arguments:
                    before,after=[subprocess.run([str(binary),*args],capture_output=True,text=True,timeout=10)for binary in programs]
                    self.assertEqual(after.stdout,before.stdout)
                    self.assertEqual(after.returncode,before.returncode,after.stderr+before.stderr)
        return report

    def test_copy_dependency_chains_and_cycles_have_no_observable_sink(self):
        source='''#![allow(unused_variables,unused_assignments,unused_mut)]
type Number=i64;
fn main(){
 let mut first:Option<Number>;
 let mut second:Option<Number>;
 first=None;
 second=first;
 first=second;
 for index in 0..3 {second=Some(index);}
 let spare=(1_i128 as Number);
 println!("done");
}
'''
        report=self.compare(source)
        for name in ("first","second","spare"):
            self.assertIn(name,report.removed_locals)
            self.assertNotIn(name,report.source)

    def test_branch_and_zero_trip_effects_stay_in_their_original_positions(self):
        source='''#![allow(unused_variables,unused_assignments,unused_mut)]
fn tick()->i64{print!("tick|");7}
fn main(){
 let mut ignored:i64;
 if std::env::args().len()>1 {ignored=tick();}else{ignored=0;}
 for _ in 0..0 {ignored=tick();}
 println!("end");
}
'''
        report=self.compare(source,arguments=((),("enabled",)))
        self.assertNotIn("ignored",report.source)
        self.assertEqual(report.wildcard_evaluations,2)
        self.assertNotIn("else",report.source)

    def test_generic_parse_keeps_the_discarded_values_type_context(self):
        source='''#![allow(unused_variables)]
fn main()->Result<(),Box<dyn std::error::Error>>{
 let text=std::env::args().nth(1).unwrap_or("4".into());
 let parsed:u8=text.parse()?;
 println!("after");Ok(())
}
'''
        report=self.compare(source,arguments=(("4",),("bad",),("256",)))
        self.assertIn("let _:u8",report.source)
        self.assertNotIn("parsed",report.source)

    def test_discarded_constraints_on_retained_producers_are_preserved(self):
        sources=[
            'fn main(){let produced="23".parse().unwrap();let ignored:u8=produced;println!("done");}',
            'fn main(){let produced="23".parse().unwrap();let ignored:(u8,u8)=(produced,4);println!("done");}',
            'fn main(){let produced="23".parse().unwrap();let ignored:Option<u8>=Some(produced);println!("done");}',
            'fn main(){let mut ignored:Option<i64>;if false {for index in 0..10_000_000_000 {ignored=Some(index);}}println!("done");}',
            'fn main(){let index:i64=1;if false {for index in 0..10_000_000_000 {let ignored:i64=index;}}println!("done");}',
        ]
        for source in sources:
            with self.subTest(source=source):
                report=self.compare(source,profiles=(False,True))
                self.assertNotIn("ignored",report.source)
                self.assertGreater(report.wildcard_evaluations,0)

    def test_copy_rhs_panics_are_preserved_in_both_build_profiles(self):
        source='''#![allow(unused_variables)]
fn one()->i64{print!("one|");1}
fn main(){let unused:i64=i64::MAX+one();println!("after");}
'''
        report=self.compare(source,profiles=(False,True))
        self.assertNotIn("unused:i64",report.source)
        self.assertIn("i64::MAX+one()",report.source)

    def test_a_cast_does_not_hide_following_effectful_operators(self):
        source='''#![allow(unused_variables)]
fn side()->i64{print!("side|");9}
fn main(){let base:u8=1;let discarded:i64=base as i64+side();println!("done");}
'''
        report=self.compare(source)
        self.assertNotIn("discarded",report.source)
        self.assertIn("side()",report.source)

    def test_diverging_copy_initializers_keep_control_transfers(self):
        sources=['''#![allow(unused_variables,unreachable_code)]
fn main(){print!("before|");let ignored:i64=return;println!("after");}
''','''#![allow(unused_variables,unreachable_code)]
fn main(){for _ in 0..3 {print!("before|");let ignored:i64=break;print!("body|");}println!("end");}
''','''#![allow(unused_variables,unreachable_code)]
fn main(){for _ in 0..3 {print!("before|");let ignored:i64=continue;print!("body|");}println!("end");}
''']
        for source in sources:
            self.compare(source,profiles=(False,True))

    def test_noncopied_guards_and_extended_borrow_lifetimes_are_retained(self):
        source='''#![allow(unused_variables)]
struct Guard(&'static str);
impl Drop for Guard{fn drop(&mut self){print!("drop:{}|",self.0);}}
fn make(label:&'static str)->Guard{print!("make:{}|",label);Guard(label)}
fn main(){
 let held:Guard=make("held");
 let reference:&Guard=&make("reference");
 let pair:(&Guard,u64)=(&make("pair"),3);
 let spare:u64=17;
 println!("body");
}
'''
        report=self.compare(source)
        for name in ("held","reference","pair"):
            self.assertNotIn(name,report.removed_locals)
        self.assertIn("spare",report.removed_locals)

    def test_copy_result_of_a_temporary_borrow_preserves_drop_order(self):
        source='''#![allow(unused_variables)]
struct Guard(u64);
impl Drop for Guard{fn drop(&mut self){print!("drop|");}}
fn main(){let unused:u64=(&Guard(7)).0;println!("body");}
'''
        self.compare(source)

    def test_shadowed_local_and_unknown_alias_types_remain_conservative(self):
        source='''#![allow(unused_variables,non_camel_case_types)]
type NativeInt=String;
fn main(){
 let unknown:NativeInt="kept".into();
 let shadowed:u64=1;
 {let shadowed:String="inner".into();println!("{}",shadowed);}
 println!("body");
}
'''
        report=self.compare(source)
        self.assertNotIn("unknown",report.removed_locals)
        self.assertNotIn("shadowed",report.removed_locals)

    def test_format_capture_and_unknown_macro_namespace_observations_are_kept(self):
        source='''#![allow(unused_variables)]
fn plain(){let answer:i64=42;let spare:u64=9;println!("{answer}");}
fn main(){
 plain();let hidden:i64=7;
 macro_rules! observe{()=>{println!("{}",hidden)}}
 observe!();
}
'''
        report=self.compare(source)
        self.assertIn("spare",report.removed_locals)
        self.assertNotIn("answer",report.removed_locals)
        self.assertNotIn("hidden",report.removed_locals)

    def test_literals_comments_and_stringified_tokens_are_preserved(self):
        source='''#![allow(unused_variables)]
const TEXT:&str=r###"else { } // string contents

raw body"###;
fn main(){
 // Keep this comment exactly.
 let spare:u64=9; /* Keep this comment too. */
 let tokens=stringify!(if true {} else {});
 if false {} else {/* Branch comment. */}
 println!("{}|{}",TEXT,tokens);
}
'''
        report=self.compare(source)
        self.assertEqual(report.removed_else,1)
        for text in ('r###"else { } // string contents\n\nraw body"###',
                     '// Keep this comment exactly.','/* Keep this comment too. */',
                     '/* Branch comment. */','stringify!(if true {} else {})'):
            self.assertIn(text,report.source)

    def test_shadowed_some_is_still_called_for_a_discarded_copy_value(self):
        source='''#![allow(unused_variables,non_snake_case)]
fn Some(value:i64)->Option<i64>{print!("call|");std::option::Option::Some(value)}
fn main(){let discarded:Option<i64>;discarded=Some(3);println!("done");}
'''
        report=self.compare(source)
        self.assertNotIn("discarded",report.source)
        self.assertIn("Some(3)",report.source)
        self.assertEqual(report.wildcard_evaluations,1)

    def test_imported_constructor_and_shadowed_primitive_alias_are_not_guessed(self):
        source='''#![allow(unused_variables,non_snake_case)]
mod effects {pub fn effect(value:i64)->Option<i64>{print!("call|");Some(value)}}
use effects::effect as Some;
fn main(){let discarded:Option<i64>=Some(3);println!("done");}
'''
        report=self.compare(source)
        self.assertNotIn("discarded",report.source)
        self.assertIn("Some(3)",report.source)
        source='''#![allow(unused_variables,non_camel_case_types)]
mod effects {pub struct Guard;impl Drop for Guard{fn drop(&mut self){print!("drop|");}}}
fn main(){use effects::Guard as i64;let held:i64=effects::Guard;println!("body");}
'''
        report=self.compare(source)
        self.assertNotIn("held",report.removed_locals)

    def test_source_observing_macros_and_attributes_fail_closed(self):
        sources=['fn main(){let spare:i64=3;println!("{}",line!());}',
                 '#[unknown_attribute] fn main(){let spare:i64=3;}',
                 'fn main(){let r#Some=|x:i64|{print!("effect");Some(x)};let spare:Option<i64>=Some(3);}']
        for source in sources:
            with self.subTest(source=source):
                report=cleanup_rust_source_with_report(source)
                self.assertTrue(report.retained)
                self.assertEqual(report.source,source)

    def test_generic_type_parameter_does_not_use_a_same_named_copy_alias(self):
        source='''#![allow(unused_variables,dead_code)]
type T=i64;
struct Guard;
impl Drop for Guard{fn drop(&mut self){println!("drop");}}
fn consume<T>(value:T){let held:T=value;println!("body");}
fn main(){consume(Guard);}
'''
        report=self.compare(source)
        self.assertNotIn("held",report.removed_locals)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class GeneratedLocalCleanupTests(unittest.TestCase):
    def test_unused_input_and_failing_arithmetic_are_still_evaluated(self):
        cases=[("n=int(input())\nprint(7)\n",("12\n","bad\n","\n","")),
               ("unused=1//int(input())\nprint('after')\n",("2\n","0\n","bad\n"))]
        with tempfile.TemporaryDirectory(prefix="pytors-unused-input-")as directory:
            for index,(source,inputs)in enumerate(cases):
                for mode in ("i64","i128","bigint"):
                    result=transpile(source,TranspileOptions(integer=mode,filename="unused.py"))
                    self.assertTrue(result.success,result.diagnostics)
                    path=Path(directory)/(f"case{index}_{mode}.rs");path.write_text(result.rust_source);binary=path.with_suffix("")
                    built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data in inputs:
                        expected=subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=10)
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,
                                              env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.stdout,expected.stdout)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                        if actual.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],expected.stderr.splitlines()[-1].split(":")[0])


if __name__=="__main__":unittest.main()
