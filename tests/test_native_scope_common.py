"""Common context roots retain ownership, module identity, streams and control."""
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_scope_common import apply
import test_native_scope_views as views

CASES={'callback_interleaved_text_output': ({'main.py': 'import left\n'
                                                  'import right\n'
                                                  'class Token:\n'
                                                  ' def __init__(self,x):self.value=x\n'
                                                  'callbacks=[left.read,right.read,left.read]\n'
                                                  'print("start")\n'
                                                  'for callback in '
                                                  'callbacks:print(callback())\n'
                                                  'print(Token(7).value)\n',
                                       'left.py': 'import sys\n'
                                                  'base=10\n'
                                                  'def read():\n'
                                                  ' value=int(input())\n'
                                                  ' sys.stdout.write("left:")\n'
                                                  ' return base+value\n',
                                       'right.py': 'import sys\n'
                                                   'base=100\n'
                                                   'def read():\n'
                                                   ' value=int(input())\n'
                                                   ' sys.stdout.write("right:")\n'
                                                   ' return base+value\n'},
                                      ['1\n2\n3\n']),
 'retained_callback_reads_original_module': ({'main.py': 'import alpha\n'
                                                         'import beta\n'
                                                         'callback=alpha.make(3)\n'
                                                         'print(beta.run(callback),callback(7))\n',
                                              'beta.py': 'seed=101\n'
                                                         'def run(callback):\n'
                                                         ' print("beta")\n'
                                                         ' return callback(5)+seed\n',
                                              'alpha.py': 'seed=11\n'
                                                          'class Box:\n'
                                                          ' def '
                                                          '__init__(self,x):self.value=x\n'
                                                          'def make(x):\n'
                                                          ' box=Box(x)\n'
                                                          ' return lambda '
                                                          'y:box.value+seed+y\n'},
                                             ['']),
 'mixed_binary_and_text_cursor': ({'main.py': 'import alpha\n'
                                              'import beta\n'
                                              'class Box:\n'
                                              ' def __init__(self,x):self.value=x\n'
                                              'print(alpha.read(),beta.read(),alpha.read(),Box(7).value)\n',
                                   'beta.py': 'def read():return int(input())\n',
                                   'alpha.py': 'import sys\n'
                                               'def read():return '
                                               'int(sys.stdin.buffer.readline())\n'},
                                  ['1\n2\n3\n']),
 'module_cache_initializer_once': ({'main.py': 'import alpha\n'
                                               'import beta\n'
                                               'import alpha\n'
                                               'class Box:\n'
                                               ' def __init__(self,x):self.value=x\n'
                                               'print(alpha.value,beta.value,Box(7).value)\n',
                                    'beta.py': 'import alpha\n'
                                               'print("beta")\n'
                                               'value=alpha.value+int(input())\n',
                                    'alpha.py': 'print("alpha")\nvalue=int(input())\n'},
                                   ['3\n5\n']),
 'failed_import_old_new_function_closure': ({'main.py': 'import state\n'
                                                        'def load(x):\n'
                                                        ' import unstable\n'
                                                        ' return x\n'
                                                        'print(list(map(load,[1])))\n'
                                                        'import unstable\n'
                                                        'old,new=state.saved\n'
                                                        'print(old(2),new(3))\n',
                                             'state.py': 'saved=[]\n'
                                                         'count=0\n'
                                                         'def '
                                                         'keep(callback):saved.append(callback)\n',
                                             'unstable.py': 'import state\n'
                                                            'state.count+=1\n'
                                                            'seed=10*state.count\n'
                                                            'class Box:\n'
                                                            ' def '
                                                            '__init__(self,x):self.value=x\n'
                                                            'def make():\n'
                                                            ' box=Box(3)\n'
                                                            ' return lambda '
                                                            'x:seed+box.value+x+int(input())\n'
                                                            'state.keep(make())\n'
                                                            'if '
                                                            'state.count==1:next(iter([]))\n'},
                                            ['5\n7\n']),
 'module_error_cleanup_output': ({'main.py': 'import alpha\n'
                                             'class Guard:\n'
                                             ' def __enter__(self):print("enter");return '
                                             'None\n'
                                             ' def __exit__(self,a,b,c):print("exit")\n'
                                             'with '
                                             'Guard():print(alpha.divide(int(input())))\n',
                                  'alpha.py': 'class Box:\n'
                                              ' def __init__(self,x):self.value=x\n'
                                              'def divide(x):\n'
                                              ' print("divide")\n'
                                              ' return 12//Box(x).value\n'},
                                 ['0\n', '3\n']),
 'recursion_setter_bound_callback_declines': ({'main.py': 'import alpha\n'
                                                          'import sys\n'
                                                          'callback=alpha.Change.set_limit\n'
                                                          'print(sys.getrecursionlimit())\n'
                                                          'print(callback(70),sys.getrecursionlimit())\n',
                                               'alpha.py': 'import sys\n'
                                                           'class Change:\n'
                                                           ' @classmethod\n'
                                                           ' def set_limit(cls,x):\n'
                                                           '  setter=sys.setrecursionlimit\n'
                                                           '  setter(x)\n'
                                                           '  return '
                                                           'sys.getrecursionlimit()\n'},
                                              ['']),
 'delayed_map_module_effects': ({'main.py': 'import alpha\n'
                                            'import beta\n'
                                            'class Box:\n'
                                            ' def __init__(self,x):self.value=x\n'
                                            'values=map(alpha.read,[1,2])\n'
                                            'print(beta.read())\n'
                                            'print(list(values),Box(7).value)\n',
                                 'beta.py': 'def read():return int(input())\n',
                                 'alpha.py': 'seed=10\n'
                                             'def read(x):\n'
                                             ' print("alpha",x)\n'
                                             ' return seed+x+int(input())\n'},
                                ['5\n7\n11\n']),
 'pending_import_cycle': ({'main.py': 'import first\nprint(first.read())\n',
                           'first.py': 'class Box:\n'
                                       ' def __init__(self,x):self.value=x\n'
                                       'import second\n'
                                       'def read():return Box(second.value).value\n',
                           'second.py': 'import first\nvalue=int(input())\n'},
                          ['7\n']),
 'callback_stream_module_interleave': ({'main.py': 'import left\n'
                                                   'import right\n'
                                                   '\n'
                                                   'saved = left.read\n'
                                                   'print(right.run(saved))\n'
                                                   'print(left.read(), right.read())\n',
                                        'left.py': 'import sys\n'
                                                   'seed = 10\n'
                                                   '\n'
                                                   'def read():\n'
                                                   '    line = sys.stdin.buffer.readline()\n'
                                                   '    print("left", int(line))\n'
                                                   '    return seed + int(line)\n',
                                        'right.py': 'import sys\n'
                                                    'seed = 100\n'
                                                    '\n'
                                                    'def read():\n'
                                                    '    line = sys.stdin.buffer.readline()\n'
                                                    '    print("right", int(line))\n'
                                                    '    return seed + int(line)\n'
                                                    '\n'
                                                    'def run(callback):\n'
                                                    '    return callback() + read()\n'},
                                       ['1\n2\n3\n4\n']),
 'failed_generation_shared_stream': ({'main.py': 'import state\n'
                                                 '\n'
                                                 'def attempt(value):\n'
                                                 '    import donor\n'
                                                 '    return value\n'
                                                 '\n'
                                                 'print(list(map(attempt, [0])))\n'
                                                 'import donor\n'
                                                 'old, new = state.saved\n'
                                                 'print(old(), new())\n',
                                      'donor.py': 'import state\n'
                                                  'import sys\n'
                                                  'state.count += 1\n'
                                                  'seed = 11 * state.count\n'
                                                  '\n'
                                                  'def read():\n'
                                                  '    return seed + '
                                                  'int(sys.stdin.buffer.readline())\n'
                                                  '\n'
                                                  'state.keep(read)\n'
                                                  'if state.count == 1:\n'
                                                  '    next(iter([]))\n',
                                      'state.py': 'saved = []\n'
                                                  'count = 0\n'
                                                  '\n'
                                                  'def keep(callback):\n'
                                                  '    saved.append(callback)\n'},
                                     ['5\n7\n']),
 'recursion_control_certificate_declines': ({'main.py': 'import sys\n'
                                                        'import provider\n'
                                                        '\n'
                                                        'sys.setrecursionlimit(60)\n'
                                                        'print(provider.read_limit())\n'
                                                        'provider.change_limit(90)\n'
                                                        'print(sys.getrecursionlimit(), '
                                                        'provider.read_limit())\n',
                                             'provider.py': 'import sys\n'
                                                            '\n'
                                                            'def change_limit(value):\n'
                                                            '    '
                                                            'sys.setrecursionlimit(value)\n'
                                                            '\n'
                                                            'def read_limit():\n'
                                                            '    return '
                                                            'sys.getrecursionlimit()\n'},
                                            [''])}
RUNTIME='use std::rc::Rc;use std::cell::RefCell;\nstruct ClassControl{depth:usize,limit:usize}struct StandardInput{position:usize}impl StandardInput{fn new()->Self{Self{position:0}}}\nstruct ClassIo{input:StandardInput,output:String}struct ClassGlobals{class_module_id:usize}\ntype ClassModuleRef=Rc<RefCell<ClassGlobals>>;\nfn class_module_globals(number:usize)->ClassModuleRef{Rc::new(RefCell::new(ClassGlobals{class_module_id:number}))}\n#[derive(Clone)]struct ClassScope{control:Rc<RefCell<ClassControl>>,io:Rc<RefCell<ClassIo>>,globals:Rc<RefCell<ClassGlobals>>,modules:Rc<RefCell<Vec<Option<ClassModuleRef>>>>}\nimpl ClassScope{fn new()->Self{let class_globals=class_module_globals(0);let class_modules=Rc::new(RefCell::new(vec![None;1]));class_modules.borrow_mut()[0]=Some(class_globals.clone());Self{control:Rc::new(RefCell::new(ClassControl{depth:0,limit:1000})),io:Rc::new(RefCell::new(ClassIo{input:StandardInput::new(),output:String::new()})),globals:class_globals,modules:class_modules}}}\nimpl ClassScope{fn with_module(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}\n'
POSITIVE='fn main(){let a=ClassScope::new();let b=a.with_module(class_module_globals(0));assert!(Rc::ptr_eq(&a.control.clone(),&b.control.clone()));assert!(Rc::ptr_eq(&a.io.clone(),&b.io.clone()));assert!(Rc::ptr_eq(&a.modules.clone(),&b.modules.clone()));assert!(!Rc::ptr_eq(&a.globals,&b.globals));b.io.borrow_mut().output.push_str("shared");b.io.borrow_mut().input.position=7;assert_eq!(a.io.borrow().output,"shared");let saved=b.clone();drop(b);drop(a);assert_eq!(saved.io.borrow().input.position,7);let io=saved.io.clone();drop(saved);assert_eq!(io.borrow().output,"shared");let next=ClassScope::new();assert!(!Rc::ptr_eq(&io,&next.io.clone()));assert_eq!(next.io.borrow().input.position,0);println!("done");}'
NEGATIVE={'bare_root_move': 'fn held(scope:ClassScope)->Rc<RefCell<ClassControl>>{scope.control}fn '
                   'main(){println!("{}",held(ClassScope::new()).borrow().limit);}',
 'mutable_root_reference': 'fn main(){let mut scope=ClassScope::new();let '
                           'replacement=Rc::new(RefCell::new(ClassIo{input:StandardInput::new(),output:String::new()}));let '
                           'old=std::mem::replace(&mut '
                           'scope.io,replacement);println!("{}",old.borrow().input.position);}',
 'local_alias_constructor': 'fn main(){type Alias=ClassScope;let old=ClassScope::new();let '
                            'value=Alias{control:old.control.clone(),io:old.io.clone(),globals:old.globals.clone(),modules:old.modules.clone()};println!("{}",value.control.borrow().limit);}',
 'use_alias_constructor': 'use self::ClassScope as Alias;fn main(){let old=ClassScope::new();let '
                          'value=Alias{control:old.control.clone(),io:old.io.clone(),globals:old.globals.clone(),modules:old.modules.clone()};println!("{}",value.control.borrow().limit);}',
 'destructure_context': 'fn main(){let '
                        'ClassScope{control,io,globals,modules}=ClassScope::new();println!("{} {} '
                        '{} '
                        '{}",control.borrow().limit,io.borrow().input.position,globals.borrow().class_module_id,modules.borrow().len());}',
 'noncanonical_view_constructor': 'impl ClassScope{fn '
                                  'with_module_view(&self,globals:ClassModuleRef)->Self{Self{control:self.control.clone(),io:self.io.clone(),globals,modules:self.modules.clone()}}}fn '
                                  'main(){let '
                                  'scope=ClassScope::new();println!("{}",scope.with_module_view(scope.globals.clone()).control.borrow().limit);}',
 'payload_use_alias_drop': 'use self::ClassControl as Alias;impl Drop for Alias{fn drop(&mut '
                           'self){println!("control-drop");}}fn main(){let '
                           'scope=ClassScope::new();println!("{}",scope.control.borrow().limit);}',
 'qualified_payload_drop': 'impl Drop for self::ClassControl{fn drop(&mut '
                           'self){println!("control-drop");}}fn main(){let '
                           'scope=ClassScope::new();println!("{}",scope.control.borrow().limit);}',
 'local_payload_drop': 'fn uncalled(){impl Drop for ClassControl{fn drop(&mut '
                       'self){println!("control-drop");}}}fn main(){let '
                       'scope=ClassScope::new();println!("{}",scope.control.borrow().limit);}',
 'layout_observer': 'fn main(){println!("{}",std::mem::size_of::<ClassScope>());}',
 'reference_count_observer': 'fn main(){let scope=ClassScope::new();let '
                             '_copy=scope.clone();println!("{}",Rc::strong_count(&scope.control.clone()));}',
 'custom_scope_trait': 'impl std::fmt::Debug for ClassScope{fn fmt(&self,f:&mut '
                       'std::fmt::Formatter<\'_>)->std::fmt::Result{write!(f,"scope")}}fn '
                       'main(){println!("{:?}",ClassScope::new());}'}

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeScopeCommonSourceTests(unittest.TestCase):
    setUpClass=classmethod(views.NativeScopeViewSourceTests.setUpClass.__func__)
    tearDownClass=classmethod(views.NativeScopeViewSourceTests.tearDownClass.__func__)
    exercise_project=views.NativeScopeViewSourceTests.exercise_project

    def test_existing_stdout_adapter_diagnostic(self):
        files,_=CASES["callback_interleaved_text_output"]
        with tempfile.TemporaryDirectory()as temporary:
            folder=Path(temporary)
            for name,source in files.items():(folder/name).write_text(source)
            for integer in ("i64","i128","bigint"):
                result=transpile(files["main.py"],TranspileOptions(filename=str(folder/"main.py"),integer=integer))
                self.assertFalse(result.success)
                self.assertIn("sys.stdout",str(result.diagnostics))

    def test_grouped_roots_keep_actual_globals_pointer(self):
        files,_=CASES["callback_stream_module_interleave"]
        with tempfile.TemporaryDirectory()as temporary:
            folder=Path(temporary)
            for name,source in files.items():(folder/name).write_text(source)
            result=transpile(files["main.py"],TranspileOptions(filename=str(folder/"main.py")))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn("struct ClassScopeCommon",result.rust_source)
            self.assertIn("Rc::ptr_eq(&self.globals,&globals)",result.rust_source)
            self.assertIn("common:self.common.clone(),globals",result.rust_source)


def install_source(name):
    def test(self):self.exercise_project(*CASES[name])
    test.__name__="test_"+name
    setattr(NativeScopeCommonSourceTests,test.__name__,test)
for name in CASES:
    if name!="callback_interleaved_text_output":install_source(name)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeScopeCommonPhysicalTests(unittest.TestCase):
    def exercise(self,tail,changed):
        source=RUNTIME+tail;model=SimpleNamespace(finite_depth_calls={"eligible":True});grouped=apply(source,model)
        self.assertEqual(grouped!=source,changed,model.scope_common)
        with tempfile.TemporaryDirectory()as temporary:
            folder=Path(temporary);expected=None
            for name,text in (("original",source),("grouped",grouped)):
                rust=folder/(name+".rs");rust.write_text(text)
                for optimized in (False,True):
                    binary=folder/(name+("_opt"if optimized else"_debug"))
                    built=subprocess.run(["rustc","--edition=2021",*(["-O"]if optimized else[]),str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=60)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                    self.assertEqual(actual.returncode,0,actual.stderr)
                    observed=(actual.returncode,actual.stdout,actual.stderr)
                    if expected is None:expected=observed
                    self.assertEqual(observed,expected)

    def test_shared_and_distinct_roots_and_retained_ownership(self):self.exercise(POSITIVE,True)

    def test_missing_finite_certificate_preserves_original(self):
        source=RUNTIME+POSITIVE
        for facts in ({},{"eligible":False}):self.assertEqual(apply(source,SimpleNamespace(finite_depth_calls=facts)),source)


def install_physical(name):
    def test(self):self.exercise(NEGATIVE[name],False)
    test.__name__="test_"+name
    setattr(NativeScopeCommonPhysicalTests,test.__name__,test)
for name in NEGATIVE:install_physical(name)
