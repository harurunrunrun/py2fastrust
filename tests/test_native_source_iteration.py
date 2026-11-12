"""Source __iter__ invokes canonical methods and preserves native cursor identity."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'direct_containers_and_for':'''class Row:
 def __init__(self,x,y):self.x=x;self.y=y
 def __iter__(self):return iter([self.x,self.y])
row=Row(3,4)
print(list(row),tuple(row),sum(row),min(row),max(row),any(row),all(row))
for value in row:print(value)
''',
'shared_original_iterator_identity':'''class Row:
 def __init__(self):self.saved=iter([1,2,3,4])
 def __iter__(self):
  print('iter')
  return self.saved
row=Row()
first=iter(row)
second=iter(row)
print(first is second,next(first),next(second),list(row),list(first))
''',
'creation_order_and_owner_once':'''class Row:
 def __init__(self,values):self.values=values
 def __iter__(self):
  print('iter')
  return iter(self.values)
def owner():
 print('owner')
 return Row([2,3])
def start():
 print('start')
 return 7
stream=enumerate(owner(),start())
print('created',list(stream))
''',
'generator_receiver_is_owned_and_live':'''events=[]
class Row:
 def __init__(self):self.x=1;self.y=2
 def __iter__(self):
  events.append(10)
  yield self.x
  yield self.y
row=Row()
stream=iter(row)
print(events)
row.x=8
print(next(stream),events)
row.y=9
print(next(stream),next(stream,None),events)
''',
'cursor_captures_iter_call_snapshot':'''class Row:
 def __init__(self):self.x=1;self.y=2
 def __iter__(self):return iter([self.x,self.y])
row=Row()
stream=iter(row)
row.x=8
print(list(stream),list(row))
''',
'map_filter_zip_creation':'''class Row:
 def __init__(self,values):self.values=values
 def __iter__(self):
  print('iter')
  return iter(self.values)
row=Row([0,2,3])
stream=map(int,row)
print('created',list(stream))
print(list(filter(None,row)))
print(list(zip(row,row)))
''',
'comprehension_and_unpack':'''class Row:
 def __init__(self):self.values=[3,4]
 def __iter__(self):return iter(self.values)
row=Row()
first,second=row
print(first,second,[value*2 for value in row],sum(value+1 for value in row))
''',
'comprehension_keeps_map_creation_effects':'''class Row:
 def __iter__(self):
  print('iter')
  return iter([2,3])
print([value+1 for value in map(int,Row())])
''',
'registered_collection_consumers':'''from collections import deque,Counter,defaultdict
class Row:
 def __iter__(self):return iter([2,3,2])
class Pairs:
 def __iter__(self):return iter([(1,4),(2,5)])
print(list(deque(Row())),list(Counter(Row()).items()))
print(dict(Pairs()),dict(defaultdict(int,Pairs())))
''',
'registered_standard_iterator_consumers':'''import itertools
from functools import reduce
from heapq import nsmallest
class Row:
 def __iter__(self):return iter([2,3])
print(list(itertools.accumulate(Row())))
print(list(itertools.product(Row(),repeat=2)))
print(reduce(lambda a,b:a+b,Row(),0),nsmallest(1,Row()))
''',
'text_join_and_starred_unpack':'''class Words:
 def __iter__(self):return iter(['one','two'])
class Numbers:
 def __iter__(self):return iter([1,2,3])
print(','.join(Words()))
first,*middle,last=Numbers()
print(first,middle,last)
''',
'for_else_and_break':'''class Row:
 def __iter__(self):return iter([1,2,3])
for value in Row():
 print(value)
 if value==2:break
else:print(88)
for value in Row():print(value)
else:print(99)
''',
'body_error_at_construction':'''class Row:
 def __iter__(self):
  print('called')
  return iter([1//0])
row=Row()
print('created')
stream=iter(row)
''',
'generator_error_at_pull':'''class Row:
 def __iter__(self):
  print('entered')
  yield 1//0
row=Row()
stream=iter(row)
print('created')
print(next(stream))
''',
'next_does_not_call_iter':'''class Row:
 def __iter__(self):
  print('iter')
  return iter([1])
print(next(Row(),9))
''',
'empty_cursor_keeps_iter_side_effects':'''class Empty:
 def __iter__(self):
  print('iter')
  return iter(())
row=Empty()
print(list(row),any(row),all(row),sum(row),min(row,default=9))
''',
'source_generator_iterates_a_source_instance':'''class Row:
 def __iter__(self):
  print('iter')
  return iter([2,3])
def values(row):
 for value in row:
  yield value*2
stream=values(Row())
print('created')
print(list(stream))
''',
}

class SourceIterationExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_source_iter_protocol(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(SourceIterationExecutionTests,_name,None)

class SourceIterationGuards(unittest.TestCase):
 def test_invalid_or_incomplete_iterator_protocols_are_explicit(self):
  cases=(('class Row:\n def __iter__(self):return [1,2]\nprint(list(Row()))\n','registered native iterator'),
   ('class Row:\n def __iter__(self):return self\n def __next__(self):return 1\nprint(list(Row()))\n','__next__'),
   ('class Row:\n @staticmethod\n def __iter__():return iter([1])\nprint(list(Row()))\n','descriptor'))
  for source,fragment in cases:
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn(fragment,result.diagnostics[0].message)

 def test_generator_instance_cycle_does_not_silently_leak(self):
  source='class Row:\n def __init__(self):self.stream=self.values()\n def values(self):yield 1\nrow=Row()\nprint(next(row.stream))\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertRegex(result.diagnostics[0].message,'cycle|recursive|ownership')

if __name__=='__main__':unittest.main()
