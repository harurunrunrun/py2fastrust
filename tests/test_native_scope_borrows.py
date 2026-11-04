"""Borrowed native contexts retain module, callback and exception lifetimes."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from py2fastrust.native_scope_borrows import apply
import test_native_lambda_callbacks as helpers


CASES={
    'call_chain': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef use(box,n):return box.plus(n)\ndef make(n):return Box(n)\nprint(use(make(7),5))\n',
    'returned_closure': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef make(n):\n box=Box(n)\n def add(value):return box.plus(value)\n return add\nf=make(7)\nprint(f(3),f(8))\n',
    'closure_module_builtin': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\nfrom math import isqrt\ndef make(n):\n def calc(value):return isqrt(value)+n\n return calc\nprint(make(4)(81))\n',
    'nested_callbacks': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef transform(box,values):return list(map(lambda x:box.plus(x),values))\nprint(transform(Box(3),[2,4,8]))\n',
    'recursive_mixed_stack': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef rec(box,n):\n if n:return rec(box,n-1)+1\n return box.plus(0)\nprint(rec(Box(4),12))\n',
    'error_frames': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef divide(box,n):return box.value//n\ndef outer(box):return divide(box,0)\nprint(outer(Box(4)))\n',
    'with_returned_closure': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\nclass Guard:\n def __enter__(self):return self\n def __exit__(self,t,v,tb):print("exit");return False\ndef make(n):\n with Guard():\n  box=Box(n)\n  return lambda value:box.plus(value)\nprint(make(7)(4))\n',
    'mutable_default_callback': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef build():\n box=Box(5)\n def f(n,target=box):return target.plus(n)\n box.value=9\n return f\nf=build()\nprint(f(3))\n',
    'bound_method_return': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef build(n):return Box(n).plus\nf=build(8)\nprint(f(2),f(-3))\n',
    'lambda_return_value': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef build(n):return(lambda value:Box(value+n))\nf=build(9)\nprint(f(3).value)\n',
    'constructor_error': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\nclass Bad:\n def __init__(self,n):self.value=12//n\ndef build(n):return Bad(n)\nprint(build(0).value)\n',
    'exit_cleanup': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\nimport sys\nclass Guard:\n def __enter__(self):return self\n def __exit__(self,t,v,tb):print("cleanup");return False\ndef finish(box):\n print(box.value)\n sys.exit(0)\nwith Guard():finish(Box(12))\n',
    'recursive_leaf_constructor': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef rec(n):\n if n:return rec(n-1)\n return Box(9)\nprint(rec(20).plus(3))\n',
    'iterable_callable_lifetime': 'class Box:\n def __init__(self,value):self.value=value\n def plus(self,n):return self.value+n\ndef build(n):\n box=Box(n)\n return map(lambda x:box.plus(x),range(4))\nprint(list(build(5)))\n',
}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeScopeBorrowTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise


def install_case(name,source):
    def test(self):
        self.exercise(source)
    test.__name__="test_"+name
    setattr(NativeScopeBorrowTests,test.__name__,test)


for name,source in CASES.items():
    install_case(name,source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeScopePhysicalLifetimeTests(unittest.TestCase):
    def exercise(self,source,expected,changed=False):
        rewritten=apply(source)
        self.assertEqual(rewritten!=source,changed)
        with tempfile.TemporaryDirectory()as temporary:
            directory=Path(temporary)
            for name,code in [('original',source),('borrowed',rewritten)]:
                rust=directory/(name+'.rs');binary=directory/name
                rust.write_text(code)
                build=subprocess.run(['rustc','--edition=2021',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=60)
                self.assertEqual(build.returncode,0,build.stderr)
                actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected,''))

    def test_returned_future_owns_its_context(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type ClassResult<T>=Result<T,()>;async fn class_function_0(class_scope:ClassScope)->ClassResult<()>{let _held=class_scope.clone();Ok(())}fn main(){let future={let scope=ClassScope{control:Rc::new(4)};class_function_0(scope)};drop(future);println!("done");}', 'done\n')

    def test_owned_field_can_move_out(self):
        self.exercise('#[derive(Clone)]struct ClassScope{modules:Vec<i64>}type ClassResult<T>=Result<T,()>;fn class_function_0(class_scope:ClassScope)->ClassResult<Vec<i64>>{Ok(class_scope.modules)}fn main(){let scope=ClassScope{modules:vec![2,5]};println!("{:?}",class_function_0(scope).unwrap());}', '[2, 5]\n')

    def test_address_taken_function_keeps_its_abi(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type ClassResult<T>=Result<T,()>;fn class_function_0(class_scope:ClassScope)->ClassResult<i64>{Ok(*class_scope.control.clone())}fn main(){let callback:fn(ClassScope)->ClassResult<i64>=class_function_0;println!("{}",callback(ClassScope{control:Rc::new(9)}).unwrap());}', '9\n')

    def test_destructor_effects_survive_alias(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type Alias=ClassScope;impl Drop for Alias{fn drop(&mut self){println!("drop {}",*self.control);}}type ClassResult<T>=Result<T,()>;fn class_function_0(class_scope:ClassScope)->ClassResult<()>{let _held=class_scope.clone();Ok(())}fn main(){let scope=ClassScope{control:Rc::new(3)};class_function_0(scope.clone()).unwrap();println!("after");}', 'drop 3\ndrop 3\nafter\ndrop 3\n')

    def test_nested_context_and_argument_effect_order(self):
        self.exercise('use std::rc::Rc;use std::cell::RefCell;#[derive(Clone)]struct ClassScope{control:Rc<RefCell<i64>>}type ClassResult<T>=Result<T,()>;fn class_function_0(class_scope:ClassScope)->ClassResult<ClassScope>{println!("scope");*class_scope.control.borrow_mut()+=1;Ok(class_scope.clone())}fn class_function_1(class_scope:ClassScope,value:i64)->ClassResult<()>{*class_scope.control.borrow_mut()+=1;println!("{} {}",*class_scope.control.borrow(),value);Ok(())}fn argument()->i64{println!("arg");7}fn main()->ClassResult<()>{let scope=ClassScope{control:Rc::new(RefCell::new(0))};class_function_1(class_function_0(scope.clone())?,argument())?;Ok(())}', 'scope\narg\n2 7\n',True)
