"""Constructor context borrows preserve scopes, effects and retained ownership."""
import shutil
import unittest

from py2fastrust import transpile
import test_native_lambda_callbacks as helpers
import test_native_finite_depth_calls as projects
import test_native_scope_borrows as physical


CASES = {'basic_constructor': ({'main.py': 'class Box:\n'
                                   ' def __init__(self,value=7):self.value=value\n'
                                   'print(Box().value,Box(11).value)\n'},
                       ('',)),
 'argument_effect_order': ({'main.py': 'def mark(label,value):\n'
                                       ' print(label)\n'
                                       ' return value\n'
                                       'class Box:\n'
                                       ' def __init__(self,a,b):\n'
                                       '  print("init")\n'
                                       '  self.value=a+b\n'
                                       'print(Box(mark("first",3),mark("second",7)).value)\n'},
                           ('',)),
 'constructor_error': ({'main.py': 'class Box:\n'
                                   ' def __init__(self,value):self.value=12//value\n'
                                   'def build(value):return Box(value)\n'
                                   'print(build(int(input())).value)\n'},
                       ('0\n', '3\n')),
 'nested_constructors': ({'main.py': 'class Inner:\n'
                                     ' def __init__(self,value):self.value=value+1\n'
                                     'class Outer:\n'
                                     ' def __init__(self,value):self.child=Inner(value)\n'
                                     'print(Outer(7).child.value)\n'},
                         ('',)),
 'returned_constructor_closure': ({'main.py': 'class Maker:\n'
                                              ' def __init__(self,base):self.call=lambda '
                                              'value:base+value\n'
                                              ' def invoke(self,value):return self.call(value)\n'
                                              'def build(value):return Maker(value)\n'
                                              'a=build(7)\n'
                                              'print(a.invoke(3),a.invoke(9))\n'},
                                  ('',)),
 'first_class_constructor': ({'main.py': 'class Box:\n'
                                         ' def __init__(self,value):self.value=value\n'
                                         'def build(factory,value):return factory(value)\n'
                                         'print(build(Box,7).value)\n'},
                             ('',)),
 'variadic_constructor': ({'main.py': 'class Box:\n'
                                      ' def '
                                      '__init__(self,first,*rest,scale=2):self.value=(first+sum(rest))*scale\n'
                                      'print(Box(1,2,3,scale=4).value)\n'},
                          ('',)),
 'recursive_constructor': ({'main.py': 'class Node:\n'
                                       ' def __init__(self,value):\n'
                                       '  self.value=value\n'
                                       '  self.child=Node(value-1)if value else None\n'
                                       'a=Node(4)\n'
                                       'print(a.value,a.child.value,a.child.child.value)\n'},
                           ('',)),
 'constructor_context_cleanup': ({'main.py': 'class Guard:\n'
                                             ' def __enter__(self):\n'
                                             '  print("enter")\n'
                                             '  return None\n'
                                             ' def __exit__(self,a,b,c):print("exit")\n'
                                             'class Box:\n'
                                             ' def __init__(self,value):\n'
                                             '  with Guard():self.value=12//value\n'
                                             'print(Box(int(input())).value)\n'},
                                 ('0\n', '3\n')),
 'module_context': ({'main.py': 'import alpha\n'
                                'import beta\n'
                                'print(alpha.Box(3).value,beta.Box(3).value)\n',
                     'beta.py': 'offset=100\n'
                                'class Box:\n'
                                ' def __init__(self,value):self.value=offset+value\n',
                     'alpha.py': 'offset=10\n'
                                 'class Box:\n'
                                 ' def __init__(self,value):self.value=offset+value\n'},
                    ('',)),
 'module_context_argument_change': ({'main.py': 'import alpha\n'
                                                'def argument():\n'
                                                ' alpha.offset=30\n'
                                                ' print("argument")\n'
                                                ' return 3\n'
                                                'Alias=alpha.Box\n'
                                                'print(Alias(argument()).value)\n',
                                     'alpha.py': 'offset=10\n'
                                                 'class Box:\n'
                                                 ' def '
                                                 '__init__(self,value):self.value=offset+value\n'},
                                    ('',)),
 'failed_generation_context': ({'main.py': 'import state\n'
                                           'def load(value):\n'
                                           ' import unstable\n'
                                           ' return value\n'
                                           'print(list(map(load,[1])))\n'
                                           'import unstable\n'
                                           'Old,New=state.saved\n'
                                           'print(Old().value,New().value,isinstance(Old(),New))\n',
                                'state.py': 'saved=[]\n'
                                            'count=0\n'
                                            'def keep(value):saved.append(value)\n',
                                'unstable.py': 'import state\n'
                                               'state.count+=1\n'
                                               'seed=11*state.count\n'
                                               'class Box:\n'
                                               ' def __init__(self):self.value=seed\n'
                                               'state.keep(Box)\n'
                                               'if state.count==1:next(iter([]))\n'},
                               ('',)),
 'context_factory_identity': ({'main.py': 'import alpha\n'
                                          'from alpha import Box as Alias\n'
                                          'factory=Alias\n'
                                          'print(factory(3).value,isinstance(factory(3),Alias))\n',
                               'alpha.py': 'offset=10\n'
                                           'class Box:\n'
                                           ' def __init__(self,value):self.value=offset+value\n'},
                              ('',))}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeConstructorScopeBorrowTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise
    exercise_project = projects.NativeFiniteDepthTests.exercise_project

    def test_synchronous_constructor_borrows_context(self):
        result = transpile(CASES["basic_constructor"][0]["main.py"])
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("fn class_construct_0(class_scope:&ClassScope", result.rust_source)

    def test_basic_constructor(self):
        self.exercise(CASES['basic_constructor'][0]["main.py"], CASES['basic_constructor'][1])

    def test_argument_effect_order(self):
        self.exercise(CASES['argument_effect_order'][0]["main.py"], CASES['argument_effect_order'][1])

    def test_constructor_error(self):
        self.exercise(CASES['constructor_error'][0]["main.py"], CASES['constructor_error'][1])

    def test_nested_constructors(self):
        self.exercise(CASES['nested_constructors'][0]["main.py"], CASES['nested_constructors'][1])

    def test_returned_constructor_closure(self):
        self.exercise(CASES['returned_constructor_closure'][0]["main.py"], CASES['returned_constructor_closure'][1])

    def test_first_class_constructor(self):
        self.exercise(CASES['first_class_constructor'][0]["main.py"], CASES['first_class_constructor'][1])

    def test_variadic_constructor(self):
        self.exercise(CASES['variadic_constructor'][0]["main.py"], CASES['variadic_constructor'][1])

    def test_recursive_constructor(self):
        self.exercise(CASES['recursive_constructor'][0]["main.py"], CASES['recursive_constructor'][1])

    def test_constructor_context_cleanup(self):
        self.exercise(CASES['constructor_context_cleanup'][0]["main.py"], CASES['constructor_context_cleanup'][1])

    def test_module_context(self):
        self.exercise_project(CASES['module_context'][0]["main.py"], files=CASES['module_context'][0])

    def test_module_context_argument_change(self):
        self.exercise_project(CASES['module_context_argument_change'][0]["main.py"], files=CASES['module_context_argument_change'][0])

    def test_failed_generation_context(self):
        self.exercise_project(CASES['failed_generation_context'][0]["main.py"], files=CASES['failed_generation_context'][0])

    def test_context_factory_identity(self):
        self.exercise_project(CASES['context_factory_identity'][0]["main.py"], files=CASES['context_factory_identity'][0])


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeConstructorScopePhysicalTests(unittest.TestCase):
    exercise = physical.NativeScopePhysicalLifetimeTests.exercise

    def test_async_constructor_future_owns_context(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type ClassResult<T>=Result<T,()>;async fn class_construct_0(class_scope:ClassScope)->ClassResult<()>{let _held=class_scope.clone();Ok(())}fn main(){let future={let scope=ClassScope{control:Rc::new(4)};class_construct_0(scope)};drop(future);println!("done");}', 'done\n')

    def test_qualified_constructor_headers_keep_owned_abi(self):
        common='#![allow(improper_ctypes_definitions)]use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type ClassResult<T>=Result<T,()>;'
        for qualifier in ('unsafe ', 'extern "C" '):
            call='class_construct_0(scope).unwrap()'
            if qualifier=='unsafe ':call='unsafe{'+call+'}'
            self.exercise(common+qualifier+'fn class_construct_0(class_scope:ClassScope)->ClassResult<i64>{Ok(*class_scope.control.clone())}fn main(){let scope=ClassScope{control:Rc::new(9)};println!("{}",'+call+');}', '9\n')
        self.exercise(common+'const fn class_construct_0(class_scope:ClassScope)->ClassResult<ClassScope>{Ok(class_scope)}fn main(){let scope=ClassScope{control:Rc::new(9)};let held=class_construct_0(scope).unwrap();println!("{}",*held.control);}', '9\n')

    def test_owned_field_can_move_from_constructor(self):
        self.exercise('#[derive(Clone)]struct ClassScope{modules:Vec<i64>}type ClassResult<T>=Result<T,()>;fn class_construct_0(class_scope:ClassScope)->ClassResult<Vec<i64>>{Ok(class_scope.modules)}fn main(){let scope=ClassScope{modules:vec![2,5]};println!("{:?}",class_construct_0(scope).unwrap());}', '[2, 5]\n')

    def test_constructor_address_retains_owned_abi(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type ClassResult<T>=Result<T,()>;fn class_construct_0(class_scope:ClassScope)->ClassResult<i64>{Ok(*class_scope.control.clone())}fn main(){let callback:fn(ClassScope)->ClassResult<i64>=class_construct_0;println!("{}",callback(ClassScope{control:Rc::new(9)}).unwrap());}', '9\n')

    def test_constructor_scope_destructor_alias(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}type Alias=ClassScope;impl Drop for Alias{fn drop(&mut self){println!("drop {}",*self.control);}}type ClassResult<T>=Result<T,()>;fn class_construct_0(class_scope:ClassScope)->ClassResult<()>{let _held=class_scope.clone();Ok(())}fn main(){let scope=ClassScope{control:Rc::new(3)};class_construct_0(scope.clone()).unwrap();println!("after");}', 'drop 3\ndrop 3\nafter\ndrop 3\n')

    def test_retained_context_clone_remains_owned_after_parent_scope(self):
        self.exercise('use std::rc::Rc;#[derive(Clone)]struct ClassScope{control:Rc<i64>}struct Held{scope:ClassScope}type ClassResult<T>=Result<T,()>;fn class_construct_0(class_scope:ClassScope)->ClassResult<Held>{Ok(Held{scope:class_scope.clone()})}fn main(){let held={let scope=ClassScope{control:Rc::new(9)};class_construct_0(scope).unwrap()};println!("{}",*held.scope.control);}', '9\n', True)

    def test_nested_constructor_context_and_argument_order(self):
        self.exercise('use std::rc::Rc;use std::cell::RefCell;#[derive(Clone)]struct ClassScope{control:Rc<RefCell<i64>>}type ClassResult<T>=Result<T,()>;fn class_construct_0(class_scope:ClassScope)->ClassResult<ClassScope>{println!("scope");*class_scope.control.borrow_mut()+=1;Ok(class_scope.clone())}fn class_construct_1(class_scope:ClassScope,value:i64)->ClassResult<()>{*class_scope.control.borrow_mut()+=1;println!("{} {}",*class_scope.control.borrow(),value);Ok(())}fn argument()->i64{println!("arg");7}fn main()->ClassResult<()>{let scope=ClassScope{control:Rc::new(RefCell::new(0))};class_construct_1(class_construct_0(scope.clone())?,argument())?;Ok(())}', 'scope\narg\n2 7\n', True)


if __name__ == "__main__":
    unittest.main()
