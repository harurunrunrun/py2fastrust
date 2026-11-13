"""Retained range slices use structural counts rather than allocation sizes."""
import ast
import os
import subprocess
import unittest

import test_native_class_iterators as iterator_tests
import test_native_iterator_reductions as helpers
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import RangeValue,analyze
from py2fastrust.native_frame_selection import select_frames


CASES={
'exhaustive_small_slices':'''for begin in [-5,0,4]:
 for end in [-4,0,7]:
  for stride in [-3,-1,1,4]:
   source=range(begin,end,stride)
   for lower in [None,-20,-2,0,2,20]:
    for upper in [None,-20,-1,0,3,20]:
     for step in [-7,-2,-1,1,2,7]:
      print(list(source[lower:upper:step]))
''',
'nested_slices_and_original_cursor':'''source=range(-20,30,3)
cursor=iter(source)
print(next(cursor),next(cursor))
back=source[::-1]
print(list(back),list(back[1:-1:2]),list(source[2:8][::-2]))
print(bool(source),bool(source[3:3]),next(cursor))
''',
'canonical_alias_and_returned_range':'''make=range
def source(begin,end,step):return make(begin,end,step)
value=source(1,20,3)
alias=value
print(list(alias[1:5:2]),list(value),list(source(20,0,-3)[::-2]))
''',
'receiver_capture_and_bounds_effects':'''value=range(12)
def owner():print('owner');return value
def bound(tag,result):
 global value
 print(tag)
 value=range(2)
 return result
print(list(owner()[bound('lower',2):bound('upper',9):bound('step',2)]))
print(list(value))
''',
'zero_step_precedes_bad_lower_after_expression_evaluation':'''def bound(tag,result):print(tag);return result
value=range(12)
print(list(value[bound('lower',1.5):bound('upper','bad'):bound('step',0)]))
''',
'bad_step_precedes_lower_conversion':'''def bound(tag,result):print(tag);return result
value=range(12)
print(list(value[bound('lower',1.5):bound('upper',2):bound('step','bad')]))
''',
'bad_lower_precedes_bad_upper':'''def bound(tag,result):print(tag);return result
value=range(12)
print(list(value[bound('lower',1.5):bound('upper','bad'):bound('step',1)]))
''',
'boolean_none_bounds':'''value=range(-4,9)
print(list(value[False:True]),list(value[None:None:True]),list(value[True:False:-1]))
''',
'huge_range_count_small_result':'''value=range(-(1<<62),1<<62)
print(list(value[:3]),list(value[-3:]),list(value[1:8:3]))
print(list(value[0:0]),bool(value),bool(value[0:0]))
''',
'huge_negative_source_and_slice_steps':'''value=range(1<<62,-(1<<62),-(1<<61))
print(list(value[:]),list(value[::-1]),list(value[1:3:1]))
print(list(range(5)[::1<<61]),list(range(5)[::-(1<<61)]))
''',
'finite_range_and_list_receiver':'''def choose(flag):
 if flag:return range(1,8)
 return [8,6,4,2]
print(list(choose(True)[::-2]),list(choose(False)[1:-1]))
''',
'shadowed_range_remains_an_ordinary_callable':'''def range(n):return [n,n+1,n+2]
print(range(4)[::-1])
''',
'container_held_ranges':'''values=[range(2,14,3),range(20,3,-4)]
table={1:range(3,12,2)}
pair=(range(1,9,2),range(10,0,-3))
print(list(values[0][::-1]),list(values[1][1:]),list(table[1][::2]))
print(list(pair[0][1:]),list(pair[1][::-1]))
''',
'function_argument_alias':'''def apply(value,lower,upper,step):
 alias=value
 return alias[lower:upper:step]
value=range(2,20,3)
print(list(apply(value,1,None,2)),list(apply(value,None,None,-1)))
''',
}


class RangeSliceExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_range_slice_semantics(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(RangeSliceExecutionTests,_name,None)


class RangeSliceProofTests(unittest.TestCase):
 def test_selector_preserves_original_ast_and_ordinary_range_for(self):
  for mode in ('i64','i128','bigint'):
   source='make=range\na=make(2,20,3)\nb=a[1:-1:2]\nprint(list(b))\n'
   unit=build_program(source,'case.py').main
   original=ast.dump(unit.tree,include_attributes=True)
   self.assertTrue(select_frames(unit,integer=mode).required)
   self.assertEqual(ast.dump(unit.tree,include_attributes=True),original)
   ordinary=build_program('answer=0\nfor value in range(12):answer+=value\nprint(answer)\n','case.py').main
   self.assertFalse(select_frames(ordinary,integer=mode).required)

 def test_canonical_range_metadata_distinguishes_its_cursor(self):
  source='make=range\na=make(5)\nb=a[::-1]\nc=iter(a)\n'
  unit=build_program(source,'case.py').main;facts=analyze(unit)
  nodes={ast.unparse(node):node for node in ast.walk(unit.tree)if isinstance(node,(ast.Call,ast.Subscript))}
  values={text:next(scope.values[unit.ordinal(node)]for scope in facts.scopes.values()if unit.ordinal(node)in scope.values)for text,node in nodes.items()}
  for text in ('make(5)','a[::-1]'):
   self.assertTrue(all(isinstance(item,RangeValue)for item in values[text].alternatives))
  self.assertFalse(any(isinstance(item,RangeValue)for item in values['iter(a)'].alternatives))

 def test_unreached_helpers_are_not_emitted(self):
  result=transpile('print(sum(range(10)))\n',TranspileOptions(license='none'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertNotIn('class_range_slice',result.rust_source)

 def test_custom_index_and_iterator_slicing_boundaries_remain_explicit(self):
  for source,fragment in (
   ('class Index:\n def __index__(self):return 1\na=range(5)\nprint(a[Index():])\n','__index__'),
   ('a=iter(range(5))\nprint(a[::-1])\n','slice')):
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)


class RangeSliceWidthTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.harness=helpers.NativeIteratorReductionTests();cls.harness.setUpClass()

 @classmethod
 def tearDownClass(cls):cls.harness.tearDownClass()

 def test_exact_full_width_counts_and_checked_structural_fields(self):
  for mode in ('i64','i128','bigint'):
   bits=64 if mode=='i64'else 128
   minimum,maximum=-(1<<(bits-1)),(1<<(bits-1))-1
   def normalize(value):
    if value is None or mode=='bigint':return value
    return (value-minimum)%(1<<bits)+minimum
   cases=(
    ('wide_prefix',(minimum,maximum,1),(None,3,None)),
    ('wide_suffix',(minimum,maximum,1),(-3,None,None)),
    ('wide_negative_index',(minimum,maximum,1),(minimum,maximum,None)),
    ('wide_stride',(minimum,maximum,1),(None,None,maximum)),
    ('wide_reverse_endpoint',(minimum,maximum,1),(None,None,-1)),
    ('wide_descending_endpoint',(maximum,minimum,-1),(None,None,-1)),
    ('unaligned_full_slice',(minimum,maximum,maximum),(None,None,None)),
    ('unaligned_prefix',(minimum,maximum,maximum),(None,2,None)),
    ('empty_endpoint',(minimum,minimum,maximum),(None,None,-1)),
    ('multiplied_step',(0,4,maximum),(None,None,2)),
    ('minimum_step_prefix',(maximum,minimum,minimum),(None,1,None)),
    ('minimum_step_reverse',(maximum,minimum,minimum),(None,None,-1)),
    ('normalized_literal_step',(0,5,1),(None,None,maximum+1)),
    ('arbitrary_precision_step',(0,10,1),(-(1<<300),1<<300,1<<200)),
   )
   for name,fields,bounds in cases:
    expression=':'.join(''if bound is None else str(bound)for bound in bounds)
    source='original=range('+','.join(map(str,fields))+')\nresult=original['+expression+']\nprint(bool(result),list(result[:3]))\n'
    failure=None
    try:
     result=range(*map(normalize,fields))[slice(*map(normalize,bounds))]
     if mode!='bigint'and any(not minimum<=field<=maximum for field in (result.start,result.stop,result.step)):
      raise OverflowError('sliced range structural fields do not fit the selected integer mode')
     # The prefix is itself a source range slice. Check its structural fields
     # too; the helper never silently truncates an unrepresentable endpoint.
     prefix=result[:3]
     if mode!='bigint'and any(not minimum<=field<=maximum for field in (prefix.start,prefix.stop,prefix.step)):
      raise OverflowError('sliced range structural fields do not fit the selected integer mode')
     expected=str(bool(result))+' '+str(list(prefix))+'\n'
    except (OverflowError,ValueError)as error:
     expected='';failure=type(error).__name__+': '+str(error)
    for optimized in (False,True):
     with self.subTest(mode=mode,name=name,optimized=optimized):
      compiled=self.harness.compile(source,mode,release=optimized)
      actual=subprocess.run([str(compiled[1])],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
      self.assertEqual(actual.stdout,expected,actual.stderr)
      if failure:
       self.assertNotEqual(actual.returncode,0)
       self.assertEqual(actual.stderr.splitlines()[-1],failure)
      else:self.assertEqual((actual.returncode,actual.stderr),(0,''))


if __name__=='__main__':unittest.main()
