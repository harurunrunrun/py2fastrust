"""Owned typed-vector updates retain Python target and operand order."""
import shutil
import unittest
import ast

from py2fastrust import transpile,TranspileOptions

import test_native_union_ordering as helpers


CASES={
 'reported':('def index():\n print("index")\n return 0\nvalues=[2]\nvalues[index()]**=int(input())\nprint(values)\n',('-3\n','0\n','5\n')),
 'float_operators':('''values=[1.5,2.0]
values[0]+=2
values[1]*=3
values[1]//=2
values[0]%=2
values[1]/=2
print(values)
''',('',)),
 'string_operators':('''values=['one']
values[0]+='two'
values[0]*=2
print(values)
''',('',)),
 'ordered_callbacks':('''def index():
 print('index',end='|')
 return -1
def right():
 print('right',end='|')
 return 3
values=[1.5,2.0]
values[index()]+=right()
print(values)
''',('',)),
 'read_error_precedes_rhs':('''def right():
 print('right')
 return 0
values=[1.5]
print('before')
values[int(input())]/=right()
print(values)
''',('1\n','-2\n','0\n')),
 'rhs_exception':('''values=[1.5]
print('before')
values[0]/=float(input())
print(values)
''',('0.0\n','2.0\n')),
 'shared_alias':('''values=[1.5]
alias=values
values[0]+=2
print(alias,values is alias)
''',('',)),
 'range_indexed_updates':('''values=[1.5,2.5,3.5]
for i in range(len(values)):
 values[i]+=i
print(values)
''',('',)),
 'negative_index':('''values=[1.5,2.5]
values[int(input())]*=2
print(values)
''',('-1\n','-2\n','-3\n','2\n')),
 'rhs_pop_renormalizes_negative_index':('''values=[1.5,2.5,3.5]
values[-1]+=values.pop()
print(values)
''',('',)),
 'rhs_pop_leaves_assignment_error':('''values=[1.5]
print('before')
values[-1]+=values.pop()
print(values)
''',('',)),
 'rhs_mutates_argument':('''def right(values):
 values.append(99.0)
 return 1.0
values=[1.5,2.5]
values[-1]+=right(values)
print(values)
''',('',)),
 'rhs_replaces_global_binding':('''values=[1.5]
alias=values
def right():
 global values
 values=[99.0]
 return 2.0
values[0]+=right()
print(values,alias)
''',('',)),
 'index_replaces_global_binding':('''values=[1.5]
alias=values
def index():
 global values
 values=[99.0]
 return 0
values[index()]+=2.0
print(values,alias)
''',('',)),
 'shared_tuple_payload':('''values=[(1.5,2),(2.5,3)]
alias=values
alias[0]=(4.5,5)
print(values,values is alias)
''',('',)),
 'tuple_float_formatting':('''values=(1.0,-0.0,float('nan'),float('inf'),None)
print(values,str(values),1.0,None)
print(*values)
''',('',)),
 'mutable_iteration':('''values=[1.5,2.5]
for value in values:
 print(value,end='|')
 if value<2:values.append(3.5)
 if value>3:values.pop()
print(values)
''',('',)),
}


class TypedVectorLayoutProofs(unittest.TestCase):
 def inspect(self,source):
  from py2fastrust.frontend import build_program
  from py2fastrust.native_constraints import analyze
  unit=build_program(source,'layout.py').main
  before=ast.dump(unit.tree,include_attributes=True)
  analysis=analyze(unit)
  self.assertEqual(before,ast.dump(unit.tree,include_attributes=True))
  return unit,analysis.scope()

 def test_unaliased_float_vector_keeps_direct_storage(self):
  from py2fastrust.native_types import ListType
  unit,facts=self.inspect(CASES['float_operators'][0])
  site=unit.ordinal(unit.tree.body[0].value)
  self.assertEqual(facts.allocations[site],ListType('float'))
  self.assertNotIn(site,facts.storage)

 def test_shared_storage_does_not_require_float_element_comparison(self):
  from py2fastrust.native_types import ListType,SharedListType,shared_payload,shared_storage_payload
  unit,facts=self.inspect(CASES['shared_alias'][0])
  site=unit.ordinal(unit.tree.body[0].value)
  self.assertEqual(facts.allocations[site],ListType('float'))
  self.assertEqual(facts.storage[site],SharedListType('float'))
  self.assertTrue(shared_storage_payload('float'))
  self.assertFalse(shared_payload('float'))

 def test_nan_element_comparisons_remain_positioned_missing_protocols(self):
  sources=["x=float('nan')\nvalues=[x]\nalias=values\nprint(values==alias)\n",
           "x=float('nan')\nvalues=[x]\nalias=values\nprint(alias.count(x))\n",
           "x=float('nan')\nvalues=(x,)\nprint(values==values)\n"]
  for source in sources:
   for mode in ('i64','i128','bigint'):
    with self.subTest(mode=mode,source=source):
     result=transpile(source,TranspileOptions(integer=mode,filename='nan_identity.py',license='none'))
     self.assertFalse(result.success)
     self.assertEqual(result.diagnostics[0].code,'E006')
     self.assertIn('identity',result.diagnostics[0].message)
     self.assertEqual(result.diagnostics[0].filename,'nan_identity.py')


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class TypedVectorAugAssignExecution(unittest.TestCase):
 setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
 tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
 compile=helpers.NativeUnionOrderingTests.compile
 exercise=helpers.NativeUnionOrderingTests.exercise


def runtime_case(name):
 def test(self):
  source,inputs=CASES[name]
  self.exercise(source,inputs)
 return test
for _name in CASES:
 setattr(TypedVectorAugAssignExecution,'test_'+_name,runtime_case(_name))
