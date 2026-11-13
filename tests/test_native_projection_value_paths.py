"""Scalar value dependencies keep their allocation paths and lower bounds."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import (
 Allocation,BOTTOM,Computed,IteratorValue,MISSING,Projection,SemanticGraph,ShapeConstraint,
 Solver,TupleValue,UNKNOWN,Value,Variable,analyze,value,
)
from py2fastrust.native_types import EMPTY,ListType,SharedListType,TupleType,union_type
import test_native_class_iterators as iterator_tests


PROGRAMS={
 'nested_list_alias_and_mutation':'''n=int(input())
rows=[[1,2]]
alias=rows
for i in range(n):
 row=alias[0]
 previous=row[0]
 row[0]=previous+row[1]
print(rows,alias is rows)
''',
 'tuple_and_iterator_paths':'''n=int(input())
rows=[(7,[1,2])]
for i in range(n):
 for tag,row in iter(rows):
  previous=next(iter(row))
  row[0]=previous+tag
print(rows)
''',
 'mapping_row_paths':'''n=int(input())
rows={3:[1,2]}
for i in range(n):
 row=rows[3]
 row[0]=row[0]+row[1]
print(rows[3])
''',
 'indirected_numeric_table':'''n=int(input())
table=[[0,1],[1,0]]
for step in range(n):
 row=[step%2]
 row.append(table[row[0]][0])
 table.append(row)
print(table)
''',
 'forward_row_values':'''n=int(input())
rows=[[0,1]]
for i in range(n):
 row=[0]
 for j in range(1,3):
  row.append(rows[row[-1]][0])
 rows.append(row)
print(rows)
''',
 'computed_text_index_in_mixed_row':'''n=int(input())
words=['ab','cd']
rows=[[0]]
for i in range(n):
 row=rows[0]
 row.append((words[i%2]+'tail')[0])
print(rows)
''',
 'computed_text_tuple_iterator_fields':'''n=int(input())
rows=[(2,['ab']),(5,['cd'])]
result=[]
for i in range(n):
 for tag,words in iter(rows):
  result.append((tag,(words[0]+'tail')[0]))
print(rows,result)
''',
 'nested_parameters_and_order':'''n=int(input())
events=[]
def mark(x):
 events.append(x)
 return x
def update(rows):
 row=rows[mark(0)]
 row[mark(0)]=row[mark(0)]+mark(2)
rows=[[1,3]]
for i in range(n):update(rows)
print(rows,events)
''',
 'zero_trip_target_unbound':'''n=int(input())
rows=[[5,6]]
for i in range(n):
 row=rows[0]
 row[0]=row[0]+1
print('after',n)
print(row[0])
''',
 'deleted_local_precedes_later_argument':'''n=int(input())
rows=[[1,2]]
for i in range(n):
 row=rows[0]
 row[0]=row[0]+1
del row
def later():
 print('later')
 return 9
print('before')
print(row[0],later())
''',
}


class ProjectionValuePathModelTests(unittest.TestCase):
 def solver(self):return Solver(SemanticGraph(build_program('pass\n','projection_model.py').main))

 def test_scalar_fixed_point_through_nested_allocations(self):
  solver=self.solver();outer=solver.allocation(1,'list',(None,()));row=solver.allocation(2,'list',(None,()))
  solver.insert(value(outer),'element',value(row))
  selected=Projection(solver.field(outer,'element'),'value',0)
  solver.insert(value(row),'element',value('int').join(value(selected)))
  self.assertEqual(solver.kind(value(selected)),'int')
  self.assertEqual(solver.kind(value(outer)),ListType(ListType('int')))
  self.assertEqual(solver.provenance(value(selected)),value('int'))
  self.assertEqual(solver.provenance(solver.field(outer,'element')),value(row))

 def test_original_tuple_index_and_iterator_item_paths(self):
  solver=self.solver();row=solver.allocation(3,'list',(None,()));slot=Variable((None,4),'element')
  nested=TupleValue((value('str'),value(IteratorValue(value(row)))))
  solver.constrain(slot,value(nested))
  iterator=Projection(value(slot),'value',1)
  item=Projection(value(iterator),'iteration')
  scalar=Projection(value(item),'value',0)
  solver.insert(value(row),'element',value('int').join(value(scalar)))
  self.assertEqual(solver.kind(value(scalar)),'int')
  self.assertEqual(solver.provenance(value(item)),value(row))

 def test_computed_projection_cycle_has_only_its_real_lower_bounds(self):
  for anchor,expected in ((BOTTOM,EMPTY),(value('int'),'int'),(UNKNOWN,None)):
   with self.subTest(anchor=anchor):
    solver=self.solver();outer=solver.allocation(1,'list',(None,()));row=solver.allocation(2,'list',(None,()))
    solver.insert(value(outer),'element',value(row))
    selected=Projection(solver.field(outer,'element'),'value',0)
    operation=Computed('binary:Add',(value(selected),value('int')))
    solver.insert(value(row),'element',anchor.join(value(operation)))
    self.assertEqual(solver.kind(value(selected)),expected)
    self.assertEqual(solver.kind(value(row)),None if expected is None else ListType(expected))

 def test_unknown_and_actual_recursive_heap_are_not_scalar_anchors(self):
  solver=self.solver();row=solver.allocation(1,'list',(None,()));outer=solver.allocation(2,'list',(None,()))
  solver.insert(value(outer),'element',value(row));selected=Projection(solver.field(outer,'element'),'value',0)
  solver.insert(value(row),'element',UNKNOWN.join(value('int')))
  self.assertIsNone(solver.kind(value(selected)))
  cycle=solver.allocation(3,'list',(None,()));solver.insert(value(cycle),'element',value(cycle).join(value('int')))
  self.assertIsNone(solver.kind(value(cycle)))
  self.assertIsNone(solver.kind(value(Projection(value(cycle),'iteration'))))
  self.assertIsNone(solver.kind(UNKNOWN))
  self.assertEqual(solver.kind(BOTTOM),EMPTY)

 def test_projection_keeps_absence_separate_from_none(self):
  solver=self.solver();row=solver.allocation(1,'list',(None,()))
  solver.insert(value(row),'element',value('int'))
  receiver=value(row).join(MISSING);selected=solver.field_values(receiver,'iteration')
  self.assertEqual(solver.kind(value(Projection(receiver,'iteration'))),'int')
  self.assertTrue(selected.unbound)
  self.assertTrue(solver.provenance(selected).unbound)
  self.assertEqual(solver.kind(value('none')),'none')
  self.assertNotEqual(solver.kind(MISSING),'none')

 def test_shape_constraints_remain_type_bounds_without_fake_alias_origins(self):
  solver=self.solver();row=solver.allocation(1,'list',(None,()));slot=Variable((None,2),'element')
  solver.insert(value(row),'element',value('int'))
  shape=ShapeConstraint(ListType('str'))
  solver.constrain(slot,value(row).join(value(shape)))
  item=value(Projection(value(slot),'iteration'))
  self.assertEqual(solver.kind(item),union_type('int','str'))
  self.assertEqual(solver.kind(value(slot)),ListType(union_type('int','str')))
  self.assertEqual(solver.provenance(value(slot)),value(row))
  self.assertEqual(solver.typing_provenance(value(slot)),value(row).join(value(ListType('str'))))
  tuple_slot=Variable((None,3),'element')
  solver.constrain(tuple_slot,value(TupleValue((value('int'),value('bool')))).join(value(ShapeConstraint(TupleType(('str','bool'))))))
  self.assertEqual(solver.kind(value(Projection(value(tuple_slot),'value',0))),union_type('int','str'))
  solver.constrain(slot,UNKNOWN)
  self.assertIsNone(solver.kind(item))

 def test_opaque_computed_projection_keeps_its_type_lower_bound(self):
  solver=self.solver();row=solver.allocation(1,'list',(None,()))
  computed=Computed('binary:Add',(value('str'),value('str')))
  selected=Projection(value(computed),'value',0)
  solver.insert(value(row),'element',value('int').join(value(selected)))
  self.assertEqual(solver.kind(value(selected)),'str')
  self.assertEqual(solver.kind(value(Projection(value(row),'iteration'))),union_type('int','str'))
  self.assertEqual(solver.kind(value(row)),ListType(union_type('int','str')))
  self.assertEqual(solver.typing_provenance(value(selected)),value(selected))
  mixed=Projection(value(computed).join(value(TupleValue((value('bool'),)))),'value',0)
  solver.insert(value(row),'element',value(mixed))
  self.assertEqual(solver.kind(value(Projection(value(row),'iteration'))),union_type('int','str','bool'))
  unknown=Projection(value(computed).join(UNKNOWN),'value',0)
  self.assertIsNone(solver.kind(value(Projection(value(TupleValue((value(unknown),))),'value',0))))
  invalid=Projection(value(Computed('binary:Add',(value('int'),value('int')))),'value',0)
  solver.insert(value(row),'element',value(invalid))
  self.assertIsNone(solver.kind(value(Projection(value(row),'iteration'))))

 def test_opaque_tuple_and_iterator_paths_keep_string_projection(self):
  solver=self.solver();row=solver.allocation(1,'list',(None,()));slot=Variable((None,2),'element')
  computed=Computed('binary:Add',(value('str'),value('str')))
  indexed=Projection(value(computed),'value',0)
  solver.constrain(slot,value(TupleValue((value('int'),value(IteratorValue(value(indexed)))))))
  iterator=Projection(value(slot),'value',1)
  scalar=Projection(value(iterator),'iteration')
  solver.insert(value(row),'element',value('int').join(value(scalar)))
  self.assertEqual(solver.kind(value(Projection(value(row),'iteration'))),union_type('int','str'))

 def test_logical_storage_header_and_real_allocation_provenance(self):
  source='rows=[[1,2]]\nfor i in range(int(input())):\n row=rows[0]\n row[0]=row[0]+1\nprint(rows)\n'
  unit=build_program(source,'projection_facts.py').main;facts=analyze(unit).scope();loop=unit.tree.body[1]
  self.assertEqual(facts.allocations[unit.ordinal(unit.tree.body[0].value)],ListType(ListType('int')))
  self.assertEqual(facts.headers[unit.ordinal(loop)]['row'].kind,ListType('int'))
  self.assertTrue(facts.headers[unit.ordinal(loop)]['row'].maybe_unbound)
  projection=loop.body[0].value;site=unit.ordinal(projection)
  self.assertEqual(facts.expressions[site],ListType('int'))
  self.assertEqual(facts.storage.get(site,facts.expressions[site]),SharedListType('int'))
  self.assertEqual(facts.header_storage[unit.ordinal(loop)]['row'],SharedListType('int'))
  self.assertTrue(any(isinstance(part,Variable)for part in facts.values[site].alternatives))

 def test_unknown_and_recursive_source_allocations_keep_positioned_boundaries(self):
  for source in ('rows=[]\nrows.append(rows)\nprint(rows)\n','rows=[eval(input())]\nprint(rows[0])\n'):
   unit=build_program(source,'projection_boundary.py').main
   self.assertIsNone(analyze(unit).scope().allocations[unit.ordinal(unit.tree.body[0].value)])
   for mode in ('i64','i128','bigint'):
    with self.subTest(mode=mode,source=source),patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
     result=transpile(source,TranspileOptions(integer=mode,filename='projection_boundary.py',license='none'))
     self.assertFalse(result.success);self.assertIsNone(result.rust_source)
     self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].line,result.diagnostics[0].filename),('E006',1,'projection_boundary.py'))
     self.assertIn('finite',result.diagnostics[0].message)

 def test_indirect_table_backedges_resolve_row_value_types(self):
  unit=build_program(PROGRAMS['indirected_numeric_table'],'indirect_table.py').main
  facts=analyze(unit).scope();loop=unit.tree.body[2]
  self.assertEqual(facts.allocations[unit.ordinal(unit.tree.body[1].value)],ListType(ListType('int')))
  self.assertEqual(facts.headers[unit.ordinal(loop)]['row'].kind,ListType('int'))
  self.assertTrue(facts.headers[unit.ordinal(loop)]['row'].maybe_unbound)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ProjectionValuePathExecutionTests(unittest.TestCase):
 def check(self,name):
  source=PROGRAMS[name];filename='projection_case.py'
  controls={}
  for data in ('0\n','3\n'):
   cp=subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,filename],input=data,capture_output=True,text=True,timeout=10)
   controls[data]=(cp,json.loads(cp.stderr)if cp.returncode else None)
  with tempfile.TemporaryDirectory(prefix='pytors-projection-value-')as directory:
   for mode in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
     result=transpile(source,TranspileOptions(integer=mode,filename=filename,license='none'))
    self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native')
    self.assertLess(len(result.rust_source.encode()),512*1024)
    rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.opt'if optimized else'.debug')
     built=subprocess.run(['rustc','--edition=2021','--crate-name','projection_case',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     for data,(cp,failure)in controls.items():
      actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
      with self.subTest(name=name,mode=mode,optimized=optimized,data=data):
       self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
       if failure:
        self.assertEqual(actual.stderr.splitlines()[-1],failure['message'])
        self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in failure['frames']])
       else:self.assertEqual(actual.stderr,'')
 def test_nested_mutable_and_tuple_iterator_paths(self):
  for name in ('nested_list_alias_and_mutation','tuple_and_iterator_paths','mapping_row_paths','indirected_numeric_table','forward_row_values','computed_text_index_in_mixed_row','computed_text_tuple_iterator_fields'):
   with self.subTest(name=name):self.check(name)
 def test_parameter_effect_order_and_absence(self):
  for name in ('nested_parameters_and_order','zero_trip_target_unbound','deleted_local_precedes_later_argument'):
   with self.subTest(name=name):self.check(name)
