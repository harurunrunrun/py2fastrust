"""Owned Vec iteration retains Python list mutation and evaluation order."""
import ast
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_owned_local_lists as places
from tests import test_native_classes as _classes


SUM='''class Accumulator:
 def __init__(self,bias):self.bias=bias
 def calculate(self,n):
  values=list(range(n))
  total=self.bias
  for value in values:total+=value
  return total
a=Accumulator(7)
print(a.calculate(9))
'''
ENUMERATE='''class Weighted:
 def __init__(self,start):self.start=start
 def calculate(self):
  values=list(map(int,input().split()))
  result=0
  for index,value in enumerate(values,self.start):result+=index*value
  return result
print(Weighted(3).calculate())
'''
APPEND='''class TreeWalk:
 def __init__(self,limit):self.limit=limit
 def calculate(self):
  values=[1,2]
  total=0
  for value in values:
   total+=value
   if value<self.limit:values.append(value+2)
  return total,len(values)
print(TreeWalk(4).calculate())
'''
MIXED='''class Formatter:
 def __init__(self,prefix):self.prefix=prefix
 def display(self):
  values=[3,'start']
  for value in values:print(self.prefix,value)
  values[0]='changed'
  values[1]=4
  for value in values:print(self.prefix,value)
Formatter('item').display()
'''
REBIND='''class Snapshots:
 def __init__(self,first):self.first=first
 def calculate(self):
  values=[self.first,2,3]
  total=0
  for value in values:
   if value==self.first:values=[8,9]
   total+=value
  return total,values[0]
print(Snapshots(1).calculate())
'''
SHARED_ROWS='''class MatrixCounter:
 def __init__(self,count):self.count=count
 def calculate(self):
  row=[0]
  values=[row]*self.count
  for value in values:value[0]+=1
  return values[0][0],values[0] is values[-1]
print(MatrixCounter(3).calculate())
'''


class OwnedListIterationProofTests(unittest.TestCase):
    def inspect(self,source,mode='i64'):
        original=places.prepare;found=[]
        def observe(emitter):
            before=ast.dump(emitter.model.unit.tree,include_attributes=True)
            result=original(emitter)
            self.assertEqual(ast.dump(emitter.model.unit.tree,include_attributes=True),before)
            found.extend(result.values())
            return result
        with patch.object(places,'prepare',observe):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'native')
        return result,found

    def test_integer_loops_and_enumerate_keep_owned_vectors_in_all_modes(self):
        for source in (SUM,ENUMERATE,APPEND):
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source.splitlines()[0],mode=mode):
                    result,found=self.inspect(source,mode)
                    self.assertTrue(found)
                    self.assertIn('Option<Vec<NativeInt>>',result.rust_source)
                    self.assertNotIn('.borrow().get(',result.rust_source)

    def test_mixed_iteration_keeps_a_finite_element_enum(self):
        result,found=self.inspect(MIXED)
        self.assertTrue(found)
        self.assertRegex(result.rust_source,r'Option<Vec<NativeUnion[0-9a-f]+>>')
        self.assertNotIn('.borrow().get(',result.rust_source)

    def test_rebound_iterator_preserves_the_existing_shared_abi(self):
        result,found=self.inspect(REBIND)
        self.assertFalse(found)
        with patch.object(places,'loop_source',return_value=None):
            baseline=transpile(REBIND,TranspileOptions(license='none'))
        self.assertEqual(result.rust_source,baseline.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class OwnedListIterationExecutionTests(unittest.TestCase):
    compile=_classes.NativeClassTests.compile
    compare=_classes.NativeClassTests.compare

    def test_append_is_seen_by_the_next_pull(self):self.compare(APPEND)

    def test_enumerate_uses_the_requested_start(self):self.compare(ENUMERATE,data='2 3 4\n')

    def test_heterogeneous_values_keep_their_python_types(self):self.compare(MIXED)

    def test_rebinding_keeps_the_original_iterator(self):self.compare(REBIND)

    def test_repeated_rows_keep_their_shared_identity(self):self.compare(SHARED_ROWS)

    def test_nested_iteration_does_not_retain_a_rust_loan(self):
        self.compare('''class ProductSum:
 def __init__(self,offset):self.offset=offset
 def calculate(self):
  values=[1,2,3]
  total=self.offset
  for a in values:
   for b in values:total+=a*b
  return total
print(ProductSum(4).calculate())
''')

    def test_missing_source_is_checked_before_start(self):
        self.compare('''class Optional:
 def __init__(self,flag):self.flag=flag
 def calculate(self):
  if self.flag:values=[2,3]
  for index,value in enumerate(values,self.start()):print(index,value)
 def start(self):
  print('must not run')
  return 3
Optional(False).calculate()
''')
