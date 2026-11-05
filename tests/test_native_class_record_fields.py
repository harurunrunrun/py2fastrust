"""Class record fields use typed tuple slots without changing list semantics."""
import ast
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_class_record_fields as fields
from py2fastrust.native_types import ListType
import test_native_iterator_reductions as _execution

SOURCES={'assignment_order': ['class Ledger:\n'
                      ' def __init__(self):self.record=[7,"shelf"]\n'
                      'def choose():\n'
                      ' print("owner")\n'
                      ' return current\n'
                      'def rhs():\n'
                      ' print("rhs")\n'
                      ' return 2\n'
                      'current=Ledger()\n'
                      'choose().record[0]=rhs()\n'
                      'print(current.record[0],current.record[1])\n',
                      ['']],
 'callback_reentry': ['class Ledger:\n'
                      ' def __init__(self):self.record=[7,"shelf"]\n'
                      ' def bump(self):\n'
                      '  self.record[1]="changed"\n'
                      '  print("rhs",self.record[0])\n'
                      '  return 2\n'
                      ' def run(self):\n'
                      '  self.record[0]+=self.bump()\n'
                      '  print(self.record[0],self.record[1].upper())\n'
                      'Ledger().run()\n',
                      ['']],
 'class_record_owner_alias': ['class Job:\n'
                              ' def __init__(self,number,label):self.record=[number,label]\n'
                              ' def advance(self):self.record[0]+=1\n'
                              'job=Job(7,"shelf")\n'
                              'other=job\n'
                              'other.advance()\n'
                              'print(job.record[0],job.record[1].upper())\n',
                              ['']],
 'class_record_private_alias': ['class Job:\n'
                                ' def __init__(self,number,label):self.record=[number,label]\n'
                                ' def advance(self,count):\n'
                                '  record=self.record\n'
                                '  for _ in range(count):record[0]+=1\n'
                                '  print(record[0],record[1].upper())\n'
                                'Job(7,"shelf").advance(3)\n',
                                ['']],
 'class_record_unpack': ['class Job:\n'
                         ' def __init__(self,number,label):self.record=[number,label]\n'
                         ' def advance(self):\n'
                         '  number,label=self.record\n'
                         '  print(number+1,label.upper())\n'
                         'Job(7,"shelf").advance()\n',
                         ['']],
 'dynamic_index_control': ['class Ledger:\n'
                           ' def __init__(self):self.record=[7,"shelf"]\n'
                           ' def run(self,i):print(self.record[i])\n'
                           'Ledger().run(int(input()))\n',
                           ['0\n', '1\n']],
 'field_replace_control': ['class Ledger:\n'
                           ' def __init__(self):self.record=[7,"shelf"]\n'
                           ' def run(self):\n'
                           '  saved=self.record\n'
                           '  self.record=[11,"new"]\n'
                           '  saved[0]+=2\n'
                           '  print(saved[0],self.record[0])\n'
                           'Ledger().run()\n',
                           ['']],
 'field_type_change_control': ['class Ledger:\n'
                               ' def __init__(self):self.record=[7,"shelf"]\n'
                               ' def run(self):\n'
                               '  self.record[0]="changed"\n'
                               '  print(self.record[0].upper(),self.record[1].upper())\n'
                               'Ledger().run()\n',
                               ['']],
 'heterogeneous_slots_shared_child': ['class Ledger:\n'
                                      ' def __init__(self,row):self.record=[row,"shelf"]\n'
                                      ' def run(self):\n'
                                      '  self.record[0].append(9)\n'
                                      '  self.record[1]="changed"\n'
                                      '  print(self.record[0][0],self.record[1].upper())\n'
                                      'row=[7]\n'
                                      'Ledger(row).run()\n'
                                      'print(row)\n',
                                      ['']],
 'homogeneous_class_field': ['class Counters:\n'
                             ' def __init__(self):self.values=[0,1,2]\n'
                             ' def advance(self):\n'
                             '  for i in range(3):self.values[i]+=2\n'
                             '  print(self.values[0],self.values[2])\n'
                             'Counters().advance()\n',
                             ['']],
 'local_record_direct': ['def solve():\n'
                         ' record=[7,"shelf"]\n'
                         ' record[0]+=2\n'
                         ' number,label=record\n'
                         ' print(number,label.upper())\n'
                         'solve()\n',
                         ['']],
 'local_record_private_alias': ['def solve():\n'
                                ' record=[7,"shelf"]\n'
                                ' alias=record\n'
                                ' alias[0]+=2\n'
                                ' print(record[0],alias[1].upper())\n'
                                'solve()\n',
                                ['']],
 'missing_field': ['class Ledger:\n'
                   ' def __init__(self,visible):\n'
                   '  if visible:self.record=[7,"shelf"]\n'
                   ' def read(self):print(self.record[0],self.record[1])\n'
                   'Ledger(int(input())).read()\n',
                   ['0\n', '1\n']],
 'negative_indices': ['class Ledger:\n'
                      ' def __init__(self):self.record=[7,"shelf"]\n'
                      ' def run(self):\n'
                      '  self.record[-2]+=2\n'
                      '  self.record[-1]=self.record[-1].upper()\n'
                      '  print(self.record[-2],self.record[-1],len(self.record))\n'
                      'Ledger().run()\n',
                      ['']],
 'out_of_bounds_assignment': ['class Ledger:\n'
                              ' def __init__(self):self.record=[7,"shelf"]\n'
                              'def choose():\n'
                              ' print("owner")\n'
                              ' return current\n'
                              'def rhs():\n'
                              ' print("rhs")\n'
                              ' return 2\n'
                              'current=Ledger()\n'
                              'choose().record[2]=rhs()\n',
                              ['']],
 'out_of_bounds_augmented': ['class Ledger:\n'
                             ' def __init__(self):self.record=[7,"shelf"]\n'
                             'def choose():\n'
                             ' print("owner")\n'
                             ' return current\n'
                             'def rhs():\n'
                             ' print("rhs")\n'
                             ' return 2\n'
                             'current=Ledger()\n'
                             'choose().record[2]+=rhs()\n',
                             ['']],
 'out_of_bounds_read': ['class Ledger:\n'
                        ' def __init__(self):self.record=[7,"shelf"]\n'
                        ' def run(self):print(self.record[2])\n'
                        'Ledger().run()\n',
                        ['']],
 'owner_capture': ['class Ledger:\n'
                   ' def __init__(self,n,s):self.record=[n,s]\n'
                   'def choose():\n'
                   ' print("owner")\n'
                   ' return current\n'
                   'def rhs():\n'
                   ' global current\n'
                   ' current=other\n'
                   ' print("rhs")\n'
                   ' return 2\n'
                   'first=Ledger(7,"first")\n'
                   'other=Ledger(11,"second")\n'
                   'current=first\n'
                   'choose().record[0]+=rhs()\n'
                   'print(first.record[0],other.record[0])\n',
                   ['']]}


AUGMENTED_SOURCES={'field_bool_slot': ['class Ledger:\n'
                     ' def __init__(self):self.record=[7,False]\n'
                     ' def run(self):\n'
                     '  self.record[-2]+=2\n'
                     '  self.record[-1]^=True\n'
                     '  print(self.record[-2],self.record[-1])\n'
                     'Ledger().run()\n',
                     ['']],
 'field_scalar_same_slot_reentry': ['class Ledger:\n'
                                    ' def __init__(self):self.record=[7,"shelf"]\n'
                                    ' def rhs(self):\n'
                                    '  print("rhs",self.record[0])\n'
                                    '  self.record[0]=100\n'
                                    '  return 2\n'
                                    ' def run(self):\n'
                                    '  self.record[0]+=self.rhs()\n'
                                    '  print(self.record[0],self.record[1])\n'
                                    'Ledger().run()\n',
                                    ['']],
 'field_shared_list_inplace': ['class Ledger:\n'
                               ' def __init__(self,row):self.record=[row,"shelf"]\n'
                               ' def run(self):\n'
                               '  self.record[0]+=[2]\n'
                               '  print(self.record[0],self.record[1])\n'
                               'row=[1]\n'
                               'ledger=Ledger(row)\n'
                               'ledger.run()\n'
                               'print(row is ledger.record[0],row)\n',
                               ['']],
 'local_bool_slot': ['def run():\n'
                     ' record=[7,False]\n'
                     ' record[0]+=2\n'
                     ' record[1]^=True\n'
                     ' print(record[0],record[1])\n'
                     'run()\n',
                     ['']],
 'local_scalar_effect': ['def rhs():\n'
                         ' print("rhs")\n'
                         ' return 2\n'
                         'def run():\n'
                         ' record=[7,"shelf"]\n'
                         ' record[0]+=rhs()\n'
                         ' print(record[0],record[1])\n'
                         'run()\n',
                         ['']],
 'local_shared_list_inplace': ['def run():\n'
                               ' row=[1]\n'
                               ' record=[row,"shelf"]\n'
                               ' record[0]+=[2]\n'
                               ' print(row is record[0],row,record[0],record[1])\n'
                               'run()\n',
                               ['']],
 'local_tuple_child_inplace': ['def rhs():\n'
                               ' print("rhs")\n'
                               ' return ()\n'
                               'def run():\n'
                               ' row=[1]\n'
                               ' record=[(row,2),"shelf"]\n'
                               ' record[0]+=rhs()\n'
                               ' record[0][0].append(3)\n'
                               ' print(row is record[0][0],row,record[0][1],record[1])\n'
                               'run()\n',
                               ['']]}
SOURCES.update(AUGMENTED_SOURCES)


class ClassRecordFieldProofTests(unittest.TestCase):
    def inspect(self,name):
        found=[];original=fields.prepare
        def observed(model):
            before=ast.dump(model.unit.tree,include_attributes=True)
            result=original(model)
            self.assertEqual(ast.dump(model.unit.tree,include_attributes=True),before)
            for record in model.class_record_fields.fields.values():
                self.assertIsInstance(record.field.kind,ListType)
                found.append(record)
            return result
        with patch.object(fields,'prepare',observed):
            result=transpile(SOURCES[name][0],TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        return result,found

    def test_fixed_slots_have_direct_typed_storage_and_accessors(self):
        result,records=self.inspect('callback_reentry')
        self.assertEqual(len(records),1)
        self.assertIn('field_0:Option<(NativeInt,NativeText)>',result.rust_source)
        self.assertIn('_get_0(owner:&ClassHandle_0)->Result<NativeInt,String>',result.rust_source)
        self.assertIn('_get_1(owner:&ClassHandle_0)->Result<NativeText,String>',result.rust_source)
        self.assertNotIn('fn class_owned_field_0_0_get(',result.rust_source)
        from py2fastrust.rust_pruning import _lex,_parse
        tokens,comments,pairs=_lex(result.rust_source)
        name='class_function_'+str(records[0].field.owner.methods['__init__'].index)
        item=next(item for item in _parse(result.rust_source,tokens,comments,pairs)if item.kind=='fn'and item.name==name)
        initializer=result.rust_source[item.start:item.end]
        self.assertNotIn('class_list(',initializer)
        self.assertNotIn('Rc::try_unwrap',initializer)

    def test_shared_child_leaf_keeps_its_original_reference_abi(self):
        result,records=self.inspect('heterogeneous_slots_shared_child')
        self.assertTrue(records)
        self.assertIn('ClassList<NativeInt>',result.rust_source)

    def test_unproved_dynamic_mutable_aliases_and_unpack_keep_list_storage(self):
        for name in ('dynamic_index_control','field_type_change_control','field_replace_control',
                     'class_record_unpack','class_record_private_alias'):
            result,records=self.inspect(name)
            self.assertFalse(records,name)
        self.assertIn('Option<ClassList<',result.rust_source)

    def test_augmented_results_keep_the_frozen_slot_abi_in_actual_bodies(self):
        from py2fastrust.rust_pruning import _lex,_parse
        for name in ('local_scalar_effect','local_bool_slot','field_scalar_same_slot_reentry','field_bool_slot'):
            result=transpile(SOURCES[name][0],TranspileOptions(license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('Option<(',result.rust_source)
            tokens,comments,pairs=_lex(result.rust_source)
            bodies=[result.rust_source[item.start:item.end]for item in _parse(result.rust_source,tokens,comments,pairs)
                    if item.kind=='fn'and item.name.startswith('class_function_')]
            self.assertTrue(bodies)
            for body in bodies:
                self.assertNotIn('NativeUnion',body,name)
                self.assertNotIn('NativeScalar::',body,name)

    def test_original_tuple_concat_boundary_remains_explicit(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(SOURCES['local_tuple_child_inplace'][0],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertTrue(any('tuple concatenation storage'in value.message for value in result.diagnostics))

    def test_homogeneous_fields_and_existing_local_records_keep_their_paths(self):
        result,records=self.inspect('homogeneous_class_field')
        self.assertFalse(records)
        self.assertIn('field_0:Option<Vec<NativeInt>>',result.rust_source)
        for name in ('local_record_direct','local_record_private_alias'):
            result,records=self.inspect(name)
            self.assertFalse(records)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassRecordFieldExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=_execution.NativeIteratorReductionTests();cls.harness.setUpClass()

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
                        final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else''
                        self.assertEqual(final(actual.stderr),final(expected.stderr))
                        frames=lambda text:re.findall(r'File "[^"\n]+", line (\d+), in ([^\n]+)',text)
                        self.assertEqual(frames(actual.stderr),frames(expected.stderr))


def _test(name):
    def run(self):self.check(name)
    return run


for _name in ['callback_reentry', 'owner_capture', 'assignment_order', 'missing_field', 'negative_indices', 'out_of_bounds_read', 'out_of_bounds_assignment', 'out_of_bounds_augmented', 'dynamic_index_control', 'field_type_change_control', 'field_replace_control', 'heterogeneous_slots_shared_child', 'class_record_owner_alias'] + ['local_scalar_effect', 'local_shared_list_inplace', 'local_bool_slot', 'field_scalar_same_slot_reentry', 'field_shared_list_inplace', 'field_bool_slot']:
    setattr(ClassRecordFieldExecutionTests,'test_'+_name,_test(_name))


if __name__=='__main__':unittest.main()
