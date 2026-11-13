"""Copy-bound dictionary payload storage and owned-value fallback contracts."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


CASES={
'scalar':'''class Box:
    def __init__(self):
        self.data = {key:3*key for key in range(19)}
box = Box()
copy = box.data.copy()
box.data[3] = 99
print(copy[3], box.data[3], len(copy))
''',
'nullable_tuple':'''class Box:
    def __init__(self):
        self.data = {1:None, 2:(3,4)}
box = Box()
copy = box.data.copy()
box.data[2] = (7,8)
print(copy[1] is None, copy[2][1], box.data[2][1])
''',
'float_tuple_key':'''class Box:
    def __init__(self):
        self.data = {(1,2):1.25, (2,3):-0.0}
box = Box()
copy = box.data.copy()
box.data[(1,2)] = 2.5
print(copy[(1,2)] == 1.25, copy[(2,3)] == 0.0)
''',
'shared_list':'''class Box:
    def __init__(self):
        self.data = {1:[2]}
box = Box()
copy = box.data.copy()
box.data[1].append(7)
print(copy[1], copy[1] is box.data[1])
''',
'shared_instance':'''class Value:
    def __init__(self, value):
        self.value = value
class Box:
    def __init__(self):
        self.data = {1:Value(3)}
box = Box()
copy = box.data.copy()
box.data[1].value = 9
print(copy[1].value, copy[1] is box.data[1])
''',
'string_key':'''class Box:
    def __init__(self):
        self.data = {'left':3, 'right':7}
box = Box()
copy = box.data.copy()
box.data['left'] = 99
print(copy['left'], copy['right'])
''',
}


class DictionaryCopyKindTests(unittest.TestCase):
    def test_copy_certificate_uses_actual_carriers_and_integer_mode(self):
        from py2fastrust.native_dictionary_copy_places import copy_kind
        from py2fastrust.native_types import TupleType,NullableType,ListType,TupleSequenceType
        for mode in ('i64','i128','bigint'):
            self.assertEqual(copy_kind('int',mode),mode!='bigint')
            self.assertEqual(copy_kind(TupleType(('int','bool')),mode),mode!='bigint')
            self.assertTrue(copy_kind(NullableType(TupleType(('bool','float','none'))),mode))
            for kind in ('str','bytes',ListType('int'),TupleSequenceType('int')):
                self.assertFalse(copy_kind(kind,mode))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DictionaryCopySlotExecutionTests(unittest.TestCase):
    def compare(self,name):
        from py2fastrust import transpile,TranspileOptions
        source=CASES[name]
        cp=subprocess.run([sys.executable,'-I','-B','-c',source],text=True,capture_output=True,timeout=30)
        self.assertEqual(cp.returncode,0,cp.stderr)
        for mode in ('i64','i128','bigint'):
            with self.subTest(integer=mode):
                result=transpile(source,TranspileOptions(integer=mode,license='none'))
                self.assertTrue(result.success,result.diagnostics)
                bits=name in {'scalar','nullable_tuple','float_tuple_key'}and mode!='bigint'
                self.assertEqual('.try_python_copy_bits('in result.rust_source,bits)
                with tempfile.TemporaryDirectory(prefix='pytors-copy-slots-')as directory:
                    rust=Path(directory)/'main.rs';rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        binary=Path(directory)/('opt'if optimized else'debug')
                        build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
                        self.assertEqual(build.returncode,0,build.stderr)
                        ran=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10)
                        self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(cp.returncode,cp.stdout,cp.stderr))
    def test_copy_bound_slot_helper_allocation_errors_and_key_representatives(self):
        from test_native_dictionary_physical_storage import products,DENSE_COPY_PROBE
        probe=DENSE_COPY_PROBE.replace('NativeKeyDict::<i64,Rc<Cell<i64>>,Canonical>','NativeKeyDict::<i64,i64,Canonical>')
        probe=probe.replace('Rc::new(Cell::new(value))','value').replace('Rc::new(Cell::new(100))','100')
        probe=probe.replace('source.get(&key(0,&hashes,0)).unwrap().set(99);assert_eq!(copied.get(&key(0,&hashes,0)).unwrap().get(),99);','*source.get_mut(&key(0,&hashes,0)).unwrap()=99;assert_eq!(*copied.get(&key(0,&hashes,0)).unwrap(),0);')
        probe=probe.replace('.try_python_copy(','.try_python_copy_bits(').replace('.try_constructor_copy(','.try_constructor_copy_bits(')
        for layout in ('dense','ordered','positioned'):
            with self.subTest(layout=layout),tempfile.TemporaryDirectory(prefix='pytors-copy-bound-')as directory:
                prefix=products(layout).split('use std::cell::{Cell,RefCell};')[0]
                code=prefix+probe.replace('EXPECTED_ALLOCATIONS','3'if layout=='positioned'else'2').replace('CHECK_NO_HOLES','assert_eq!(source.entries.free,NATIVE_ENTRY_NONE);'if layout!='dense'else'')
                source=Path(directory)/'main.rs';source.write_text(code)
                for optimized in (False,True):
                    binary=Path(directory)/('opt'if optimized else'debug')
                    build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],text=True,capture_output=True,timeout=180)
                    self.assertEqual(build.returncode,0,build.stderr)
                    ran=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10)
                    self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(0,'ok\n',''))
    def test_bulk_slot_api_rejects_noncopy_owned_payloads(self):
        from test_native_dictionary_physical_storage import products
        prefix=products('ordered').split('use std::cell::{Cell,RefCell};')[0]
        source=prefix+'fn main(){let source=NativeKeyDict::<i64,std::rc::Rc<i64>,i64>::new();let _=source.try_python_copy_bits(|value|*value);}'
        with tempfile.TemporaryDirectory(prefix='pytors-copy-rejected-')as directory:
            path=Path(directory)/'main.rs';path.write_text(source)
            build=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(Path(directory)/'invalid')],text=True,capture_output=True,timeout=180)
            self.assertNotEqual(build.returncode,0)
            self.assertIn('Copy',build.stderr)
            self.assertIn('Rc<i64>',build.stderr)
    def test_scalar(self):self.compare('scalar')
    def test_nullable_tuple(self):self.compare('nullable_tuple')
    def test_float_tuple_key(self):self.compare('float_tuple_key')
    def test_shared_list(self):self.compare('shared_list')
    def test_shared_instance(self):self.compare('shared_instance')
    def test_string_key(self):self.compare('string_key')


if __name__=='__main__':unittest.main()
