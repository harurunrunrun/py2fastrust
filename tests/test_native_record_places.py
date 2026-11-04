"""Physical fixed records keep list semantics and independent ownership proofs."""
import ast
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_types import ListType
from py2fastrust import native_record_places as places
import test_native_iterator_reductions as _execution

SOURCES={'bool_type_change_excluded': ['def main():\n'
                               ' record=[1,"text"]\n'
                               ' record[0]=True\n'
                               ' print(record[0],record[1])\n'
                               'main()\n',
                               ['']],
 'boolean_constant_store': ['def rhs():\n'
                            ' print("rhs")\n'
                            ' return "changed"\n'
                            'def main():\n'
                            ' record=[1,"text"]\n'
                            ' print(record[0])\n'
                            ' record[True]=rhs()\n'
                            ' print(record[0],record[1])\n'
                            'main()\n',
                            ['']],
 'class_fixed_field': ['class Record:\n'
                       ' def __init__(self):self.data=[3,"tree"]\n'
                       ' def update(self):\n'
                       '  self.data[0]+=4\n'
                       '  self.data[-1]=self.data[-1].upper()\n'
                       ' def show(self):print(self.data[0],self.data[1],len(self.data))\n'
                       'a=Record()\n'
                       'a.update()\n'
                       'a.show()\n',
                       ['']],
 'closure_capture_excluded': ['def main():\n'
                              ' record=[1,"text"]\n'
                              ' def read():return record[0]\n'
                              ' record[0]=3\n'
                              ' print(read(),record[1])\n'
                              'main()\n',
                              ['']],
 'constant_read_bounds': ['def main():\n record=[1,"text"]\n print(record[-3])\nmain()\n', ['']],
 'constant_store_bounds_rhs': ['def rhs():\n'
                               ' print("rhs")\n'
                               ' return 7\n'
                               'def main():\n'
                               ' record=[1,"text"]\n'
                               ' record[2]=rhs()\n'
                               'main()\n',
                               ['']],
 'dynamic_index': ['def main():\n'
                   ' record=[1,"dynamic"]\n'
                   ' index=int(input())\n'
                   ' print(record[index])\n'
                   'main()\n',
                   ['0\n', '1\n', '-1\n', '2\n']],
 'identity_observer': ['def main():\n'
                       ' record=[1,"id"]\n'
                       ' print(record is record,record[0],record[1])\n'
                       'main()\n',
                       ['']],
 'int_bool_record_loop': ['def main():\n'
                          ' record=[1,False]\n'
                          ' for i in range(3):\n'
                          '  record[0]+=2\n'
                          '  record[1]=not record[1]\n'
                          ' print(record[0],record[1])\n'
                          'main()\n',
                          ['']],
 'list_alias': ['def main():\n'
                ' record=[1,"alias"]\n'
                ' other=record\n'
                ' other[0]+=4\n'
                ' print(record[0],other[1],record is other)\n'
                'main()\n',
                ['']],
 'local_compatible_rebind': ['def main():\n'
                             ' record=[1,"one"]\n'
                             ' if int(input()):record=[2,"two"]\n'
                             ' print(record[0]+1,record[1].upper())\n'
                             'main()\n',
                             ['0\n', '1\n']],
 'local_compatible_stores': ['def rhs():\n'
                             ' print("rhs")\n'
                             ' return 9\n'
                             'def main():\n'
                             ' record=[7,"label"]\n'
                             ' record[0]=rhs()\n'
                             ' record[-1]=record[-1].upper()\n'
                             ' record[0]+=3\n'
                             ' print(record[0],record[1])\n'
                             'main()\n',
                             ['']],
 'local_constant_reads': ['def main():\n'
                          ' record=[4,"word"]\n'
                          ' print(record[0]+3,record[-1].upper(),len(record))\n'
                          'main()\n',
                          ['']],
 'local_missing_binding': ['def main():\n'
                           ' if int(input()):record=[1,"one"]\n'
                           ' print(record[0],record[1])\n'
                           'main()\n',
                           ['0\n', '1\n']],
 'local_unpack': ['def main():\n'
                  ' record=[7,"label"]\n'
                  ' number,label=record\n'
                  ' print(number+1,label.upper(),len(record))\n'
                  'main()\n',
                  ['']],
 'multiple_literal_definitions_excluded': ['def main():\n'
                                           ' record=[1,"text"]\n'
                                           ' record=[2,"other"]\n'
                                           ' print(record[0],record[1])\n'
                                           'main()\n',
                                           ['']],
 'nested_tuple_leaf': ['def main():\n'
                       ' record=[(2,3),"text"]\n'
                       ' (first,second),label=record\n'
                       ' print(first+second,label,record[0][1])\n'
                       'main()\n',
                       ['']],
 'resize': ['def main():\n'
            ' record=[1,"size"]\n'
            ' record.append(2)\n'
            ' print(record[0],record[1],record[2],len(record))\n'
            'main()\n',
            ['']],
 'selected_invalid_store_rhs': ['def rhs():\n'
                                ' print("rhs")\n'
                                ' return 7\n'
                                'def main():\n'
                                ' record=[1,"text"]\n'
                                ' print(record[0])\n'
                                ' record[2]=rhs()\n'
                                'main()\n',
                                ['']],
 'slot_type_change': ['def main():\n'
                      ' record=[1,"shape"]\n'
                      ' record[0]="new"\n'
                      ' print(record[0],record[1])\n'
                      'main()\n',
                      ['']],
 'too_few_names': ['def main():\n record=[1,"text"]\n print(record[0])\n a,b,c=record\nmain()\n',
                   ['']],
 'too_many_names': ['def main():\n record=[1,"text"]\n print(record[0])\n a,=record\nmain()\n',
                    ['']],
 'unpack_partial_target_error': ['def target():\n'
                                 ' print("first target")\n'
                                 ' return [0]\n'
                                 'def main():\n'
                                 ' record=[1,"text"]\n'
                                 ' sink=[0]\n'
                                 ' target()[0],sink[9]=record\n'
                                 'main()\n',
                                 ['']],
 'unpack_same_record_target': ['def main():\n'
                               ' record=[2,"label"]\n'
                               ' record[0],label=record\n'
                               ' print(record[0],label,record[1])\n'
                               'main()\n',
                               ['']],
 'unpack_snapshot_before_targets': ['def main():\n'
                                    ' record=[2,"label"]\n'
                                    ' record[0],record[1]=record\n'
                                    ' print(record[0],record[1])\n'
                                    'main()\n',
                                    ['']],
 'whole_return_excluded': ['def make():\n'
                           ' record=[1,"text"]\n'
                           ' return record\n'
                           'record=make()\n'
                           'record[0]=8\n'
                           'print(record[0],record[1])\n',
                           ['']]}


class RecordPlaceProofTests(unittest.TestCase):
    def inspect(self,name):
        found=[];original=places.prepare
        def observed(emitter):
            unit=emitter.model.unit;before=ast.dump(unit.tree,include_attributes=True)
            result=original(emitter)
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
            for record in result.values():
                self.assertIsInstance(record.kind,ListType)
                self.assertTrue(emitter.rust_type(record.kind).startswith('ClassList<'))
                found.append(record)
            return result
        with patch.object(places,'prepare',observed):result=transpile(SOURCES[name][0],TranspileOptions(filename='record.py',license='none'))
        self.assertTrue(result.success,result.diagnostics)
        return result,found

    def test_explicit_unpack_and_constant_indices_use_physical_tuples(self):
        for name in ('local_unpack','local_constant_reads'):
            result,records=self.inspect(name)
            self.assertTrue(records,name)
            self.assertIn('Option<(NativeInt,NativeText)>',result.rust_source)
            self.assertNotIn('Option<Vec<',result.rust_source)
            self.assertNotIn('class_list(vec![',result.rust_source)

    def test_compatible_stores_keep_the_frozen_independent_slot_types(self):
        result,records=self.inspect('local_compatible_stores')
        self.assertTrue(records)
        self.assertTrue(all(record.fields==('int','str')for record in records))
        self.assertIn('Option<(NativeInt,NativeText)>',result.rust_source)

    def test_alias_identity_resize_rebind_and_type_changes_keep_existing_places(self):
        for name in ('list_alias','identity_observer','resize','slot_type_change','bool_type_change_excluded',
                     'local_compatible_rebind','multiple_literal_definitions_excluded','dynamic_index'):
            result,records=self.inspect(name)
            self.assertFalse(records,name)

    def test_captures_returns_and_class_fields_keep_existing_storage(self):
        for name in ('closure_capture_excluded','whole_return_excluded','class_fixed_field'):
            result,records=self.inspect(name)
            self.assertFalse(records,name)

    def test_unproved_conditional_binding_retains_optional_vector_storage(self):
        result,records=self.inspect('local_missing_binding')
        self.assertFalse(records)
        self.assertIn('Option<Vec<',result.rust_source)
        self.assertIn('UnboundLocalError',result.rust_source)

    def test_numeric_record_is_not_a_shared_list_borrow_region(self):
        result,records=self.inspect('int_bool_record_loop')
        self.assertTrue(records)
        self.assertIn('Option<(NativeInt,bool)>',result.rust_source)
        self.assertNotIn('.map(|owner|owner.borrow_mut())',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class RecordPlaceExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=_execution.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def check(self,name):
        source,inputs=SOURCES[name]
        for mode in ('i64','i128','bigint'):
            for release in (False,True):
                compiled=self.harness.compile(source,mode,release=release)
                for data in inputs:
                    with self.subTest(name=name,mode=mode,release=release,data=data):
                        actual=subprocess.run([str(compiled[1])],input=data,capture_output=True,text=True,timeout=10)
                        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=10)
                        self.assertEqual(actual.stdout,expected.stdout)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                        final=lambda s:s.rstrip().splitlines()[-1]if s.strip()else''
                        self.assertEqual(final(actual.stderr),final(expected.stderr))
                        frames=lambda s:re.findall(r'File "[^"\n]+", line (\d+), in ([^\n]+)',s)
                        self.assertEqual(frames(actual.stderr),frames(expected.stderr))

    def test_unpack_and_constant_index_reads(self):self.check('local_unpack');self.check('local_constant_reads')

    def test_rhs_order_compatible_stores_and_augmented_update(self):self.check('local_compatible_stores')

    def test_original_values_are_snapshotted_before_target_updates(self):self.check('unpack_snapshot_before_targets')

    def test_nested_tuple_leaf_keeps_its_normal_value_abi(self):self.check('nested_tuple_leaf')

    def test_out_of_range_read_and_store_rhs_order(self):
        self.check('constant_read_bounds');self.check('constant_store_bounds_rhs');self.check('selected_invalid_store_rhs')

    def test_unpack_arity_error_text_and_frames(self):self.check('too_few_names');self.check('too_many_names')

    def test_unbound_binding_keeps_its_original_failure(self):self.check('local_missing_binding')

    def test_partial_target_effects_are_not_reordered(self):self.check('unpack_partial_target_error')

    def test_numeric_loop_keeps_typed_record_storage(self):self.check('int_bool_record_loop');self.check('boolean_constant_store')


if __name__=='__main__':unittest.main()
