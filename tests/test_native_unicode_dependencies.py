"""Required Unicode selection keeps compiled dependencies and no-opt helpers."""
from importlib.resources import files
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust.native_unicode_dependencies import select_unicode_dependencies
from py2fastrust.native_notices import retain_native_notices
from py2fastrust.rust_pruning import _lex,prune_rust_source_with_report


TABLE='const NATIVE_PRED_TABLE_ALPHA:&[(u32,u32)]=&[(65,90),(97,122)];\n'


class UnicodeDependencyTests(unittest.TestCase):
    def equal_execution(self,before,after):
        if not shutil.which('rustc'):return
        with tempfile.TemporaryDirectory(prefix='pytors-unicode-dependencies-')as directory:
            outputs=[]
            for index,source in enumerate((before,after)):
                path=Path(directory,str(index)+'.rs');path.write_text(source)
                for optimized in (False,True):
                    binary=path.with_suffix('.opt'if optimized else'.debug')
                    build=subprocess.run(['rustc','--edition=2021','--crate-name','dependencies',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True)
                    self.assertEqual(build.returncode,0,build.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True)
                    stderr=actual.stderr.replace(str(path),'<generated>')
                    stderr=re.sub(r"(thread '[^']+') \(\d+\)",r'\1 (PID)',stderr)
                    outputs.append((actual.returncode,actual.stdout,stderr))
            self.assertEqual(outputs,[outputs[0]]*4)

    def test_dead_table_and_reverse_callers_are_removed_without_other_pruning(self):
        unrelated='// keep this unrelated helper exactly\nfn unrelated() -> u32 { 7 }\nconst OTHER:[u32;2]=[8,9];\n'
        source=TABLE+'fn property()->usize{NATIVE_PRED_TABLE_ALPHA.len()}\nfn wrapper()->usize{property()}\nconst POINTER:fn()->usize=wrapper;\n'+unrelated+'fn main(){println!("ok");}\n'
        result=select_unicode_dependencies(source)
        self.assertNotIn('const NATIVE_PRED_TABLE_ALPHA',result)
        for word in ('fn property','fn wrapper','const POINTER'):self.assertNotIn(word,result)
        self.assertIn(unrelated,result)
        self.equal_execution(source,result)

    def test_unused_local_tables_and_associated_reverse_callers_are_removed(self):
        source='''struct Number;
impl Number {
 fn digit()->u32{const ZEROES:&[u32]=&[48,1632];ZEROES[0]}
 fn parse()->u32{Self::digit()}
 fn ordinary()->u32{7}
}
fn dead()->u32{Number::parse()}
fn main(){println!("{}",Number::ordinary());}
'''
        result=select_unicode_dependencies(source)
        self.assertNotIn('const ZEROES',result)
        self.assertNotIn('fn digit',result)
        self.assertNotIn('fn parse',result)
        self.assertNotIn('fn dead',result)
        self.assertIn('fn ordinary()->u32{7}',result)
        self.equal_execution(source,result)

    def test_live_functions_and_static_initializers_keep_real_data(self):
        for main in ('fn main(){println!("{}",property());}',
                     'static COUNT:usize=property();fn main(){println!("{}",COUNT);}'):
            source=TABLE+'const fn property()->usize{NATIVE_PRED_TABLE_ALPHA.len()}\n'+main
            self.assertEqual(select_unicode_dependencies(source),source)
            self.equal_execution(source,select_unicode_dependencies(source))

    def test_trait_calls_and_implicit_drop_keep_their_data(self):
        sources=(TABLE+'''struct Text;
trait Show{fn show(&self)->usize;}
impl Show for Text{fn show(&self)->usize{NATIVE_PRED_TABLE_ALPHA.len()}}
fn main(){println!("{}",Text.show());}
''',TABLE+'''struct Text;
impl Drop for Text{fn drop(&mut self){println!("{}",NATIVE_PRED_TABLE_ALPHA.len());}}
fn main(){let _value=Text;println!("before");}
''')
        for source in sources:
            self.assertEqual(select_unicode_dependencies(source),source)
            self.equal_execution(source,select_unicode_dependencies(source))

    def test_dead_trait_and_owner_references_are_removed_coherently(self):
        source=TABLE+'''struct Text;
trait Show{fn show(&self)->usize;}
impl Show for Text{fn show(&self)->usize{NATIVE_PRED_TABLE_ALPHA.len()}}
fn dead(value:Text)->usize{value.show()}
fn unrelated()->u32{9}
fn main(){println!("ready");}
'''
        result=select_unicode_dependencies(source)
        self.assertNotIn('NATIVE_PRED_TABLE_ALPHA',result)
        self.assertNotIn('struct Text',result)
        self.assertNotIn('fn dead',result)
        self.assertIn('fn unrelated()->u32{9}',result)
        self.equal_execution(source,result)

    def test_dead_trait_selection_closes_empty_inherent_wrappers(self):
        for body in ('fn spare(&self){}',''):
            source='struct S;impl S{'+body+'}impl Default for S{fn default()->Self{const TEXT_PRINTABLE:&[(u32,u32)]=&[(1,2)];let _=TEXT_PRINTABLE;S}}fn main(){println!("ok");}'
            result=select_unicode_dependencies(source)
            self.assertNotIn('struct S',result)
            self.assertNotIn('impl S',result)
            self.equal_execution(source,result)

    def test_literal_words_and_license_shaped_values_are_not_references(self):
        license=files('py2fastrust').joinpath('stdlib','UNICODE_LICENSE.txt').read_text()
        source=TABLE+'fn dead()->usize{NATIVE_PRED_TABLE_ALPHA.len()}\nfn main(){let value=r####"'+license+'\nZEROES NATIVE_PRED_TABLE_ALPHA"####;println!("{}",value);}'
        result=select_unicode_dependencies(source)
        self.assertNotIn('const NATIVE_PRED_TABLE_ALPHA',result)
        literals=lambda text:[token.text for token in _lex(text)[0]if token.text.startswith(('"','r"','r#'))]
        self.assertEqual(literals(source),literals(result))
        self.equal_execution(source,result)

    def test_named_format_captures_include_raw_and_escaped_templates(self):
        for template in ('"{NATIVE_PRED_TABLE_ALPHA:?}"','r#"{NATIVE_PRED_TABLE_ALPHA:?}"#',
                         '"{{{NATIVE_PRED_TABLE_ALPHA:?}}}"','"\\x7bNATIVE_PRED_TABLE_ALPHA:?}"',
                         '"{\\u{4e}ATIVE_PRED_TABLE_ALPHA:?}"'):
            source=TABLE+'fn main(){println!('+template+');}'
            self.assertEqual(select_unicode_dependencies(source),source)
            self.equal_execution(source,select_unicode_dependencies(source))

    def test_opaque_missing_main_and_protected_definitions_fail_closed(self):
        sources=(TABLE+'macro_rules! hidden{()=>{NATIVE_PRED_TABLE_ALPHA.len()}}fn main(){}',
                 TABLE+'pub fn exported()->usize{NATIVE_PRED_TABLE_ALPHA.len()}fn main(){}',
                 TABLE+'fn no_main()->usize{NATIVE_PRED_TABLE_ALPHA.len()}')
        for source in sources:self.assertEqual(select_unicode_dependencies(source),source)

    def test_static_members_with_the_same_name_have_distinct_owners(self):
        source='''struct A;struct B;
impl A{fn parse()->u32{const ZEROES:&[u32]=&[48];ZEROES[0]}}
impl B{fn parse()->u32{7}}
fn main(){println!("{}",B::parse());}
'''
        result=select_unicode_dependencies(source)
        self.assertNotIn('const ZEROES',result)
        self.assertIn('impl B{fn parse()->u32{7}}',result)
        self.equal_execution(source,result)

    def test_static_parse_is_not_a_string_dot_parse_dependency(self):
        source='''struct Int;
impl Int{fn parse()->u32{const ZEROES:&[u32]=&[48];ZEROES[0]}}
fn main(){let _integer=Int;println!("{}","12".parse::<i32>().unwrap());}
'''
        result=select_unicode_dependencies(source)
        self.assertNotIn('const ZEROES',result)
        self.assertIn('"12".parse::<i32>()',result)
        self.equal_execution(source,result)

    def test_all_standard_format_macros_keep_implicit_captures(self):
        source='const TEXT_PRINTABLE:&[(u32,u32)]=&[(65,90)];fn main(){unimplemented!("{TEXT_PRINTABLE:?}");}'
        self.assertEqual(select_unicode_dependencies(source),source)
        self.equal_execution(source,select_unicode_dependencies(source))

    def test_macro_comparisons_are_not_generic_angle_groups(self):
        source=TABLE+'fn dead()->usize{NATIVE_PRED_TABLE_ALPHA.len()}fn main(){assert!(2<3);println!("ok");}'
        result=select_unicode_dependencies(source)
        self.assertNotIn('NATIVE_PRED_TABLE_ALPHA',result)
        self.equal_execution(source,result)

    def test_function_local_type_aliases_and_shadowed_global_aliases_keep_data(self):
        prefix='struct Int;impl Int{fn parse()->u32{const ZEROES:&[u32]=&[48];ZEROES[0]}}'
        sources=(prefix+'fn main(){type Alias=Int;println!("{}",Alias::parse());}',
                 prefix+'type Alias=u32;fn main(){type Alias=Int;println!("{}",Alias::parse());}',
                 prefix+'struct Alias;fn main(){use crate::Int as Alias;println!("{}",Alias::parse());}')
        for source in sources:
            self.assertEqual(select_unicode_dependencies(source),source)
            self.equal_execution(source,select_unicode_dependencies(source))

    def test_local_anonymous_trait_import_does_not_disable_other_selection(self):
        source=TABLE+'fn dead()->usize{NATIVE_PRED_TABLE_ALPHA.len()}fn main(){use std::fmt::Write as _;let mut value=String::new();write!(&mut value,"{}",7).unwrap();println!("{}",value);}'
        result=select_unicode_dependencies(source)
        self.assertNotIn('const NATIVE_PRED_TABLE_ALPHA',result)
        self.equal_execution(source,result)

    def test_generic_pruner_default_behavior_is_unchanged(self):
        source=TABLE+'fn unused()->usize{NATIVE_PRED_TABLE_ALPHA.len()}fn unrelated()->u32{7}fn main(){println!("ok");}'
        ordinary=prune_rust_source_with_report(source)
        self.assertFalse(ordinary.retained,ordinary.reason)
        self.assertNotIn('fn unrelated',ordinary.source)
        selected=select_unicode_dependencies(source)
        self.assertIn('fn unrelated',selected)
        self.assertNotIn('NATIVE_PRED_TABLE_ALPHA',selected)

    def test_synthetic_notice_source_without_main_keeps_its_license(self):
        result=retain_native_notices('const ZEROES:&[u32]=&[48];')
        self.assertIn('// UNICODE LICENSE V3',result)
        self.assertIn('const ZEROES',result)


if __name__=='__main__':unittest.main()
