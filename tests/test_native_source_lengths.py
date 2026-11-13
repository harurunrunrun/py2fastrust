"""Canonical source length, truth and reverse protocols preserve effects."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'length_and_truth':'''class Bag:
 def __init__(self,n):self.n=n
 def __len__(self):
  print('len',self.n)
  return self.n
x=Bag(2)
print(len(x),bool(x),not x)
if x:print('yes')
x.n=0
print(bool(x))
while x:print('unreachable')
''',
'bool_precedence_and_ownership':'''class Bag:
 def __init__(self,n):self.n=n
 def __len__(self):
  print('unexpected')
  return 9
 def __bool__(self):
  print('bool',self.n)
  return self.n>0
x=Bag(0)
y=Bag(1)
print((x or y) is y,(y and x) is x, bool(x),not y)
''',
'known_absence_and_union':'''class Bag:pass
class Empty:
 def __len__(self):return 0
for value in [Bag(),Empty(),False]:
 print(bool(value),not value)
''',
'len_bool_return':'''class Bag:
 def __len__(self):return True
print(len(Bag()),bool(Bag()))
''',
'len_negative':'''class Bag:
 def __len__(self):return -1
print(len(Bag()))
''',
'len_invalid_result':'''class Bag:
 def __len__(self):return 1.5
print(len(Bag()))
''',
'bool_invalid_result':'''class Bag:
 def __bool__(self):return 1
print(bool(Bag()))
''',
'reversed_original_cursor':'''class Bag:
 def __init__(self):self.cursor=iter([3,2,1])
 def __reversed__(self):
  print('reverse')
  return self.cursor
bag=Bag()
a=reversed(bag)
b=reversed(bag)
print(a is b,next(a),next(b),list(a))
''',
'reversed_unchecked_result':'''class Bag:
 def __init__(self):self.values=[1,2]
 def __reversed__(self):return self.values
bag=Bag()
result=reversed(bag)
result.append(3)
print(result is bag.values,bag.values)
class Nothing:
 def __reversed__(self):return None
print(reversed(Nothing()))
''',
'hint_order_and_owner_mutation':'''class Bag:
 def __init__(self):self.values=[3,1]
 def __iter__(self):
  print('iter')
  self.values.append(2)
  return iter(self.values)
 def __len__(self):
  print('len')
  self.values.append(0)
  return len(self.values)
print(list(Bag()))
print(tuple(Bag()))
print(sorted(Bag()))
''',
'hint_bad_type_suppression':'''class Bag:
 def __iter__(self):
  print('iter')
  return iter([3,1])
 def __len__(self):
  print('len')
  return None
print(list(Bag()),tuple(Bag()),sorted(Bag()))
''',
'hint_raised_typeerror_suppression':'''class Bag:
 def __iter__(self):return iter([3,1])
 def __len__(self):
  print('hint')
  raise TypeError('ignored')
print(list(Bag()),tuple(Bag()),sorted(Bag()))
''',
'hint_negative_propagates':'''class Bag:
 def __iter__(self):
  print('iter')
  return iter([3,1])
 def __len__(self):
  print('len')
  return -1
print(list(Bag()))
''',
'hint_valueerror_propagates':'''class Bag:
 def __iter__(self):return iter([3,1])
 def __len__(self):raise ValueError('hint')
print(sorted(Bag()))
''',
}


CASES.update({
'while_length_fallback':'''class Bag:
 def __init__(self):self.n=3
 def __len__(self):return self.n
bag=Bag()
while bag:
 print(bag.n)
 bag.n-=1
print(bool(bag))
''',
'hint_precedes_generator_body':'''class Bag:
 def __iter__(self):
  print('pull')
  yield 3
  yield 1
 def __len__(self):
  print('len')
  return 2
print(list(Bag()),tuple(Bag()),sorted(Bag()))
''',
'hint_retained_typeerror_traceback':'''saved=TypeError('ignored')
class Bag:
 def __iter__(self):return iter([1,2])
 def __len__(self):raise saved
print(list(Bag()))
raise saved
''',
'hint_storage_limit':'''class Bag:
 def __iter__(self):return iter([1,2])
 def __len__(self):return 1<<62
print(list(Bag()))
''',
})


CASES.update({
'saved_builtin_protocol_identity':'''class Bag:
 def __len__(self):print('len');return 2
 def __reversed__(self):print('reverse');return iter([4,3])
length=len
truth=bool
reverse=reversed
bag=Bag()
print(length(bag),truth(bag),list(reverse(bag)))
''',
'boolean_result_union_validates_current_variant':'''class Bag:
 def __init__(self,n):self.n=n
 def __bool__(self):
  if self.n:return True
  return 1
print(bool(Bag(1)))
print(bool(Bag(0)))
''',
})

class SourceLengthExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_length_truth_reversed_and_hint_protocols(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(SourceLengthExecutionTests,_name,None)

class SourceLengthGuards(unittest.TestCase):
 def test_occupied_slots_and_unproved_index_protocol_are_explicit(self):
  for source,fragment in (
   ('class Bag:\n __len__=None\nprint(bool(Bag()))\n','__len__'),
   ('class Bag:\n __len__=lambda self:1\nprint(len(Bag()))\n','lambda'),
   ('class Base:\n def __len__(self):return 0\nclass Bag(Base):pass\nprint(bool(Bag()))\n','inherit'),
   ('class Index:\n def __index__(self):return 1\nclass Bag:\n def __len__(self):return Index()\nprint(len(Bag()))\n','__index__'),
   ('class Bag:\n def __iter__(self):return iter([1,2])\n def __len__(self):\n  print(1)\n  raise TypeError("hint")\n def __length_hint__(self):\n  print(2)\n  return 3\nprint(list(Bag()),sorted(Bag()))\n','__length_hint__'),
   ('class Cursor:\n def __iter__(self):return self\n def __next__(self):return 1\n def __len__(self):print(8);return 1\nclass Bag:\n def __iter__(self):return Cursor()\nprint(tuple(Bag()))\n','__next__')):
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)

if __name__=='__main__':unittest.main()
