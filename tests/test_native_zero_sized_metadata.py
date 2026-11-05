"""Zero-size metadata preserves actual references under one-generation proof."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_single_execution_metadata as metadata

PROJECTS = {'constructor_error_order': {'main.py': 'import math\n'
                                        'class Quantity:\n'
                                        ' def __init__(self,value):\n'
                                        '  print("init",value)\n'
                                        '  if value<0:raise '
                                        'ValueError("negative")\n'
                                        '  self.value=value\n'
                                        ' @classmethod\n'
                                        ' def create(cls,value):return '
                                        'cls(value)\n'
                                        'first=Quantity(math.isqrt(16))\n'
                                        'print(first.value)\n'
                                        'second=Quantity.create(int(input()))\n'
                                        'print(second.value)\n'},
 'direct_factory_alias': {'main.py': 'import math\n'
                                     'class Quantity:\n'
                                     ' base=3\n'
                                     ' def '
                                     '__init__(self,value):self.value=value\n'
                                     ' @classmethod\n'
                                     ' def make(cls,value):return cls(value)\n'
                                     ' @classmethod\n'
                                     ' def read_base(cls):return cls.base\n'
                                     'Alias=Quantity\n'
                                     'a=Alias.make(math.isqrt(81))\n'
                                     'b=Quantity(4)\n'
                                     'print(a.value+b.value,a.read_base(),isinstance(a,Quantity),Alias '
                                     'is Quantity)\n'},
 'failed_module_retry_generations': {'main.py': 'import state_unit\n'
                                                'class Suppress:\n'
                                                ' def __enter__(self):return '
                                                'None\n'
                                                ' def '
                                                '__exit__(self,kind,error,trace):return '
                                                'True\n'
                                                'with Suppress():\n'
                                                ' import payload_unit\n'
                                                'with Suppress():\n'
                                                ' import payload_unit\n'
                                                'print(state_unit.attempts,state_unit.saved[0].total(),state_unit.saved[1].total())\n',
                                     'payload_unit.py': 'import state_unit\n'
                                                        'state_unit.attempts+=1\n'
                                                        'class Quantity:\n'
                                                        ' '
                                                        'base=state_unit.attempts*10\n'
                                                        ' def '
                                                        '__init__(self,value):self.value=value\n'
                                                        ' def '
                                                        'total(self):return '
                                                        'self.value+Quantity.base\n'
                                                        'state_unit.saved.append(Quantity(5))\n'
                                                        'if '
                                                        'state_unit.attempts==1:raise '
                                                        'RuntimeError("retry")\n',
                                     'state_unit.py': 'attempts=0\nsaved=[]\n'},
 'finite_depth_decline': {'main.py': 'import sys\n'
                                     'sys.setrecursionlimit(1000)\n'
                                     'class Quantity:\n'
                                     ' def '
                                     '__init__(self,value):self.value=value\n'
                                     ' @classmethod\n'
                                     ' def create(cls,value):return '
                                     'cls(value)\n'
                                     'item=Quantity.create(9)\n'
                                     'print(item.value)\n'},
 'fresh_factory_and_stored_classmethod': {'main.py': 'import math\n'
                                                     'class Quantity:\n'
                                                     ' base=2\n'
                                                     ' def '
                                                     '__init__(self,value):self.value=value\n'
                                                     ' @classmethod\n'
                                                     ' def create(cls,value):\n'
                                                     '  result=cls(0)\n'
                                                     '  result.value=value\n'
                                                     '  return result\n'
                                                     ' @classmethod\n'
                                                     ' def '
                                                     'total(cls,value):return '
                                                     'cls.base+value\n'
                                                     'make=Quantity.create\n'
                                                     'read=Quantity.total\n'
                                                     'item=make(math.isqrt(100))\n'
                                                     'print(read(item.value),item.total(3))\n'},
 'function_import_decline': {'main.py': 'def load(value):\n'
                                        ' import payload_unit\n'
                                        ' return '
                                        'payload_unit.Quantity.create(value)\n'
                                        'a=load(5)\n'
                                        'b=load(9)\n'
                                        'print(a.value,b.value)\n',
                             'payload_unit.py': 'class Quantity:\n'
                                                ' def '
                                                '__init__(self,value):self.value=value\n'
                                                ' @classmethod\n'
                                                ' def create(cls,value):return '
                                                'cls(value)\n'},
 'function_local_generations': {'main.py': 'import math\n'
                                           'def make(seed):\n'
                                           ' class Quantity:\n'
                                           '  base=seed\n'
                                           '  def '
                                           '__init__(self,value):self.value=value\n'
                                           '  @classmethod\n'
                                           '  def total(cls,value):return '
                                           'value+cls.base\n'
                                           ' return Quantity(math.isqrt(16))\n'
                                           'a=make(3)\n'
                                           'b=make(8)\n'
                                           'print(a.total(a.value),b.total(b.value))\n'},
 'imported_distinct_modules': {'left_unit.py': 'import math\n'
                                               'class Quantity:\n'
                                               ' base=11\n'
                                               ' def '
                                               '__init__(self,value):self.value=value\n'
                                               ' @classmethod\n'
                                               ' def total(cls,value):return '
                                               'cls.base+value\n'
                                               'def make():return '
                                               'Quantity(math.isqrt(25))\n',
                               'main.py': 'import left_unit\n'
                                          'import right_unit\n'
                                          'a=left_unit.make()\n'
                                          'b=right_unit.make()\n'
                                          'print(a.total(a.value),b.total(b.value),isinstance(a,left_unit.Quantity),isinstance(a,right_unit.Quantity))\n',
                               'right_unit.py': 'import math\n'
                                                'class Quantity:\n'
                                                ' base=23\n'
                                                ' def '
                                                '__init__(self,value):self.value=value\n'
                                                ' @classmethod\n'
                                                ' def total(cls,value):return '
                                                'cls.base+value\n'
                                                'def make():return '
                                                'Quantity(math.isqrt(49))\n'},
 'instance_identity_decline': {'main.py': 'import math\n'
                                          'class Quantity:\n'
                                          ' def '
                                          '__init__(self,value):self.value=value\n'
                                          'item=Quantity(math.isqrt(36))\n'
                                          'alias=item\n'
                                          'print(item is '
                                          'alias,item.value,alias.value)\n'},
 'live_class_namespace': {'main.py': 'import math\n'
                                     'class Quantity:\n'
                                     ' base=7\n'
                                     ' def '
                                     '__init__(self,value):self.value=value\n'
                                     ' @classmethod\n'
                                     ' def total(cls,value):return '
                                     'value+cls.base\n'
                                     'item=Quantity(math.isqrt(16))\n'
                                     'Alias=Quantity\n'
                                     'print(item.total(item.value))\n'
                                     'Alias.base=13\n'
                                     'print(item.total(item.value),Quantity.base)\n'},
 'multiple_value_owners': {'main.py': 'import math\n'
                                      'class Left:\n'
                                      ' def '
                                      '__init__(self,value):self.value=value\n'
                                      'class Right:\n'
                                      ' def '
                                      '__init__(self,value):self.value=value\n'
                                      'a=Left(math.isqrt(49))\n'
                                      'b=Right(11)\n'
                                      'print(a.value+b.value,isinstance(a,Left),isinstance(a,Right),isinstance(b,Right))\n'},
 'value_container_copies': {'main.py': 'import math\n'
                                       'class Quantity:\n'
                                       ' def '
                                       '__init__(self,value):self.value=value\n'
                                       ' @classmethod\n'
                                       ' def create(cls,value):return '
                                       'cls(value)\n'
                                       'item=Quantity(math.isqrt(64))\n'
                                       'values=[item,item,Quantity.create(3)]\n'
                                       'print(values[0].value+values[1].value+values[2].value,isinstance(values[1],Quantity))\n'},
 'zero_instance_payload': {'main.py': 'import math\n'
                                      'class Category:\n'
                                      ' base=17\n'
                                      ' def '
                                      '__init__(self,value):print("new",value)\n'
                                      ' @classmethod\n'
                                      ' def read(cls):return cls.base\n'
                                      'values=[Category(math.isqrt(16)),Category(7)]\n'
                                      'print(values[0].read(),values[-1].read())\n'}}


def project_source(name):
    directory = tempfile.TemporaryDirectory(prefix="pytors-zero-metadata-source-")
    root = Path(directory.name)
    for filename, source in PROJECTS[name].items():
        (root / filename).write_text(source)
    return directory, root / "main.py"


class ZeroMetadataSourceProofs(unittest.TestCase):
    def test_original_direct_module_owners_use_zero_size_carrier(self):
        for name in ("direct_factory_alias", "imported_distinct_modules", "zero_instance_payload"):
            directory, path = project_source(name)
            with directory:
                observed = []
                original = metadata.apply

                def capture(source, model):
                    result = original(source, model)
                    observed.append(dict(model.single_execution_metadata))
                    return result

                with patch.object(metadata, "apply", capture):
                    result = transpile(path.read_text(), TranspileOptions(filename=str(path), license="none"))
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(any(info["eligible"] and info["specialized_owners"] for info in observed), name)
                for info in observed:
                    for owner in info["specialized_owners"]:
                        self.assertIn("struct ClassValueMetadata_" + str(owner) + ";", result.rust_source)
                self.assertNotIn("(&'static ClassClassRef)", result.rust_source)

    def test_failed_certification_keeps_exact_safe_generated_source(self):
        for name in ("finite_depth_decline", "function_import_decline"):
            directory, path = project_source(name)
            with directory:
                options = TranspileOptions(filename=str(path), license="none")
                first = transpile(path.read_text(), options)
                with patch.object(metadata, "PLAIN_RUNTIME", "INVALID_UNSELECTED_PRIVATE_TEMPLATE"):
                    second = transpile(path.read_text(), options)
                self.assertTrue(first.success, first.diagnostics)
                self.assertTrue(second.success, second.diagnostics)
                self.assertEqual(first.rust_source, second.rust_source)
                self.assertIn("(Option<ClassClassRef>)", first.rust_source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ZeroMetadataPhysicalContracts(unittest.TestCase):
    def run_physical(self, body, expected):
        header = """
use std::rc::Rc;
use std::cell::RefCell;
struct ClassGlobals {stamp:i64}
struct ClassClassReference {module:Rc<RefCell<ClassGlobals>>}
type ClassClassRef=Rc<ClassClassReference>;
fn make(stamp:i64)->ClassClassRef {
    Rc::new(ClassClassReference {module:Rc::new(RefCell::new(ClassGlobals {stamp}))})
}
#[derive(Clone)]
struct Datum {class_definition:ClassValueMetadata_0,value:std::cell::Cell<i64>}
fn datum(reference:&ClassClassRef,value:i64)->Datum {
    Datum {class_definition:class_value_metadata_0(reference),value:std::cell::Cell::new(value)}
}
"""
        source = (header + metadata.PLAIN_RUNTIME.replace("__INDEX__", "0")
                  + metadata.PLAIN_RUNTIME.replace("__INDEX__", "1")
                  + "\nfn main(){" + body + "}")
        for optimized in (False, True):
            with tempfile.TemporaryDirectory(prefix="pytors-zero-metadata-physical-") as directory:
                path, binary = Path(directory, "metadata.rs"), Path(directory, "metadata")
                path.write_text(source)
                built = subprocess.run(["rustc", "--edition=2021", *(["-O"] if optimized else []),
                                        str(path), "-o", str(binary)],
                                       capture_output=True, text=True, timeout=120)
                self.assertEqual(built.returncode, 0, built.stderr)
                actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                self.assertEqual((actual.stdout, actual.stderr, actual.returncode), (expected, "", 0))

    def test_size_and_trait_vs_inherent_clone_identity(self):
        body = """
let actual=make(7);
let before=Rc::strong_count(&actual);
let value=datum(&actual,3);
let copy=Clone::clone(&value);
assert_eq!(Rc::strong_count(&actual),before+1);
let reference:ClassClassRef=value.class_definition.clone();
assert!(Rc::ptr_eq(&reference,&actual));
assert!(Rc::ptr_eq(&copy.class_definition,&actual));
drop(reference);
assert_eq!(Rc::strong_count(&actual),before+1);
println!("{} {} {} {} {}",std::mem::size_of::<ClassValueMetadata_0>(),
    std::mem::size_of::<Datum>(),std::mem::size_of::<(Datum,i64)>(),
    std::mem::size_of::<(Datum,Datum)>(),copy.value.get());
"""
        self.run_physical(body, "0 8 16 16 3\n")

    def test_each_owner_pin_and_live_actual_namespace_survive_value_clones(self):
        body = """
let first=make(11);
let second=make(23);
let a=class_value_metadata_0(&first);
let b=class_value_metadata_1(&second);
let copy=Clone::clone(&a);
first.module.borrow_mut().stamp=19;
assert!(Rc::ptr_eq(&a,&first));
assert!(Rc::ptr_eq(&copy,&first));
assert!(Rc::ptr_eq(&b,&second));
drop(first);
println!("{} {} {}",a.module.borrow().stamp,copy.module.borrow().stamp,b.module.borrow().stamp);
"""
        self.run_physical(body, "19 19 23\n")


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ZeroMetadataProjectExecution(unittest.TestCase):
    def test_class_aliases_and_live_namespace_all_integer_modes(self):
        for name in ("direct_factory_alias", "live_class_namespace", "zero_instance_payload"):
            directory, path = project_source(name)
            with directory:
                reference = subprocess.run([sys.executable, "-S", str(path)],
                                           capture_output=True, text=True, timeout=10)
                for integer in ("i64", "i128", "bigint"):
                    result = transpile(path.read_text(), TranspileOptions(
                        filename=str(path), integer=integer, license="none"))
                    self.assertTrue(result.success, result.diagnostics)
                    for optimized in (False, True):
                        rust = path.with_name(integer + ("_opt" if optimized else "_debug") + ".rs")
                        binary = rust.with_suffix("")
                        rust.write_text(result.rust_source)
                        built = subprocess.run(["rustc", "--edition=2021", *(["-O"] if optimized else []),
                                                str(rust), "-o", str(binary)],
                                               capture_output=True, text=True, timeout=120)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                        self.assertEqual((actual.stdout, actual.stderr, actual.returncode),
                                         (reference.stdout, reference.stderr, reference.returncode),
                                         (name, integer, optimized))
