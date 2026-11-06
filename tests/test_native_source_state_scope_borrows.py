"""Private state entries share the established execution-context ABI proof."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust.native_scope_borrows import apply


NAMES=('class_state_function_4','class_state_enter_2','class_state_construct_1')
HEADER='use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type ClassResult<T>=Result<T,()>;'


def program(name,body='Ok(*class_scope.control.clone())',result='i64',extra='',qualifier=''):
    return(HEADER+extra+qualifier+'fn '+name+'(class_scope:ClassScope)->ClassResult<'+result+'>{'+body+'}'
           'fn main(){let scope=ClassScope{control:Rc::new(9)};println!("{}",'+name+'(scope.clone()).unwrap());}')


class NativeSourceStateScopeProofTests(unittest.TestCase):
    def test_each_private_family_uses_the_existing_borrow_proof(self):
        for name in NAMES:
            with self.subTest(name=name):
                rewritten=apply(program(name))
                self.assertIn('fn '+name+'(class_scope:&ClassScope)',rewritten)
                self.assertIn(name+'(&scope)',rewritten)
                self.assertNotIn(name+'(scope.clone())',rewritten)

    def test_address_taken_entries_retain_their_owned_abi(self):
        for name in NAMES:
            source=(HEADER+'fn '+name+'(class_scope:ClassScope)->ClassResult<i64>{Ok(*class_scope.control.clone())}'
                    'fn main(){let callback:fn(ClassScope)->ClassResult<i64>='+name+';'
                    'println!("{}",callback(ClassScope{control:Rc::new(9)}).unwrap());}')
            with self.subTest(name=name):self.assertEqual(apply(source),source)

    def test_move_and_unproved_owned_consumers_retain_their_abi(self):
        for name in NAMES:
            cases=(program(name,'let callback=move||*class_scope.control;Ok(callback())'),
                   program(name,'Ok(consume(class_scope))',extra='fn consume(scope:ClassScope)->i64{*scope.control}'))
            for source in cases:
                with self.subTest(name=name,source=source):self.assertEqual(apply(source),source)

    def test_suspension_owned_fields_and_drop_do_not_gain_a_borrow(self):
        for name in NAMES:
            future=program(name,'Ok(*class_scope.control.clone())',qualifier='async ')
            owned=(HEADER.replace('control:Rc<i64>','control:Vec<i64>')+'fn '+name+
                   '(class_scope:ClassScope)->ClassResult<Vec<i64>>{Ok(class_scope.control)}fn main(){}')
            dropping=program(name,extra='type Alias=ClassScope;impl Drop for Alias{fn drop(&mut self){}}')
            for source in (future,owned,dropping):
                with self.subTest(name=name,source=source):self.assertEqual(apply(source),source)

    def test_unregistered_names_are_not_physical_abi_candidates(self):
        source=program('arbitrary_state_function_4')
        self.assertEqual(apply(source),source)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_original_and_borrowed_private_entries_execute_identically(self):
        with tempfile.TemporaryDirectory(prefix='pytors-state-scope-')as temporary:
            directory=Path(temporary)
            for index,name in enumerate(NAMES):
                original=program(name)
                for suffix,code in [('owned',original),('borrowed',apply(original))]:
                    with self.subTest(name=name,version=suffix):
                        rust=directory/(str(index)+'_'+suffix+'.rs');binary=rust.with_suffix('')
                        rust.write_text(code)
                        built=subprocess.run(['rustc','--edition=2021','--crate-name','state_scope_tests',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                        self.assertEqual(built.returncode,0,built.stderr)
                        run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                        self.assertEqual((run.returncode,run.stdout,run.stderr),(0,'9\n',''))
