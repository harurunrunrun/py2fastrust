"""Builtin slice stores preserve captured references, snapshots and exceptions."""
import unittest
import test_native_class_iterators as iterator_tests
import test_native_annotations_assertions as assertion_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'insert_replace_delete_and_clipping':'''a=[1,2,3,4]
a[1:2]=[8,9]
a[4:2]=[7]
a[-20:-18]=[5]
a[2:100]=[]
print(a)
a[:]=[6,7,8]
a[1:]=[9]
print(a)
''',
'extended_positive_negative':'''a=[1,2,3,4,5]
a[::2]=(8,9,10)
a[::-2]=[11,12,13]
print(a)
a[3:0:-1]=range(3)
print(a)
''',
'self_assignment_snapshots':'''a=[1,2,3]
a[1:2]=a
print(a)
a[::-1]=a
print(a)
a[:]=a
print(a)
''',
'shared_element_identity':'''x=[1]
y=[2]
a=[x,y]
a[1:1]=a
print(a)
a[0].append(7)
print(a,a[0] is a[1],a[-1] is y)
''',
'heterogeneous_values':'''a=[1,'two',None]
a[1:2]=[False,(3,4),'end']
print(a)
a[::-2]=[('x',),7,None]
print(a)
''',
'rhs_receiver_bounds_order':'''a=[1,2,3]
def rhs():print('rhs');return iter([8,9])
def owner():print('owner');return a
def bound(label,value):print(label);return value
owner()[bound('lower',1):bound('upper',2):bound('step',1)]=rhs()
print(a)
''',
'stored_cursor_is_consumed_for_each_target':'''a=[1,2]
b=[3,4]
cursor=iter([8,9])
a[:]=b[:]=cursor
print(a,b,list(cursor))
''',
'source_iter_does_not_call_owner_length':'''class Rows:
 def __iter__(self):print('iter');return iter([8,9])
 def __len__(self):print('unexpected');return 99
a=[1,2,3]
a[1:2]=Rows()
print(a)
''',
'iterator_mutation_changes_normalized_length':'''a=[1,2,3]
class Rows:
 def __iter__(self):
  a[:]=[0,1,2,3,4,5]
  print('mutated',a)
  return iter([8])
a[1:-1]=Rows()
print(a)
''',
'immediate_generator_expression':'''a=[1,2,3]
a[1:2]=(value*2 for value in [4,5])
print(a)
''',
'augmented_target_is_captured_once':'''a=[1,2,3]
original=a
def owner():print('owner');return a
def low():print('lower');return 1
def high():print('upper');return 2
def rhs():
 global a
 print('rhs')
 a=[9]
 return [7,8]
owner()[low():high()]+=rhs()
print(a,original)
''',
'extended_length_mismatch':'''a=[1,2,3,4]
a[::2]=[8]
''',
'empty_extended_slice_still_checks_size':'''a=[]
a[::1<<62]=[8]
''',
'zero_step_before_iteration':'''class Rows:
 def __iter__(self):print('unexpected');return iter([8])
a=[1,2,3]
a[::0]=Rows()
''',
'invalid_bound_before_iteration':'''class Rows:
 def __iter__(self):print('unexpected');return iter([8])
a=[1,2,3]
a[1.5:]=Rows()
''',
'noniterable_rhs':'''a=[1,2,3]
a[:]=8
''',
'generator_error_preserves_mutation':'''a=[1,2,3]
def values():
 a.append(7)
 print('mutated',a)
 yield 8
 yield 1//0
a[1:2]=values()
''',
'extended_mismatch_uses_current_length':'''a=[1,2,3]
class Rows:
 def __iter__(self):
  a[:]=[0,1,2,3,4,5]
  print('mutated',a)
  return iter([8])
a[::2]=Rows()
''',
}


CASES.update({
'range_hint_counts_before_division':'''a=[]
a[:]=range(-(1<<62),1<<62,1<<62)
print(a)
a[:]=reversed(range(-(1<<62),1<<62,1<<62))
print(a)
''',
'partially_consumed_range_cursors':'''a=[]
forward=iter(range(8))
backward=reversed(range(8))
print(next(forward),next(forward),next(backward))
a[:]=forward
print(a,list(forward))
a[:]=backward
print(a,list(backward))
''',
'huge_forward_hint_overflows_before_pulls':'''a=[]
a[:]=range(-(1<<62),1<<62)
''',
'huge_reverse_hint_overflows_before_pulls':'''a=[]
a[:]=reversed(range(-(1<<62),1<<62))
''',
'huge_valid_hint_allocation_error':'''a=[]
a[:]=range(1<<62)
''',
'returned_cursor_hint_ignores_owner_length':'''cursor=iter(range(-(1<<62),1<<62))
class Rows:
 def __iter__(self):print('iter');return cursor
 def __len__(self):print('unexpected');return 0
a=[]
a[:]=Rows()
''',
'chained_immediate_generator_is_exhausted':'''a=[]
b=[]
a[:]=b[:]=(value*2 for value in [3,4])
print(a,b)
''',
'generator_creation_and_late_body_binding':'''a=[1,2,3]
scale=2
def source():print('outer');return [4,5]
def lower():
 global scale
 print('lower')
 scale=7
 return 1
a[lower():2]=(value*scale for value in source())
print(a)
''',
'invalid_step_precedes_invalid_lower_and_iteration':'''class Rows:
 def __iter__(self):print('unexpected');return iter([8])
def bound(label,value):print(label);return value
a=[1,2,3]
a[bound('lower',1.5):bound('upper',2.5):bound('step',0)]=Rows()
''',
})


CASES.update({
'read_zero_step_precedes_invalid_lower':'''def bound(label,value):print(label);return value
a=[1,2,3]
print(a[bound('lower',1.5):bound('upper',2.5):bound('step',0)])
''',
'finite_list_and_tuple_receiver':'''def assign(target,source):
 target[1:2]=source
 return target
print(assign([1,2,3],[8,9]))
assign((1,2,3),[8])
''',
'immutable_receiver_errors_before_bound_conversion_or_iteration':'''class Rows:
 def __iter__(self):print('unexpected');return iter([8])
def bound(label,value):print(label);return value
a=(1,2,3)
a[bound('lower',1.5):bound('upper',2):bound('step',0)]=Rows()
''',
'unpack_slice_targets':'''a=[1,2]
b=[3,4]
a[:],b[:]=(iter([8]),iter([9,10]))
print(a,b)
''',
'augmented_repeat':'''a=[1,2,3]
a[1:2]*=3
print(a)
a[1:4]*=0
print(a)
''',
})

class ListSliceAssignmentExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_builtin_list_slice_assignment(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(ListSliceAssignmentExecutionTests,_name,None)

ESCAPING_GENERATOR_SOURCE='a=[]\nsaved=a[:]=(value for value in [1,2])\n'

class RetainedSliceGeneratorTests(unittest.TestCase):
 compare=assertion_tests.AnnotationAndAssertionExecutionTests.compare
 def test_original_multi_target_generator_assignment(self):
  self.compare(ESCAPING_GENERATOR_SOURCE,('',))
 def test_saved_generator_is_exhausted_after_slice_assignment(self):
  self.compare(ESCAPING_GENERATOR_SOURCE+'print(a,list(saved))\n',('',))

class ListSliceAssignmentGuards(unittest.TestCase):
 def test_custom_index_and_inplace_iterable_boundaries_are_explicit(self):
  cases=(('class Index:\n def __index__(self):return 1\na=[1,2]\na[Index():]=[3]\n','__index__'),
   ('a=[1,2]\na[:]+=iter([3])\n','__iadd__'))
  for source,fragment in cases:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)

if __name__=='__main__':unittest.main()
