"""Source membership preserves operand/callback order and truth conversion."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as helpers

CASES={
'basic':'''class Bag:
 def __init__(self,items):self.items=items
 def __contains__(self,x):return x in self.items
bag=Bag([2,5])
print(2 in bag,3 in bag,2 not in bag,3 not in bag)
''',
'operand_order':'''events=[]
class Bag:
 def __contains__(self,x):
  events.append(3)
  return x==7
def key():
 events.append(1)
 return 7
def owner():
 events.append(2)
 return Bag()
print(key() in owner(),events)
''',
'truthy_returns':'''class Bag:
 def __contains__(self,x):
  if x==0:return None
  if x==1:return 3
  return [4,5]
bag=Bag()
print(0 in bag,1 in bag,2 in bag,0 not in bag,2 not in bag)
''',
'chain':'''events=[]
class Bag:
 def __init__(self,stop):self.stop=stop
 def __contains__(self,x):
  events.append(self.stop)
  return self.stop>0
def later():
 events.append(99)
 return Bag(3)
print(7 in Bag(0) in later(),events)
print(7 in Bag(1) in later(),events)
''',
'mutation':'''class Bag:
 def __init__(self):self.items=[]
 def __contains__(self,x):
  self.items.append(x)
  return x%2
bag=Bag()
print(3 in bag,4 not in bag,bag.items)
''',
'return_not_implemented':'''class Bag:
 def __contains__(self,x):return NotImplemented
print('before')
print(1 in Bag())
''',
'error':'''class Bag:
 def __contains__(self,x):
  print('called',x)
  return 1//0
print(3 not in Bag())
''',
'direct_return':'''class Bag:
 def __contains__(self,x):return [x]
bag=Bag()
print(bag.__contains__(9),9 in bag)
''',
'builtin_and_source_union':'''class Bag:
 def __contains__(self,x):return x==5
def query(owner):return 5 in owner
print(query([2,5]),query(Bag()),query([1]))
''',
'query_equality_is_not_implicit':'''class Key:
 def __eq__(self,other):
  print('unexpected equality')
  return False
class Bag:
 def __contains__(self,x):return True
print(Key() in Bag())
''',
'callback_changes_binding':'''state=0
class Bag:
 def __contains__(self,x):
  global state
  state='changed'
  return True
if 2 in Bag():print(state)
''',
'associative_queries':'''class Table:
 def __init__(self):self.data={}
 def __contains__(self,key):return key in self.data
 def store(self,key,value):self.data[key]=value
 def fetch(self,key):return self.data[key]
table=Table()
q=int(input())
for _ in range(q):
 query=list(map(int,input().split()))
 if query[0]==0:table.store(query[1],query[2])
 else:
  key=query[1]
  print(table.fetch(key) if key in table else 0)
''',
}

class SourceContainsExecutionTests(unittest.TestCase):
 cases=CASES
 inputs={'associative_queries':'7\n0 2 8\n1 2\n1 9\n0 2 11\n0 9 3\n1 2\n1 9\n'}
 check=helpers.IteratorExecutionTests.check
 def test_membership(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

class SourceContainsGuardTests(unittest.TestCase):
 def test_descriptor_and_replaced_slot_are_explicit(self):
  for body in ('@staticmethod\ndef __contains__(x):return True',
               'def __contains__(self,x):return True\n__contains__=None',
               'def __contains__(self,x):return True\ndel __contains__'):
   source='class Bag:\n '+body.replace('\n','\n ')+'\nprint(1 in Bag())\n'
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success,source)
   self.assertTrue(any('__contains__'in d.message for d in result.diagnostics),result.diagnostics)
