"""Borrowed typed iterator fields become owned values without moving their owner."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile
from py2fastrust.native import _Generator
from py2fastrust.native_iterators import Planner
from py2fastrust.native_nested_lists import HELPERS as SHARED_HELPERS
from py2fastrust.native_types import SharedListType,TupleType

CASES={'original_tuple_items': ('mapping={(1,2):3,(4,5):6}\n'
                          'print(mapping[(1,2)],list(mapping.items()))\n',
                          ('',),
                          ('i64', 'i128', 'bigint')),
 'nested_tuple_bytes_items': ("mapping={(1,2):(b'head',(3,b'tail'))}\n"
                              'print(list(mapping.items()),list(mapping.values()))\n',
                              ('',),
                              ('i64', 'i128', 'bigint')),
 'nested_tuple_text_views': ("mapping={(1,2):('alpha',(3,'omega'))}\n"
                             'print(list(mapping.items()),list(mapping.values()),list(mapping.keys()))\n',
                             ('',),
                             ('i64', 'i128', 'bigint')),
 'large_integer_tuple_fields': ('number=int(input())\n'
                                'mapping={(number,number+1):(number+2,number-3)}\n'
                                'print(list(mapping.items()),list(mapping.values()))\n',
                                ('123456789012345678\n',),
                                ('i64', 'i128', 'bigint')),
 'heap_integer_tuple_fields': ('number=int(input())\n'
                               'mapping={(number,number+1):(number+2,number-3)}\n'
                               'print(list(mapping.items()),list(mapping.values()))\n',
                               ('3273390607896141870013189696827599152216642046043064789483291368096133796404674554883270092325904157150886684127560071009217256545885393053328527589377\n',),
                               ('bigint',)),
 'zipped_dictionary_views': ("mapping={(1,2):('value',3),(4,5):('other',6)}\n"
                             'print(list(zip(mapping.items(),mapping.keys())))\n',
                             ('',),
                             ('i64', 'i128', 'bigint')),
 'borrowed_matrix_rows': ('rows=[[1,2],[3]]\n'
                          'result=[]\n'
                          'for row in rows:result.append(sum(row))\n'
                          'print(result,rows)\n',
                          ('',),
                          ('i64', 'i128', 'bigint')),
 'mutable_matrix_rows': ('rows=[[1],[2]]\nfor row in rows:row.append(9)\nprint(rows)\n',
                         ('',),
                         ('i64', 'i128', 'bigint')),
 'shared_mutable_tuple_payloads': ('payload=[1]\n'
                                   'mapping={(1,2):(payload,payload)}\n'
                                   'values=list(mapping.items())\n'
                                   'values[0][1][0].append(7)\n'
                                   'print(payload,values[0][1][1])\n',
                                   ('',),
                                   ('i64', 'i128', 'bigint')),
 'borrowed_tuple_list': ('values=[(1,2),(3,4)]\nprint(list(iter(values)))\n',
                         ('',),
                         ('i64', 'i128', 'bigint')),
 'owned_generator_tuple_values': ('def values():\n'
                                  ' yield((1,2),3)\n'
                                  ' yield((4,5),6)\n'
                                  'print(list(values()))\n',
                                  ('',),
                                  ('i64', 'i128', 'bigint'))}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IteratorFieldOwnership(unittest.TestCase):
    def check(self,name):
        source,inputs,modes=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-field-owner-')as directory:
            root=Path(directory);program=root/'case.py';program.write_text(source)
            expected=[subprocess.run([sys.executable,'-I','-B',str(program)],input=value,text=True,capture_output=True,timeout=20)for value in inputs]
            for mode in modes:
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename=str(program),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+str(optimized));built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180);self.assertEqual(built.returncode,0,built.stderr)
                    for value,reference in zip(inputs,expected):
                        actual=subprocess.run([str(binary)],input=value,text=True,capture_output=True,timeout=20)
                        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(reference.returncode,reference.stdout,reference.stderr),(name,mode,optimized))

    def kernel(self,code):
        with tempfile.TemporaryDirectory(prefix='pytors-field-kernel-')as directory:
            root=Path(directory);source=root/'main.rs';source.write_text(code)
            for optimized in (False,True):
                binary=root/str(optimized);built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=90);self.assertEqual(built.returncode,0,built.stderr)
                run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10);self.assertEqual((run.returncode,run.stdout,run.stderr),(0,'',''))

    def test_actual_shared_handle_is_cloned_and_does_not_hold_a_borrow(self):
        generator=_Generator(64);kind=SharedListType('int')
        stream=Planner(generator).leaf('','','source.iter()',((kind,'@.0',False),))
        value=stream.values[0];self.assertTrue(value.owned)
        action=f"assert!(std::rc::Rc::ptr_eq(&{value.code},&owner)); {value.code}.borrow_mut().push(9); retained.push({value.code});"
        code=SHARED_HELPERS+'type NativeInt=i64; fn main(){ let owner=native_shared_list(vec![1_i64]); let source=vec![(owner.clone(),)]; let mut retained=Vec::new();'+stream.emit(action,'<module>',1)+"drop(source); assert_eq!(*owner.borrow(),vec![1,9]); assert!(std::rc::Rc::ptr_eq(&retained[0],&owner)); drop(retained); assert_eq!(std::rc::Rc::strong_count(&owner),1); }"
        self.kernel(code)

    def test_owned_mutable_fields_move_the_same_allocation(self):
        generator=_Generator(64)
        stream=Planner(generator).leaf('','','source.into_iter()',(('list_int','@',True),))
        value=stream.values[0];self.assertTrue(value.owned)
        self.assertNotIn('.clone()',stream.emit('', '<module>',1))
        code='fn main(){ let payload=vec![1_i64,2]; let pointer=payload.as_ptr(); let source=vec![payload]; let mut retained=Vec::new();'+stream.emit(f'assert_eq!({value.code}.as_ptr(),pointer); retained.push({value.code});','<module>',1)+'assert_eq!(retained[0],vec![1,2]); }'
        self.kernel(code)

    def test_borrowed_list_int_protocol_stays_borrowed(self):
        generator=_Generator(64)
        stream=Planner(generator).leaf('','','source.iter()',(('list_int','@',False),))
        value=stream.values[0];self.assertFalse(value.owned)
        self.assertNotIn('.clone()',stream.emit('', '<module>',1))
        code='fn main(){ let source=vec![vec![1_i64,2]];'+stream.emit(f'assert!(std::ptr::eq({value.code},&source[0]));','<module>',1)+'assert_eq!(source[0],vec![1,2]); }'
        self.kernel(code)

    def test_copy_tuple_fields_keep_the_original_uncloned_projection(self):
        generator=_Generator(64);kind=TupleType(('int','int'))
        stream=Planner(generator).leaf('','','source.iter()',((kind,'@.0',False),))
        value=stream.values[0];self.assertTrue(value.owned)
        self.assertNotIn('.clone()',stream.emit('', '<module>',1))
        code='fn main(){let source=vec![((1_i64,2_i64),)];'+stream.emit(f'assert_eq!({value.code},(1,2));','<module>',1)+'assert_eq!(source[0].0,(1,2));}'
        self.kernel(code)

    def test_original_tuple_items(self):
        self.check('original_tuple_items')

    def test_nested_tuple_bytes_items(self):
        self.check('nested_tuple_bytes_items')

    def test_nested_tuple_text_views(self):
        self.check('nested_tuple_text_views')

    def test_large_integer_tuple_fields(self):
        self.check('large_integer_tuple_fields')

    def test_heap_integer_tuple_fields(self):
        self.check('heap_integer_tuple_fields')

    def test_zipped_dictionary_views(self):
        self.check('zipped_dictionary_views')

    def test_borrowed_matrix_rows(self):
        self.check('borrowed_matrix_rows')

    def test_mutable_matrix_rows(self):
        self.check('mutable_matrix_rows')

    def test_shared_mutable_tuple_payloads(self):
        self.check('shared_mutable_tuple_payloads')

    def test_borrowed_tuple_list(self):
        self.check('borrowed_tuple_list')

    def test_owned_generator_tuple_values(self):
        self.check('owned_generator_tuple_values')

if __name__=='__main__':unittest.main()
