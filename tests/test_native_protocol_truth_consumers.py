"""Implicit membership/sort consumers retain original source truth callbacks."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as helpers

CASES={
'length_result':'''events=[]
class Result:
 def __init__(self,n):self.n=n
 def __len__(self):
  events.append(self.n)
  return self.n
class Bag:
 def __contains__(self,x):
  events.append(8)
  return Result(x)
bag=Bag()
print(0 in bag,2 in bag,0 not in bag,events)
''',
'bool_priority':'''events=[]
class Result:
 def __init__(self,b):self.b=b
 def __bool__(self):
  events.append(1)
  return self.b
 def __len__(self):
  print('wrong')
  return 1//0
class Bag:
 def __contains__(self,x):return Result(x>0)
bag=Bag()
print(0 in bag,3 not in bag,events)
''',
'plain_instance':'''class Result:pass
class Bag:
 def __contains__(self,x):return Result()
print(3 in Bag(),4 not in Bag())
''',
'negative_length':'''class Result:
 def __len__(self):
  print('length')
  return -1
class Bag:
 def __contains__(self,x):return Result()
print('start')
print(1 in Bag())
''',
'union_result':'''class Result:
 def __len__(self):return 2
class Bag:
 def __contains__(self,x):
  if x==0:return None
  if x==1:return False
  return Result()
bag=Bag()
print(0 in bag,1 in bag,2 in bag)
''',
'chained_distinct_callbacks':'''events=[]
class Result:
 def __init__(self,n):self.n=n
 def __bool__(self):
  events.append(self.n)
  return self.n>0
class Bag:
 def __init__(self,n):self.n=n
 def __contains__(self,x):return Result(self.n)
print(7 in Bag(0) in Bag(3),events)
print(7 in Bag(1) in Bag(2),events)
''',
'sort_result':'''events=[]
class Truth:
 def __init__(self,b):self.b=b
 def __bool__(self):
  events.append(7)
  return self.b
class Item:
 def __init__(self,n):self.n=n
 def __lt__(self,other):return Truth(self.n<other.n)
items=[Item(8),Item(1),Item(5),Item(1)]
items.sort()
print([x.n for x in items],events)
''',
'sort_length_result':'''class Truth:
 def __init__(self,n):self.n=n
 def __len__(self):return self.n
class Item:
 def __init__(self,n):self.n=n
 def __lt__(self,other):return Truth(int(self.n<other.n))
print([x.n for x in sorted([Item(2),Item(9),Item(-1)])])
''',
}

class ProtocolTruthConsumers(unittest.TestCase):
 cases=CASES
 check=helpers.IteratorExecutionTests.check
 def test_source_truth_consumers(self):
  for name in self.cases:
   with self.subTest(name=name):self.check(name)
 def test_occupied_truth_slot_is_not_assumed_absent(self):
  source='class Result:\n __bool__=None\nclass Bag:\n def __contains__(self,x):return Result()\nprint(1 in Bag())\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertTrue(any('__bool__'in d.message for d in result.diagnostics),result.diagnostics)
