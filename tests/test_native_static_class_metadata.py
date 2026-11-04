"""Shared class metadata preserves actual class generations and ownership."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import test_native_lambda_callbacks as helpers
from py2fastrust.native_static_class_metadata import RUNTIME

CASES={'captured_classmethod_metadata': 'class Sensor:\n'
                                  ' offset=8\n'
                                  ' def __init__(self,n):self.value=n\n'
                                  ' @classmethod\n'
                                  ' def adjusted(cls,n):return cls.offset+n\n'
                                  ' def score(self):return self.adjusted(self.value)\n'
                                  'def main():\n'
                                  ' a=Sensor(4)\n'
                                  ' b=Sensor(7)\n'
                                  ' saved=a.adjusted\n'
                                  ' print(a.score(),b.score(),saved(3))\n'
                                  'main()\n',
 'class_alias_survives_deletion': 'class Packet:\n'
                                  ' def __init__(self,n):self.value=n\n'
                                  ' def read(self):return self.value\n'
                                  'saved=Packet\n'
                                  'del Packet\n'
                                  'def main():\n'
                                  ' a=saved(11)\n'
                                  ' b=saved(17)\n'
                                  ' print(a.read(),b.read())\n'
                                  'main()\n',
 'constructor_side_effects_and_error': 'events=[]\n'
                                       'class Packet:\n'
                                       ' def __init__(self,n):\n'
                                       '  events.append(n)\n'
                                       '  self.value=20//n\n'
                                       'def main():\n'
                                       ' print(Packet(4).value,events)\n'
                                       ' Packet(0)\n'
                                       'main()\n',
 'distinct_classes_and_rebinding': 'class First:\n'
                                   ' def __init__(self,n):self.value=n\n'
                                   ' def read(self):return self.value+1\n'
                                   'class Second:\n'
                                   ' def __init__(self,n):self.value=n\n'
                                   ' def read(self):return self.value+20\n'
                                   'def main():\n'
                                   ' factory=First\n'
                                   ' a=factory(5)\n'
                                   ' factory=Second\n'
                                   ' b=factory(7)\n'
                                   ' '
                                   'print(a.read(),b.read(),isinstance(a,First),isinstance(b,Second))\n'
                                   'main()\n',
 'instance_identity_keeps_native_reference': 'class Packet:\n'
                                             ' def __init__(self,n):self.value=n\n'
                                             'def main():\n'
                                             ' a=Packet(3)\n'
                                             ' b=Packet(3)\n'
                                             ' alias=a\n'
                                             ' print(a is alias,a is b,a.value,b.value)\n'
                                             'main()\n',
 'module_value_factories': 'class Measure:\n'
                           ' def __init__(self,n):self.value=n\n'
                           ' def total(self,other):return Measure(self.value+other.value)\n'
                           'def make(n):\n'
                           ' item=Measure(0)\n'
                           ' item.value=n*3\n'
                           ' return item\n'
                           'def main():\n'
                           ' a=make(4)\n'
                           ' b=make(7)\n'
                           ' c=a.total(b)\n'
                           ' print(a.value,b.value,c.value)\n'
                           'main()\n'}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class StaticClassMetadataSourceTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

def install(name,source):
    def test(self):self.exercise(source)
    setattr(StaticClassMetadataSourceTests,'test_'+name,test)
for name,source in CASES.items():install(name,source)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class StaticClassMetadataGenerationTests(unittest.TestCase):
    def exercise(self,body,expected):
        header="""use std::rc::Rc;use std::cell::RefCell;
struct ClassGlobals{class_module_status:usize,stamp:i64}
struct ClassClassReference{module:Rc<RefCell<ClassGlobals>>}
type ClassClassRef=Rc<ClassClassReference>;
fn make(stamp:i64,status:usize)->ClassClassRef{Rc::new(ClassClassReference{module:Rc::new(RefCell::new(ClassGlobals{class_module_status:status,stamp}))})}
#[derive(Clone)]struct Datum{class_definition:ClassValueMetadata_0}
fn cached(value:&ClassClassRef)->Datum{Datum{class_definition:class_value_metadata_0(value)}}
"""
        with tempfile.TemporaryDirectory()as temporary:
            path=Path(temporary)/'metadata.rs';binary=path.with_suffix('')
            path.write_text(header+RUNTIME.replace('__INDEX__','0')+'\nfn main(){'+body+'}')
            build=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected,''))

    def test_derived_clone_and_explicit_owned_metadata(self):
        self.exercise('let reference=make(7,1);let a=cached(&reference);let b=Clone::clone(&a);let owned:ClassClassRef=a.class_definition.clone();println!("{} {} {}",a.class_definition.module.borrow().stamp,b.class_definition.module.borrow().stamp,Rc::ptr_eq(&owned,&reference));','7 7 true\n')

    def test_failed_initialization_then_new_success(self):
        self.exercise('let first=make(3,0);let a=cached(&first);first.module.borrow_mut().class_module_status=2;let second=make(17,1);let b=cached(&second);println!("{} {} {} {}",a.class_definition.module.borrow().stamp,b.class_definition.module.borrow().stamp,Rc::ptr_eq(&a.class_definition,&first),Rc::ptr_eq(&b.class_definition,&second));','3 17 true true\n')

    def test_distinct_completed_class_generations(self):
        self.exercise('let first=make(7,1);let a=cached(&first);let second=make(29,1);let b=cached(&second);println!("{} {} {} {}",a.class_definition.module.borrow().stamp,b.class_definition.module.borrow().stamp,Rc::ptr_eq(&a.class_definition,&first),Rc::ptr_eq(&b.class_definition,&second));','7 29 true true\n')

    def test_initializing_and_ready_instances_share_the_actual_class(self):
        self.exercise('let reference=make(2,0);let a=cached(&reference);reference.module.borrow_mut().class_module_status=1;let b=cached(&reference);reference.module.borrow_mut().stamp=9;println!("{} {} {}",a.class_definition.module.borrow().stamp,b.class_definition.module.borrow().stamp,Rc::ptr_eq(&a.class_definition,&b.class_definition));','9 9 true\n')
