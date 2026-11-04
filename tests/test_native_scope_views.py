"""Module scope views retain ownership, lexical lifetime and actual module identity."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from py2fastrust import transpile, TranspileOptions
from py2fastrust.native_scope_views import apply
import test_native_lambda_callbacks as helpers

CASES = {'same_module_nested_reads': ({'main.py': 'seed=7\n'
                                          'class Box:\n'
                                          ' def __init__(self,x):self.value=x\n'
                                          ' def read(self):return seed+self.value\n'
                                          'def leaf(x):return Box(x).read()\n'
                                          'def outer(x):return leaf(x)+leaf(x+1)\n'
                                          'print(outer(3))\n'},
                              ['']),
 'same_module_global_effects': ({'main.py': 'count=0\n'
                                            'class Box:\n'
                                            ' def __init__(self,x):self.value=x\n'
                                            'def tick(x):\n'
                                            ' global count\n'
                                            ' count+=x\n'
                                            ' return count\n'
                                            'def run():\n'
                                            ' b=Box(3)\n'
                                            ' return tick(b.value)+tick(5)\n'
                                            'print(run(),count)\n'},
                                ['']),
 'cross_module_callback_context': ({'main.py': 'import alpha\n'
                                               'import beta\n'
                                               'print(beta.run(alpha.read),alpha.run(beta.read))\n',
                                    'beta.py': 'seed=101\n'
                                               'class Box:\n'
                                               ' def __init__(self,x):self.value=x\n'
                                               'def read(x):return Box(x).value+seed\n'
                                               'def run(callback):return '
                                               'callback(5)+read(7)\n',
                                    'alpha.py': 'seed=11\n'
                                                'class Box:\n'
                                                ' def __init__(self,x):self.value=x\n'
                                                'def read(x):return Box(x).value+seed\n'
                                                'def run(callback):return '
                                                'callback(2)+read(3)\n'},
                                   ['']),
 'argument_mutates_module_before_call': ({'main.py': 'import alpha\n'
                                                     'def argument():\n'
                                                     ' alpha.seed=40\n'
                                                     ' print("argument")\n'
                                                     ' return 2\n'
                                                     'callback=alpha.read\n'
                                                     'print(callback(argument()),alpha.read(3))\n',
                                          'alpha.py': 'seed=10\n'
                                                      'class Box:\n'
                                                      ' def '
                                                      '__init__(self,x):self.value=x\n'
                                                      'def read(x):return '
                                                      'seed+Box(x).value\n'},
                                         ['']),
 'module_returned_closure_defaults': ({'main.py': 'import alpha\n'
                                                  'callback=alpha.make(3)\n'
                                                  'alpha.seed=40\n'
                                                  'print(callback(),callback(5))\n',
                                       'alpha.py': 'seed=11\n'
                                                   'class Box:\n'
                                                   ' def __init__(self,x):self.value=x\n'
                                                   'def make(x):\n'
                                                   ' b=Box(x)\n'
                                                   ' def read(value=seed):return '
                                                   'b.value+seed+value\n'
                                                   ' return read\n'},
                                      ['']),
 'module_bound_method_callback': ({'main.py': 'import alpha\n'
                                              'import beta\n'
                                              'a=alpha.Box(3)\n'
                                              'callback=a.read\n'
                                              'print(beta.run(callback),callback(5))\n',
                                   'beta.py': 'seed=101\n'
                                              'def run(callback):return '
                                              'callback()+callback(7)+seed\n',
                                   'alpha.py': 'seed=11\n'
                                               'class Box:\n'
                                               ' def __init__(self,x):self.value=x\n'
                                               ' def read(self,x=2):return '
                                               'seed+self.value+x\n'},
                                  ['']),
 'failed_generation_methods_defaults': ({'main.py': 'import state\n'
                                                    'def load(value):\n'
                                                    ' import unstable\n'
                                                    ' return value\n'
                                                    'print(list(map(load,[1])))\n'
                                                    'import unstable\n'
                                                    'Old,New=state.saved\n'
                                                    'a,b=Old(),New()\n'
                                                    'print(a.read(),b.read(),a.read(3),b.read(3),isinstance(a,New))\n',
                                         'state.py': 'saved=[]\n'
                                                     'count=0\n'
                                                     'def '
                                                     'keep(value):saved.append(value)\n',
                                         'unstable.py': 'import state\n'
                                                        'state.count+=1\n'
                                                        'seed=11*state.count\n'
                                                        'class Box:\n'
                                                        ' def '
                                                        '__init__(self):self.value=seed\n'
                                                        ' def read(self,x=seed):return '
                                                        'self.value+seed+x\n'
                                                        'state.keep(Box)\n'
                                                        'if '
                                                        'state.count==1:next(iter([]))\n'},
                                        ['']),
 'module_exception_finally': ({'main.py': 'import alpha\n'
                                          'class Guard:\n'
                                          ' def __init__(self):self.value=0\n'
                                          'def run(x):\n'
                                          ' try:return alpha.divide(x)\n'
                                          ' finally:print("finally")\n'
                                          'print(run(int(input())))\n',
                               'alpha.py': 'seed=12\n'
                                           'class Box:\n'
                                           ' def __init__(self,x):self.value=seed//x\n'
                                           'def divide(x):return Box(x).value\n'},
                              ['0\n', '3\n']),
 'same_module_recursive_guard_retained': ({'main.py': 'class Box:\n'
                                                      ' def '
                                                      '__init__(self,x):self.value=x\n'
                                                      'def recur(x):\n'
                                                      ' if x:return '
                                                      'Box(x).value+recur(x-1)\n'
                                                      ' return 0\n'
                                                      'print(recur(int(input())))\n'},
                                          ['0\n', '5\n']),
 'context_manager_cross_module_cleanup': ({'main.py': 'import alpha\n'
                                                      'with alpha.Guard():\n'
                                                      ' '
                                                      'print(alpha.read(int(input())))\n',
                                           'alpha.py': 'seed=12\n'
                                                       'class Guard:\n'
                                                       ' def '
                                                       '__enter__(self):print("enter");return '
                                                       'None\n'
                                                       ' def '
                                                       '__exit__(self,a,b,c):print("exit")\n'
                                                       'class Box:\n'
                                                       ' def '
                                                       '__init__(self,x):self.value=x\n'
                                                       'def read(x):return '
                                                       'seed//Box(x).value\n'},
                                          ['0\n', '3\n']),
 'cross_module_constructor_alias': ({'main.py': 'import alpha\n'
                                                'from alpha import Box as Alias\n'
                                                'def create(factory,x):return '
                                                'factory(x)\n'
                                                'print(create(Alias,3).read(),isinstance(create(Alias,4),alpha.Box))\n',
                                     'alpha.py': 'seed=11\n'
                                                 'class Box:\n'
                                                 ' def '
                                                 '__init__(self,x):self.value=x+seed\n'
                                                 ' def read(self):return '
                                                 'self.value+seed\n'},
                                    ['']),
 'callback_container_alternating_modules': ({'main.py': 'import alpha\n'
                                                        'import beta\n'
                                                        'callbacks=[alpha.read,beta.read,alpha.read]\n'
                                                        'for callback in '
                                                        'callbacks:print(callback(2))\n',
                                             'beta.py': 'seed=101\n'
                                                        'class Box:\n'
                                                        ' def '
                                                        '__init__(self,x):self.value=x\n'
                                                        'def read(x):return '
                                                        'seed+Box(x).value\n',
                                             'alpha.py': 'seed=11\n'
                                                         'class Box:\n'
                                                         ' def '
                                                         '__init__(self,x):self.value=x\n'
                                                         'def read(x):return '
                                                         'seed+Box(x).value\n'},
                                            [''])}

PHYSICAL = {'same_actual_module': ('use std::rc::Rc;use std::cell::RefCell;\n'
                        '#[derive(Clone)]struct '
                        'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                        'struct ClassGlobals{number:i64,value:i64}\n'
                        'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                        'type ClassResult<T>=Result<T,()>;\n'
                        'impl ClassScope{fn '
                        'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                        'fn '
                        'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                        'fn '
                        'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                        'class_scope=class_scope.with_module(target);{let '
                        'value=class_scope.globals.borrow().value;Ok(value)}}fn main(){let '
                        'root=scope(11);println!("{}",class_function_0(&root,root.globals.clone()).unwrap());}',
                        '11\n',
                        True),
 'different_actual_module_same_number': ('use std::rc::Rc;use std::cell::RefCell;\n'
                                         '#[derive(Clone)]struct '
                                         'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                                         'struct ClassGlobals{number:i64,value:i64}\n'
                                         'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                                         'type ClassResult<T>=Result<T,()>;\n'
                                         'impl ClassScope{fn '
                                         'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                                         'fn '
                                         'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                                         'fn '
                                         'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                                         'class_scope=class_scope.with_module(target);{let '
                                         'value=class_scope.globals.borrow().value;Ok(value)}}fn '
                                         'main(){let root=scope(11);let '
                                         'other=scope(22);println!("{} '
                                         '{}",root.globals.borrow().number==other.globals.borrow().number,class_function_0(&root,other.globals.clone()).unwrap());}',
                                         'true 22\n',
                                         True),
 'owned_clone_survives_root': ('use std::rc::Rc;use std::cell::RefCell;\n'
                               '#[derive(Clone)]struct '
                               'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                               'struct ClassGlobals{number:i64,value:i64}\n'
                               'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                               'type ClassResult<T>=Result<T,()>;\n'
                               'impl ClassScope{fn '
                               'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                               'fn '
                               'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                               'struct Held{scope:ClassScope}fn '
                               'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<Held>{let '
                               'class_scope=class_scope.with_module(target);Ok(Held{scope:class_scope.clone()})}fn '
                               'main(){let held={let '
                               'root=scope(11);class_function_0(&root,root.globals.clone()).unwrap()};println!("{}",held.scope.globals.borrow().value);}',
                               '11\n',
                               True),
 'captured_module_effects_once': ('use std::rc::Rc;use std::cell::RefCell;\n'
                                  '#[derive(Clone)]struct '
                                  'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                                  'struct ClassGlobals{number:i64,value:i64}\n'
                                  'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                                  'type ClassResult<T>=Result<T,()>;\n'
                                  'impl ClassScope{fn '
                                  'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                                  'fn '
                                  'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                                  'fn '
                                  'capture(class_scope:&ClassScope)->ClassModuleRef{println!("capture");class_scope.globals.borrow_mut().value+=1;class_scope.globals.clone()}fn '
                                  'class_function_0(class_scope:&ClassScope)->ClassResult<i64>{let '
                                  'class_scope=class_scope.with_module(capture(&class_scope));{let '
                                  'value=class_scope.globals.borrow().value;Ok(value)}}fn '
                                  'main(){let '
                                  'root=scope(11);println!("{}",class_function_0(&root).unwrap());}',
                                  'capture\n12\n',
                                  True),
 'nested_module_views': ('use std::rc::Rc;use std::cell::RefCell;\n'
                         '#[derive(Clone)]struct '
                         'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                         'struct ClassGlobals{number:i64,value:i64}\n'
                         'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                         'type ClassResult<T>=Result<T,()>;\n'
                         'impl ClassScope{fn '
                         'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                         'fn '
                         'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                         'fn '
                         'class_function_0(class_scope:&ClassScope,a:ClassModuleRef,b:ClassModuleRef)->ClassResult<i64>{let '
                         'class_scope=class_scope.with_module(a);let '
                         'first=class_scope.globals.borrow().value;let '
                         'class_scope=class_scope.with_module(b);{let '
                         'value=first+class_scope.globals.borrow().value;Ok(value)}}fn main(){let '
                         'root=scope(11);let '
                         'other=scope(22);println!("{}",class_function_0(&root,root.globals.clone(),other.globals.clone()).unwrap());}',
                         '33\n',
                         True),
 'async_header_retains_owned': ('use std::rc::Rc;use std::cell::RefCell;\n'
                                '#[derive(Clone)]struct '
                                'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                                'struct ClassGlobals{number:i64,value:i64}\n'
                                'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                                'type ClassResult<T>=Result<T,()>;\n'
                                'impl ClassScope{fn '
                                'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                                'fn '
                                'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                                'async fn '
                                'class_function_0(class_scope:ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                                'class_scope=class_scope.with_module(target);{let '
                                'value=class_scope.globals.borrow().value;Ok(value)}}fn main(){let '
                                'future={let root=scope(11);let '
                                'target=root.globals.clone();class_function_0(root,target)};drop(future);println!("done");}',
                                'done\n',
                                False),
 'move_closure_retains_owned': ('use std::rc::Rc;use std::cell::RefCell;\n'
                                '#[derive(Clone)]struct '
                                'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                                'struct ClassGlobals{number:i64,value:i64}\n'
                                'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                                'type ClassResult<T>=Result<T,()>;\n'
                                'impl ClassScope{fn '
                                'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                                'fn '
                                'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                                'fn '
                                'class_function_0(class_scope:ClassScope,target:ClassModuleRef)->impl '
                                'FnOnce()->i64{let '
                                'class_scope=class_scope.with_module(target);move||{let '
                                'value=class_scope.globals.borrow().value;value}}fn main(){let '
                                'callback={let root=scope(11);let '
                                'target=root.globals.clone();class_function_0(root,target)};println!("{}",callback());}',
                                '11\n',
                                False),
 'raw_owned_aggregate_retained': ('use std::rc::Rc;use std::cell::RefCell;\n'
                                  '#[derive(Clone)]struct '
                                  'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                                  'struct ClassGlobals{number:i64,value:i64}\n'
                                  'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                                  'type ClassResult<T>=Result<T,()>;\n'
                                  'impl ClassScope{fn '
                                  'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                                  'fn '
                                  'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                                  'struct Held{scope:ClassScope}fn '
                                  'class_function_0(class_scope:ClassScope,target:ClassModuleRef)->ClassResult<Held>{let '
                                  'class_scope=class_scope.with_module(target);Ok(Held{scope:class_scope})}fn '
                                  'main(){let root=scope(11);let '
                                  'target=root.globals.clone();println!("{}",class_function_0(root,target).unwrap().scope.globals.borrow().value);}',
                                  '11\n',
                                  False),
 'qualified_header_retained': ('use std::rc::Rc;use std::cell::RefCell;\n'
                               '#[derive(Clone)]struct '
                               'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                               'struct ClassGlobals{number:i64,value:i64}\n'
                               'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                               'type ClassResult<T>=Result<T,()>;\n'
                               'impl ClassScope{fn '
                               'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                               'fn '
                               'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                               'unsafe fn '
                               'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                               'class_scope=class_scope.with_module(target);{let '
                               'value=class_scope.globals.borrow().value;Ok(value)}}extern "C" fn '
                               'class_function_1(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                               'class_scope=class_scope.with_module(target);{let '
                               'value=class_scope.globals.borrow().value;Ok(value)}}fn main(){let '
                               'root=scope(11);println!("{} '
                               '{}",unsafe{class_function_0(&root,root.globals.clone()).unwrap()},class_function_1(&root,root.globals.clone()).unwrap());}',
                               '11 11\n',
                               False),
 'noncanonical_constructor_retained': ('use std::rc::Rc;use std::cell::RefCell;\n'
                                       '#[derive(Clone)]struct '
                                       'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                                       'struct ClassGlobals{number:i64,value:i64}\n'
                                       'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                                       'type ClassResult<T>=Result<T,()>;\n'
                                       'impl ClassScope{fn '
                                       'with_module(&self,globals:ClassModuleRef)->Self{{println!("switch");Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}}\n'
                                       'fn '
                                       'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                                       'fn '
                                       'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                                       'class_scope=class_scope.with_module(target);{let '
                                       'value=class_scope.globals.borrow().value;Ok(value)}}fn '
                                       'main(){let '
                                       'root=scope(11);println!("{}",class_function_0(&root,root.globals.clone()).unwrap());}',
                                       'switch\n11\n',
                                       False),
 'scope_destructor_retained': ('use std::rc::Rc;use std::cell::RefCell;\n'
                               '#[derive(Clone)]struct '
                               'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
                               'struct ClassGlobals{number:i64,value:i64}\n'
                               'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
                               'type ClassResult<T>=Result<T,()>;\n'
                               'impl ClassScope{fn '
                               'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                               'fn '
                               'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
                               'type ScopeAlias=ClassScope;impl Drop for ScopeAlias{fn drop(&mut '
                               'self){println!("drop");}}fn '
                               'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
                               'class_scope=class_scope.with_module(target);{let '
                               'value=class_scope.globals.borrow().value;Ok(value)}}fn main(){let '
                               'root=scope(11);println!("{}",class_function_0(&root,root.globals.clone()).unwrap());}',
                               'drop\n11\ndrop\n',
                               False),
 'qualified_clone': ('use std::rc::Rc;\n'
                     'type ClassModuleRef=Rc<i32>;\n'
                     '#[derive(Clone)]\n'
                     'struct '
                     'ClassScope{control:Rc<i32>,io:Rc<i32>,globals:Rc<i32>,modules:Rc<i32>}\n'
                     'impl ClassScope{fn '
                     'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                     'fn '
                     'make_scope()->ClassScope{ClassScope{control:Rc::new(1),io:Rc::new(2),globals:Rc::new(3),modules:Rc::new(4)}}\n'
                     'fn class_function_0(class_scope:ClassScope){\n'
                     ' let other=class_scope.globals.clone();\n'
                     ' let class_scope=class_scope.with_module(other);\n'
                     ' let retained=std::clone::Clone::clone(&class_scope);\n'
                     ' println!("{}",*retained.globals);\n'
                     '}\n'
                     'fn main(){class_function_0(make_scope());}\n',
                     '3\n',
                     False),
 'generic_size_observer': ('use std::rc::Rc;\n'
                           'type ClassModuleRef=Rc<i32>;\n'
                           '#[derive(Clone)]\n'
                           'struct '
                           'ClassScope{control:Rc<i32>,io:Rc<i32>,globals:Rc<i32>,modules:Rc<i32>}\n'
                           'impl ClassScope{fn '
                           'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
                           'fn '
                           'make_scope()->ClassScope{ClassScope{control:Rc::new(1),io:Rc::new(2),globals:Rc::new(3),modules:Rc::new(4)}}\n'
                           'fn bytes<T>(value:&T)->usize{std::mem::size_of_val(value)}\n'
                           'fn class_function_0(class_scope:ClassScope){\n'
                           ' let other=class_scope.globals.clone();\n'
                           ' let class_scope=class_scope.with_module(other);\n'
                           ' println!("{}",bytes(&class_scope));\n'
                           '}\n'
                           'fn main(){class_function_0(make_scope());}\n',
                           '32\n',
                           False)}

PHYSICAL["nested_generic_shadows_concrete_callee"]=('use std::rc::Rc;\n'
 'type ClassModuleRef=Rc<i32>;\n'
 '#[derive(Clone)]\n'
 'struct ClassScope{control:Rc<i32>,io:Rc<i32>,globals:Rc<i32>,modules:Rc<i32>}\n'
 'impl ClassScope{fn '
 'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
 'fn concrete(scope:&ClassScope){println!("{}",*scope.globals);}\n'
 'fn class_function_0(class_scope:ClassScope){\n'
 ' fn concrete<T:Clone>(value:&T){let _retained=value.clone();println!("done");}\n'
 ' let other=class_scope.globals.clone();\n'
 ' let class_scope=class_scope.with_module(other);\n'
 ' concrete(&class_scope);\n'
 '}\n'
 'fn '
 'main(){class_function_0(ClassScope{control:Rc::new(1),io:Rc::new(2),globals:Rc::new(3),modules:Rc::new(4)});}\n',
 'done\n',
 False)

PHYSICAL["generic_type_parameter_shadows_runtime_scope"]=('use std::rc::Rc;use std::cell::RefCell;\n'
 '#[derive(Clone)]struct '
 'ClassScope{control:Rc<RefCell<i64>>,io:Rc<RefCell<i64>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<ClassModuleRef>>>}\n'
 'struct ClassGlobals{number:i64,value:i64}\n'
 'type ClassModuleRef=Rc<RefCell<ClassGlobals>>;\n'
 'type ClassResult<T>=Result<T,()>;\n'
 'impl ClassScope{fn '
 'with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
 'fn '
 'scope(value:i64)->ClassScope{ClassScope{control:Rc::new(RefCell::new(0)),io:Rc::new(RefCell::new(0)),globals:Rc::new(RefCell::new(ClassGlobals{number:1,value})),modules:Rc::new(RefCell::new(Vec::new()))}}\n'
 'fn concrete<ClassScope:Clone>(value:&ClassScope){let _retained=value.clone();}fn '
 'class_function_0(class_scope:&ClassScope,target:ClassModuleRef)->ClassResult<i64>{let '
 'class_scope=class_scope.with_module(target);concrete(&class_scope);{let '
 'value=class_scope.globals.borrow().value;Ok(value)}}fn main(){let '
 'root=scope(11);println!("{}",class_function_0(&root,root.globals.clone()).unwrap());}',
 '11\n',
 False)

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeScopeViewSourceTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)

    def exercise_project(self,files,inputs):
        folder=Path(self.directory.name)/hashlib.sha256(repr(files).encode()).hexdigest()
        folder.mkdir(exist_ok=True)
        for name,source in files.items():(folder/name).write_text(source)
        path=folder/"main.py"
        expected=[subprocess.run([sys.executable,str(path)],input=data,text=True,capture_output=True,timeout=10)for data in inputs]
        for integer in ("i64","i128","bigint"):
            result=transpile(files["main.py"],TranspileOptions(integer=integer,filename=str(path)))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            for optimized in (False,True):
                rust=folder/(integer+("_opt"if optimized else"_debug")+".rs");rust.write_text(result.rust_source);binary=rust.with_suffix("")
                built=subprocess.run(["rustc","--edition=2021","--crate-name","scope_views",*(["-O"]if optimized else[]),str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                for data,wanted in zip(inputs,expected):
                    actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=10,env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                    self.assertEqual((actual.returncode,actual.stdout),(wanted.returncode,wanted.stdout),actual.stderr)
                    final=lambda s:s.rstrip().splitlines()[-1]if s.strip()else""
                    self.assertEqual(final(actual.stderr),final(wanted.stderr))
                    frames=lambda s:re.findall(r'File "[^"]+", line (\d+), in ([^\n]+)',s)
                    self.assertEqual(frames(actual.stderr),frames(wanted.stderr))

    def test_existing_function_try_finally_diagnostic(self):
        source=CASES["module_exception_finally"][0]["main.py"]
        files=CASES["module_exception_finally"][0]
        folder=Path(self.directory.name)/"unsupported_finally";folder.mkdir(exist_ok=True)
        for name,text in files.items():(folder/name).write_text(text)
        for integer in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=integer,filename=str(folder/"main.py")))
            self.assertFalse(result.success)
            self.assertIn("exception handler",str(result.diagnostics))

    def test_runtime_view_preserves_owned_clone_and_actual_pointer(self):
        files,inputs=CASES["cross_module_callback_context"]
        folder=Path(self.directory.name)/"view_codegen";folder.mkdir(exist_ok=True)
        for name,text in files.items():(folder/name).write_text(text)
        result=transpile(files["main.py"],TranspileOptions(filename=str(folder/"main.py")))
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn(".with_module_view(",result.rust_source)
        self.assertIn("Rc::ptr_eq(&self.globals,&globals)",result.rust_source)
        self.assertIn("fn clone(&self)->ClassScope",result.rust_source)


def install_source(name):
    def test(self):self.exercise_project(*CASES[name])
    test.__name__="test_"+name
    setattr(NativeScopeViewSourceTests,test.__name__,test)

for name in CASES:
    if name!="module_exception_finally":install_source(name)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeScopeViewPhysicalTests(unittest.TestCase):
    def exercise(self,source,stdout,changed):
        model=SimpleNamespace(finite_depth_calls={"eligible":True})
        rewritten=apply(source,model)
        self.assertEqual(rewritten!=source,changed,model.scope_views)
        with tempfile.TemporaryDirectory()as temporary:
            folder=Path(temporary)
            for name,text in (("original",source),("transformed",rewritten)):
                rust=folder/(name+".rs");rust.write_text(text)
                for optimized in (False,True):
                    binary=folder/(name+("_opt"if optimized else"_debug"))
                    built=subprocess.run(["rustc","--edition=2021",*(["-O"]if optimized else[]),str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=60)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,stdout,""))

    def test_missing_finite_certificate_keeps_original(self):
        source=PHYSICAL["same_actual_module"][0]
        for facts in ({},{"eligible":False}):
            self.assertEqual(apply(source,SimpleNamespace(finite_depth_calls=facts)),source)


def install_physical(name):
    def test(self):self.exercise(*PHYSICAL[name])
    test.__name__="test_"+name
    setattr(NativeScopeViewPhysicalTests,test.__name__,test)

for name in PHYSICAL:install_physical(name)
