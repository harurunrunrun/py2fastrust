"""Unpack adapters reflect the current producer schema rather than old bottom."""
import unittest
import test_native_annotations_assertions as support

CASES={'plain_pairs': ('def values():\n yield 1,2\n yield 3,5\nfor first,second in values():print(first+second)\n', ('',)), 'parent_filtered_pairs': ('def make(rows):\n def values():\n  for first in rows:\n   for second in rows:\n    if (first+second)%2:yield first,second\n return values\nfor first,second in make([1,2,4])():print(first,second)\n', ('',)), 'heterogeneous_tuple_fields': ('def values():\n yield 1,"first",None\n yield 2,"second",None\nfor number,text,missing in values():print(number,text,missing is None)\n', ('',)), 'shared_mutable_tuple_fields': ('def values(shared):\n yield shared,[7]\n yield shared,[9]\nshared=[3]\nfor first,second in values(shared):\n first.append(second[0])\n second.append(11)\n print(shared,first,second)\nprint(shared)\n', ('',)), 'real_empty_producer': ('def values():\n if False:yield 1,2\nfor first,second in values():print("unreachable")\nprint("done")\n', ('',)), 'tuple_length_error': ('def values():\n yield 1,2,3\nfor first,second in values():print("unreachable")\nprint("after")\n', ('',)), 'starred_tuple_target': ('def values():\n yield 1,2,3\n yield 4,5,6\nfor first,*rest in values():print(first,rest)\n', ('',)), 'actual_noniterable_union': ('def values():\n yield 3\n yield 1,2\nfor first,second in values():print("after",first,second)\n', ('',))}

BOUNDARIES={'shared_mutable_tuple_fields':CASES.pop('shared_mutable_tuple_fields')}

class GeneratorUnpackSchemaExecutionTests(unittest.TestCase):
 compare=support.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
for _name in CASES:setattr(GeneratorUnpackSchemaExecutionTests,'test_'+_name,_case(_name))

class GeneratorUnpackSchemaMetadataTests(unittest.TestCase):
 def test_reanalysis_clears_the_provisional_bottom_cursor(self):
  from unittest.mock import patch
  from py2fastrust import transpile,TranspileOptions
  from py2fastrust.native_classes import shape
  from py2fastrust.native_types import TupleType,EmptyType
  import py2fastrust.native_class_unpacking as unpacking
  original=unpacking.analyze;observed=[];old_records=[]
  def observe(model,plan,target,value,environment,**kwargs):
   kind=shape(value);key=(plan.index,id(target))
   result=original(model,plan,target,value,environment,**kwargs)
   stored=getattr(model,'unpack_sites',{}).get(key)
   if isinstance(kind,EmptyType)and stored is not None:old_records.append(stored.source_kind.record)
   if isinstance(kind,TupleType)and not result:
    self.assertIsNone(stored)
    observed.append(model.final)
   return result
  with patch.object(unpacking,'analyze',observe):
   result=transpile(CASES['plain_pairs'][0],TranspileOptions(filename='unpack_schema.py'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertTrue(observed)
  self.assertIn(True,observed)
  self.assertTrue(old_records)
  self.assertTrue(all(not record.emitted for record in old_records))
  for record in old_records:self.assertNotIn('struct ClassIteratorState_'+str(record.index)+'{',result.rust_source)
 def test_unpruned_pair_lowering_has_no_provisional_empty_cursor(self):
  from py2fastrust import transpile,TranspileOptions
  for integer in ('i64','i128','bigint'):
   result=transpile(CASES['plain_pairs'][0],TranspileOptions(integer=integer,optimize=False,filename='unpack_schema.py'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertNotRegex(result.rust_source,r'struct ClassIteratorState_\d+\{source:Option<NativeEmpty>')
 def test_preexisting_mutable_tuple_payload_boundary_remains_positioned(self):
  from py2fastrust import transpile,TranspileOptions
  for source,inputs in BOUNDARIES.values():
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename='unpack_schema.py'))
    self.assertFalse(result.success,result.diagnostics)
    self.assertTrue(any(d.code=='E006'and d.line==6 and 'first.append'in d.message for d in result.diagnostics),result.diagnostics)

if __name__=='__main__':unittest.main()
