"""Actual helper effects settle before rejecting a provisional scalar target."""
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_annotations_assertions as support

CASES={
 'fully_known_operands_after_helper':('''class Grid:
 def __init__(self):
  self.rows=[0]
  self.prepare()
  self.rows[0][0]=9
 def prepare(self):self.rows[0]=[3]
grid=Grid()
print(grid.rows)
''',('',)),
 'helper_chain_and_shared_alias':('''def fill(rows):rows[0]=[3,5]
class Grid:
 def __init__(self):
  self.rows=[0]
  self.prepare()
  self.rows[0][1]=11
 def prepare(self):fill(self.rows)
grid=Grid()
alias=grid.rows[0]
alias[0]=7
print(grid.rows,alias)
''',('',)),
 'nested_dimensions_after_real_tuple_producer':('''class Grid:
 def __init__(self,n):
  self.source=[[]for _ in range(n)]
  self.prepare(n)
  self.rows=[[]for _ in range(n)]
  for i in range(n):
   self.rows[i]=[0]*len(self.source[i])
   for j,(a,b)in enumerate(self.source[i]):
    self.rows[i][j]=[-1]*(a+1)
    self.rows[i][j][a]=b
 def prepare(self,n):
  for i in range(1,n):self.source[i].append((i,i+7))
for n in [0,1,4]:print(Grid(n).rows)
''',('',)),
 'receiver_and_rhs_effects_remain_ordered':('''events=[]
def index():events.append('index');return 0
def value():events.append('value');return 13
class Grid:
 def __init__(self):
  self.rows=[0]
  self.prepare()
  self.rows[0][index()]=value()
 def prepare(self):self.rows[0]=[3]
grid=Grid()
print(events,grid.rows)
''',('',)),
 'finite_scalar_branch_keeps_runtime_error_before_later_effects':('''events=[]
def index():print('index');return 0
def value():print('value');return 13
class Grid:
 def __init__(self,flag):
  self.rows=[0]
  self.prepare(flag)
  self.rows[0][index()]=value()
  print('after store')
 def prepare(self,flag):
  if flag:self.rows[0]=[3]
grid=Grid(int(input()))
print(grid.rows)
''',('0\n','1\n')),
 'ancestor_dependent_helper_keeps_actual_runtime_order':('''class Grid:
 def __init__(self):
  self.rows=[0]
  self.probe()
  self.rows[0]=[3]
  print('after replacement')
 def probe(self):self.rows[0][0]=7
grid=Grid()
''',('',)),
}

class PendingIndexedStoreExecutionTests(unittest.TestCase):
 compare=support.AnnotationAndAssertionExecutionTests.compare

for _name,_arguments in CASES.items():
 def _case(self,arguments=_arguments):self.compare(*arguments)
 setattr(PendingIndexedStoreExecutionTests,'test_'+_name,_case)

class PendingIndexedStoreBoundaries(unittest.TestCase):
 def test_complete_scalar_target_stays_positioned(self):
  cases=(
   'class Grid:\n def __init__(self):\n  self.rows=[0]\n  self.prepare()\n  self.rows[0][0]=3\n def prepare(self):pass\ngrid=Grid()\n',
  )
  for source in cases:
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,license='none',filename='pending_store.py'))
    self.assertFalse(result.success)
    self.assertTrue(any(item.code=='E006'and item.line>0 for item in result.diagnostics),result.diagnostics)

if __name__=='__main__':unittest.main()
