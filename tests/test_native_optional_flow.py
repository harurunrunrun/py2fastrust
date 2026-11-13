"""Optional local predicates keep None, binding state and mutable values distinct."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'normalize_optional_default_and_late_empty':'''def total(source=None):
 if source is None:source=[]
 return sum(source)
print(total(),total([1,2]),total([]))
''',
'identity_normalization_keeps_alias':'''def normalize(source):
 if source is None:source=[]
 source.append(8)
 return source
items=[2]
result=normalize(items)
print(items,result,result is items,normalize(None))
''',
'not_none_and_reversed_identity':'''def total(source):
 if None is not source:return sum(source)
 return -1
print(total(None),total([]),total([3,4]))
''',
'inverted_identity':'''def total(source):
 if not(source is not None):source=[5]
 return sum(source)
print(total(None),total([]),total([3,4]))
''',
'positive_truth_excludes_none':'''def total(source):
 if source:return sum(source)
 return -1
print(total(None),total([]),total([3,4]))
''',
'negative_truth_retains_empty_container':'''def total(source):
 if not source:
  print(source is None)
  return 0
 return sum(source)
print(total(None),total([]),total([3,4]))
''',
'guarded_reassignment_retires_old_point':'''def total(source):
 if source is not None:
  print(sum(source))
  source=None
  print(source is None)
 if source is None:source=[9]
 return sum(source)
print(total(None),total([]),total([3,4]))
''',
'captured_readonly_local':'''def total(source):
 def read():return source
 if source is None:source=[]
 return sum(source)+len(read())
print(total(None),total([3,4]))
''',
'captured_writer_cannot_keep_old_refinement':'''def total(source):
 def clear():
  nonlocal source
  source=None
 if source:clear()
 if source is None:return 7
 return len(source)
print(total(None),total([]),total([3,4]))
''',
'none_identity_skips_equality_callback':'''class Tricky:
 def __eq__(self,other):print('eq');return True
def choose(source):
 if source is None:return 4
 return 9
print(choose(None),choose(Tricky()))
''',
'unbound_is_not_none':'''def choose(flag):
 if flag:source=None
 if source is None:return 4
 return 9
print(choose(False))
''',
'zero_trip_keeps_original_none_binding':'''def total(source):
 for _ in range(0):
  if source is None:source=[]
 print(source is None)
 return len(source)
print(total(None))
''',
'nested_empty_allocation_in_specialized_body':'''def total(source=None):
 if source is None:source=[[],[]]
 return sum(len(row)for row in source)
print(total(),total([[3],[4,5]]))
''',
'source_truth_callback_runs_once':'''class Bag:
 def __init__(self,n):self.n=n
 def __bool__(self):
  print('truth',self.n)
  return self.n>0
def choose(source):
 if source:return source.n
 return 8
print(choose(None),choose(Bag(0)),choose(Bag(2)))
''',
'branch_mutation_preserves_other_alias':'''def total(source):
 alias=source
 if source is None:source=[6]
 else:source.append(2)
 print(alias is None)
 return sum(source)
items=[3]
print(total(None),total(items),items)
''',
}


CASES.update({
'range_truth_uses_endpoints_without_length':'''def choose(source):
 if source:return 1
 return 0
print(choose(None),choose(range(0)),choose(range(1,6)),choose(range(6,1)),choose(range(6,1,-2)),choose(range(1,6,-2)))
print(choose(range(-(1<<62),1<<62)),choose(range(1<<62,-(1<<62),-1)))
''',
'range_value_truth_survives_iterator_exhaustion':'''def choose(source):
 if source:return 1
 return 0
values=range(3)
cursor=iter(values)
print(list(cursor),choose(values),list(cursor),choose(values))
''',
'range_zero_step_error_precedes_truth':'''def choose(source):
 print('truth')
 if source:return 1
 return 0
def step():
 print('step')
 return 0
print(choose(range(0,3,step())))
''',
})


CASES.update({
'canonical_truth_alias_on_range_and_iterator':'''truth=bool
values=range(3)
cursor=iter(values)
print(truth(range(0)),truth(values),truth(cursor))
print(list(cursor),truth(cursor),truth(values))
''',
'shadowed_range_keeps_actual_container_truth':'''def range(n):
 print('custom',n)
 return []
if range(3):print('wrong')
else:print('empty')
''',
'actual_tuple_and_list_truth':'''def choose(source):
 if source:return 1
 return 0
print(choose(None),choose(()),choose((0,)),choose([]),choose([0]))
''',
})


CASES['truth_callback_can_rebind_captured_subject']='''callback=None
class Gate:
 def __bool__(self):return callback()
def choose():
 source=Gate()
 def change():
  nonlocal source
  source=None
  return True
 global callback
 callback=change
 if source:return source is None
 return False
print(choose())
'''

class OptionalFlowExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_optional_local_identity_truth_and_temporal_storage(self):
  for name in CASES:
   if name=='truth_callback_can_rebind_captured_subject':continue
   with self.subTest(name=name):self.check(name)
 def test_truth_callback_can_rebind_captured_subject(self):
  self.check('truth_callback_can_rebind_captured_subject')

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(OptionalFlowExecutionTests,_name,None)

class OptionalTruthSelectionTests(unittest.TestCase):
 def test_only_actual_truth_observers_require_iterator_transport(self):
  from py2fastrust.frontend import parse_source
  from py2fastrust.native_constraints import analyze
  from py2fastrust.native_guard_flow import requires_frames
  cases=(('for value in range(3):print(value)\n',False),
   ('if range(3):print(1)\n',True),
   ('truth=bool\nprint(truth(range(3)))\n',True),
   ('def range(n):return []\nif range(3):print(1)\n',False),
   ('if [0]:print(1)\nif (0,):print(2)\n',False))
  for source,expected in cases:
   with self.subTest(source=source):
    unit=parse_source(source)
    self.assertEqual(requires_frames(unit,analyze(unit)),expected)

if __name__=='__main__':unittest.main()
