"""Local scalar field reads keep name/error timing and mutable aliases."""
import ast,shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_scalar_attribute_projection import read
import test_native_class_iterators as iterator_tests

CASES={'scalar_fields': 'class Record:\n'
                  ' def __init__(self,n):\n'
                  '  self.number=n\n'
                  '  self.flag=True\n'
                  '  self.ratio=1.5\n'
                  '  self.absent=None\n'
                  ' def read(self):return '
                  'self.number,self.flag,self.ratio,self.absent\n'
                  'print(Record(17).read())\n',
 'later_argument_alias_mutation': 'class Counter:\n'
                                  ' def __init__(self,n):self.value=n\n'
                                  'def later(other):\n'
                                  " print('later')\n"
                                  ' other.value+=9\n'
                                  ' return other.value\n'
                                  'def pair(first,second):return first,second\n'
                                  'def read(owner):return '
                                  'pair(owner.value,later(owner))\n'
                                  'owner=Counter(3)\n'
                                  'alias=owner\n'
                                  'print(read(owner),owner.value,owner is '
                                  'alias)\n',
 'rebind_local_after_read': 'class Record:\n'
                            ' def __init__(self,n):self.value=n\n'
                            'def read(flag):\n'
                            ' owner=Record(2)\n'
                            ' old=owner\n'
                            ' before=owner.value\n'
                            ' if flag:owner=Record(9)\n'
                            ' owner.value+=4\n'
                            ' return before,owner.value,old.value,owner is '
                            'old\n'
                            'print(read(False),read(True))\n',
 'root_unbound_before_argument_0': 'class Record:\n'
                                   ' def __init__(self,n):self.value=n\n'
                                   'def later():\n'
                                   " print('later')\n"
                                   ' return 3\n'
                                   'def add(a,b):return a+b\n'
                                   'def read(flag):\n'
                                   ' if flag:owner=Record(7)\n'
                                   ' return add(owner.value,later())\n'
                                   'print(read(bool(int(input()))))\n',
 'root_unbound_before_argument_1': 'class Record:\n'
                                   ' def __init__(self,n):self.value=n\n'
                                   'def later():\n'
                                   " print('later')\n"
                                   ' return 3\n'
                                   'def add(a,b):return a+b\n'
                                   'def read(flag):\n'
                                   ' if flag:owner=Record(7)\n'
                                   ' return add(owner.value,later())\n'
                                   'print(read(bool(int(input()))))\n',
 'root_zero_trip_0': 'class Record:\n'
                     ' def __init__(self,n):self.value=n\n'
                     'def read(count):\n'
                     ' for owner in [Record(8)][:count]:pass\n'
                     ' return owner.value\n'
                     'print(read(int(input())))\n',
 'root_zero_trip_1': 'class Record:\n'
                     ' def __init__(self,n):self.value=n\n'
                     'def read(count):\n'
                     ' for owner in [Record(8)][:count]:pass\n'
                     ' return owner.value\n'
                     'print(read(int(input())))\n',
 'delete_root_binding': 'class Record:\n'
                        ' def __init__(self,n):self.value=n\n'
                        'def read():\n'
                        ' owner=Record(5)\n'
                        ' del owner\n'
                        ' return owner.value\n'
                        'print(read())\n',
 'optional_field_and_error_0': 'class Record:\n'
                               ' def __init__(self,flag):\n'
                               '  if flag:self.value=23\n'
                               ' def read(self):return self.value\n'
                               'print(Record(bool(int(input()))).read())\n',
 'optional_field_and_error_1': 'class Record:\n'
                               ' def __init__(self,flag):\n'
                               '  if flag:self.value=23\n'
                               ' def read(self):return self.value\n'
                               'print(Record(bool(int(input()))).read())\n',
 'deleted_field_error': 'class Record:\n'
                        ' def __init__(self,n):self.value=n\n'
                        ' def read(self):\n'
                        '  del self.value\n'
                        '  return self.value\n'
                        'print(Record(7).read())\n',
 'restore_field_after_delete': 'class Record:\n'
                               ' def __init__(self,n):self.value=n\n'
                               ' def read(self):\n'
                               '  del self.value\n'
                               '  self.value=11\n'
                               '  return self.value\n'
                               'print(Record(7).read())\n',
 'loop_cache_and_mutation': 'class Record:\n'
                            ' def __init__(self,n):self.value=n\n'
                            ' def invariant(self,count):\n'
                            '  total=0\n'
                            '  for i in range(count):total+=self.value+i\n'
                            '  return total\n'
                            ' def changing(self,count):\n'
                            '  total=0\n'
                            '  for i in range(count):\n'
                            '   total+=self.value\n'
                            '   self.value+=i\n'
                            '  return total,self.value\n'
                            'owner=Record(4)\n'
                            'print(owner.invariant(0),owner.invariant(5),owner.changing(5))\n',
 'finite_receiver_union_excluded': 'class Left:\n'
                                   ' def __init__(self):self.value=3\n'
                                   'class Right:\n'
                                   ' def __init__(self):self.value=13\n'
                                   'def read(flag):\n'
                                   ' owner=Left()if flag else Right()\n'
                                   ' return owner.value\n'
                                   'print(read(False),read(True))\n',
 'point_storage_union_excluded': 'class Record:\n'
                                 ' def __init__(self,n):self.value=n\n'
                                 'def read(flag):\n'
                                 ' owner=Record(8)\n'
                                 ' if flag:owner=None\n'
                                 ' if owner is None:return 0\n'
                                 ' return owner.value\n'
                                 'print(read(False),read(True))\n',
 'captured_root_excluded': 'class Record:\n'
                           ' def __init__(self,n):self.value=n\n'
                           'def make():\n'
                           ' owner=Record(3)\n'
                           ' def read():return owner.value\n'
                           ' owner.value=14\n'
                           ' return read\n'
                           'print(make()())\n',
 'module_root_excluded': 'class Record:\n'
                         ' def __init__(self,n):self.value=n\n'
                         'owner=Record(3)\n'
                         'def read():return owner.value\n'
                         'print(read())\n',
 'comprehension_bindings_excluded': 'class Record:\n'
                                    ' def __init__(self,n):self.value=n\n'
                                    'def read(owner):return [owner.value for '
                                    'owner in [Record(2),owner]]\n'
                                    'print(read(Record(9)))\n',
 'outer_in_generator_excluded': 'class Record:\n'
                                ' def __init__(self,n):self.value=n\n'
                                'def read(owner):return sum(owner.value+i for '
                                'i in range(4))\n'
                                'print(read(Record(9)))\n',
 'mutable_field_excluded': 'class Record:\n'
                           ' def __init__(self):self.values=[2,3]\n'
                           ' def read(self):return self.values\n'
                           'owner=Record()\n'
                           'items=owner.read()\n'
                           'items.append(7)\n'
                           'print(owner.values,items is owner.values)\n',
 'class_fallback_and_shadow': 'class Record:\n'
                              ' value=10\n'
                              ' def __init__(self,flag):\n'
                              '  if flag:self.value=4\n'
                              ' def read(self):return self.value\n'
                              'print(Record(False).read(),Record(True).read())\n',
 'method_capture_root': 'class Record:\n'
                        ' def __init__(self,n):self.value=n\n'
                        ' def callback(self):\n'
                        '  def read():return self.value\n'
                        '  return read\n'
                        'owner=Record(5)\n'
                        'callback=owner.callback()\n'
                        'owner.value=12\n'
                        'print(callback())\n',
 'type_change_separate_slots': 'class Record:\n'
                               ' def __init__(self,n):self.value=n\n'
                               'def read():\n'
                               ' owner=Record(3)\n'
                               ' first=owner.value\n'
                               ' owner=17\n'
                               ' second=owner+2\n'
                               ' owner=Record(7)\n'
                               ' return first,second,owner.value\n'
                               'print(read())\n'}
INPUTS={'optional_field_and_error_0': '0\n',
 'optional_field_and_error_1': '1\n',
 'root_unbound_before_argument_0': '0\n',
 'root_unbound_before_argument_1': '1\n',
 'root_zero_trip_0': '0\n',
 'root_zero_trip_1': '1\n'}
BOUNDARIES={'custom_attribute_protocol_boundary': 'class Record:\n'
                                       ' def __init__(self):self.value=3\n'
                                       ' def __getattribute__(self,name):\n'
                                       "  if name=='value':return 19\n"
                                       '  return '
                                       'object.__getattribute__(self,name)\n'
                                       'def read(owner):return owner.value\n'
                                       'print(read(Record()))\n',
 'property_descriptor_boundary': 'class Record:\n'
                                 ' @property\n'
                                 ' def value(self):return 31\n'
                                 'def read(owner):return owner.value\n'
                                 'print(read(Record()))\n'}

class ScalarAttributeProofs(unittest.TestCase):
 def compile(self,name,mode='i64',disabled=False):
  calls=[]
  def project(emitter,node):
   result=None if disabled else read(emitter,node)
   if result is not None:
    self.assertIsInstance(node,ast.Attribute)
    self.assertIsInstance(node.value,ast.Name)
    self.assertGreaterEqual(emitter.model.unit.ordinal(node),0)
    calls.append((emitter.plan.scope,node.attr,result.kind,result.code))
   return result
  with patch('py2fastrust.native_scalar_attribute_projection.read',side_effect=project):
   result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return result,calls
 def test_fixed_scalar_fields_borrow_the_local_receiver(self):
  for mode in ('i64','i128'):
   result,calls=self.compile('scalar_fields',mode)
   self.assertEqual({kind for _,_,kind,_ in calls},{'int','bool','float','none'})
   for scope,field,kind,code in calls:
    self.assertIn('.as_ref().ok_or_else(',code)
    self.assertRegex(code,r'class_get_\d+_\d+\(class_temp_\d+\)')
    self.assertNotRegex(code,r'class_local_\d+\.clone\(\)')
 def test_bigint_fields_keep_the_existing_owned_path(self):
  result,calls=self.compile('scalar_fields','bigint')
  self.assertEqual({kind for _,_,kind,_ in calls},{'bool','float','none'})
 def test_unproved_owners_and_fields_keep_identical_emission(self):
  names=('finite_receiver_union_excluded','point_storage_union_excluded',
         'captured_root_excluded','module_root_excluded',
         'comprehension_bindings_excluded','outer_in_generator_excluded',
         'mutable_field_excluded','class_fallback_and_shadow','method_capture_root')
  for name in names:
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.compile(name,mode)
     old,_=self.compile(name,mode,disabled=True)
     self.assertFalse(calls)
     self.assertEqual(result.rust_source,old.rust_source)
 def test_existing_lazy_field_cache_is_preserved(self):
  result,calls=self.compile('loop_cache_and_mutation')
  self.assertTrue(any('initialized loop field'in code for _,_,_,code in calls))
 def test_unimplemented_protocols_keep_positioned_diagnostics(self):
  for name,source in BOUNDARIES.items():
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     current=transpile(source,TranspileOptions(integer=mode,license='none'))
     with patch('py2fastrust.native_scalar_attribute_projection.read',return_value=None):
      old=transpile(source,TranspileOptions(integer=mode,license='none'))
     self.assertFalse(current.success)
     self.assertEqual([str(d)for d in current.diagnostics],[str(d)for d in old.diagnostics])
     self.assertTrue(all(d.code=='E006'for d in current.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ScalarAttributeExecution(unittest.TestCase):
 cases=CASES
 inputs=INPUTS
 check=iterator_tests.IteratorExecutionTests.check
 def test_scalar_fields(self):self.check('scalar_fields')
 def test_later_argument_alias_mutation(self):self.check('later_argument_alias_mutation')
 def test_rebind_local_after_read(self):self.check('rebind_local_after_read')
 def test_root_unbound_before_argument_0(self):self.check('root_unbound_before_argument_0')
 def test_root_unbound_before_argument_1(self):self.check('root_unbound_before_argument_1')
 def test_root_zero_trip_0(self):self.check('root_zero_trip_0')
 def test_root_zero_trip_1(self):self.check('root_zero_trip_1')
 def test_delete_root_binding(self):self.check('delete_root_binding')
 def test_optional_field_and_error_0(self):self.check('optional_field_and_error_0')
 def test_optional_field_and_error_1(self):self.check('optional_field_and_error_1')
 def test_deleted_field_error(self):self.check('deleted_field_error')
 def test_restore_field_after_delete(self):self.check('restore_field_after_delete')
 def test_loop_cache_and_mutation(self):self.check('loop_cache_and_mutation')
 def test_finite_receiver_union_excluded(self):self.check('finite_receiver_union_excluded')
 def test_point_storage_union_excluded(self):self.check('point_storage_union_excluded')
 def test_captured_root_excluded(self):self.check('captured_root_excluded')
 def test_module_root_excluded(self):self.check('module_root_excluded')
 def test_comprehension_bindings_excluded(self):self.check('comprehension_bindings_excluded')
 def test_outer_in_generator_excluded(self):self.check('outer_in_generator_excluded')
 def test_mutable_field_excluded(self):self.check('mutable_field_excluded')
 def test_class_fallback_and_shadow(self):self.check('class_fallback_and_shadow')
 def test_method_capture_root(self):self.check('method_capture_root')
 def test_type_change_separate_slots(self):self.check('type_change_separate_slots')
