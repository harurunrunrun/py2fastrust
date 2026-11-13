"""Mapping deletion preserves source order, hashing and live shared identity."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as helpers

CASES={
'alias_and_order':'''d={1:4,2:8,3:9}
alias=d
del d[2]
d[2]=10
del alias[True]
print(list(d.items()),list(alias))
''',
'receiver_and_key_effects':'''events=[]
left={3:8}
right={3:9}
def owner():
 events.append(1)
 return left
def key():
 global left
 events.append(2)
 left=right
 return 3
del owner()[key()]
print(events,left,right)
''',
'empty_missing':'''d={}
print('before')
del d['absent']
print('after')
''',
'multiple_targets_stop_on_error':'''d={1:7,2:9}
def key(n):
 print('key',n)
 return n
del d[key(1)],d[key(4)],d[key(2)]
''',
'tuple_layout_query':'''d={(2,4):8,(3,7):9}
key=tuple([2,4])
del d[key]
print(d)
''',
'unhashable_list':'''d={1:7}
def key():
 print('key')
 return [1]
del d[key()]
''',
'unhashable_tuple':'''d={1:7}
del d[([],)]
''',
'defaultdict_missing':'''from collections import defaultdict
def factory():
 print('unexpected factory')
 return 9
d=defaultdict(factory)
del d[4]
''',
'counter_missing':'''from collections import Counter
d=Counter([2,2,3])
alias=d
del d[2]
del d[99]
print(list(alias.items()))
''',
'live_iterator':'''d={1:7,2:8,3:9}
for x in d:
 print(x)
 del d[x]
''',
'nested_targets':'''d={1:8,2:9,3:7}
del (d[1],(d[2],))
print(d)
''',
}

class MappingDeletionTests(unittest.TestCase):
 cases=CASES
 check=helpers.IteratorExecutionTests.check
 def test_mapping_deletion(self):
  for name in self.cases:
   with self.subTest(name=name):self.check(name)
 def test_custom_hash_key_remains_explicit(self):
  source='class Key:pass\nd={1:2}\ndel d[Key()]\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertTrue(any('hash' in d.message for d in result.diagnostics),result.diagnostics)
