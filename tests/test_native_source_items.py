"""Typed source item calls retain Python primary, mutation, and exception order."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'shared_rows_and_setter_return_ignored':'''class Grid:
 def __init__(self):self.rows=[[1,2],[3,4]]
 def __getitem__(self,i):return self.rows[i]
 def __setitem__(self,i,row):self.rows[i]=row;return 7
grid=Grid()
row=grid[0]
row[1]=9
grid[1]=[5,6]
print(grid[0],grid[1],row is grid[0])
''',
 'key_can_itself_use_builtin_slicing':'''class Box:
 def __getitem__(self,key):return sum(key)
print(Box()[[1,2,3][:2]])
''',
'mutable_key_captured_once':'''class Box:
 def __init__(self):self.values=[2,5]
 def __getitem__(self,key):
  result=self.values[key[0]]
  key[0]=1
  return result
 def __setitem__(self,key,value):self.values[key[0]]=value
key=[0]
box=Box()
box[key]+=4
print(box.values,key)
''',
'getter_signature_error_prevents_rhs':'''class Box:
 def __getitem__(self):return 4
 def __setitem__(self,key,value):print('set')
def rhs():print('rhs');return 2
box=Box()
box[0]+=rhs()
''',
'ordinary_tuple_key':'''class Grid:
 def __init__(self):self.rows=[[1,2],[3,4]]
 def __getitem__(self,key):
  r,c=key
  return self.rows[r][c]
 def __setitem__(self,key,value):
  r,c=key
  self.rows[r][c]=value
grid=Grid()
grid[0,1]=8
grid[1,0]+=4
print(grid[0,1],grid[1,0])
''',
 'canonical_slice_alias_and_shadow':'''saved_slice=slice
class Grid:
 def __init__(self):self.rows=[[1,2],[3,4]]
 def __getitem__(self,key):
  if isinstance(key,saved_slice):return self.rows[key]
  else:return self.rows[key]
class Choice:
 def __getitem__(self,key):
  if isinstance(key,slice):return 7
  else:return 99
slice=int
print(Grid()[0],Choice()[3])
''',
'int_key_excludes_slice_branch':'''class Grid:
 def __init__(self):self.rows=[[1,2],[3,4]]
 def __getitem__(self,key):
  if isinstance(key,slice):return self.rows[key]
  else:return self.rows[key]
 def __setitem__(self,key,value):
  if isinstance(key,slice):self.rows[key]=value
  else:self.rows[key]=value
grid=Grid()
grid[0]=[7,8]
print(grid[0])
''',
'assignment_and_augmented_primary_order':'''class Box:
 def __init__(self):self.values=[4]
 def __getitem__(self,key):
  print('get',key)
  return self.values[key]
 def __setitem__(self,key,value):
  print('set',key,value)
  self.values[key]=value
box=Box()
def owner():print('owner');return box
def key():print('key');return 0
def rhs():print('rhs');return 3
owner()[key()]=rhs()
owner()[key()]+=rhs()
print(box[0])
''',
'augmented_rebind_retains_original_owner':'''class Box:
 def __init__(self,value):self.values=[value]
 def __getitem__(self,key):return self.values[key]
 def __setitem__(self,key,value):self.values[key]=value
first=Box(3)
second=Box(20)
current=first
index=0
def change():
 global current,index
 current=second
 index=1
 return 4
current[index]+=change()
print(first[0],second[0],index)
''',
 'getter_rebinding_retains_captured_key':'''class Box:
 def __init__(self,value):self.values=[value]
 def __getitem__(self,key):
  global current,index
  current=second
  index='changed'
  return self.values[key]
 def __setitem__(self,key,value):self.values[key]=value
first=Box(3)
second=Box(20)
current=first
index=0
current[index]+=4
print(first.values,second.values,index)
''',
'setter_only_protocol':'''class Box:
 def __init__(self):self.value=0
 def __setitem__(self,key,value):self.value=key+value
box=Box()
box[2]=7
print(box.value)
''',
'callback_effects_prevent_loop_field_caches':'''class Box:
 def __init__(self):self.value=1
 def __getitem__(self,key):self.value+=key;return self.value
 def __setitem__(self,key,value):self.value=value+key
box=Box()
for i in range(3):
 print(box.value,box[1],box.value)
 box[1]=i
 print(box.value)
''',
'setter_signature_error':'''class Box:
 def __setitem__(self,key):print('body')
def rhs():print('rhs');return 2
box=Box()
box[0]=rhs()
''',
'augmented_list_keeps_alias':'''class Box:
 def __init__(self):self.rows=[[1]]
 def __getitem__(self,key):return self.rows[key]
 def __setitem__(self,key,value):
  print('set',value is self.rows[key])
  self.rows[key]=value
box=Box()
row=box[0]
box[0]+=[2,3]
box[0]*=2
print(row,box[0],row is box[0])
''',
'getter_error_prevents_rhs_and_setter':'''class Box:
 def __getitem__(self,key):
  print('get')
  return 1//0
 def __setitem__(self,key,value):print('set')
def rhs():print('rhs');return 2
box=Box()
box[0]+=rhs()
''',
'rhs_error_prevents_setter':'''class Box:
 def __getitem__(self,key):print('get');return 4
 def __setitem__(self,key,value):print('set')
def rhs():print('rhs');return 1//0
box=Box()
box[0]+=rhs()
''',
'operation_error_prevents_setter':'''class Box:
 def __getitem__(self,key):print('get');return 4
 def __setitem__(self,key,value):print('set')
def rhs():print('rhs');return 0
box=Box()
box[0]//=rhs()
''',
'setter_error_after_rhs':'''class Box:
 def __getitem__(self,key):print('get');return 4
 def __setitem__(self,key,value):print('set',value);self.bad=1//0
def rhs():print('rhs');return 2
box=Box()
box[0]+=rhs()
''',
'get_indexerror_payload':'''class Box:
 def __getitem__(self,key):
  print('get',key)
  raise IndexError('outside')
box=Box()
print(box[4])
''',
'explicit_indexerror_class':'''class Box:
 def __getitem__(self,key):
  if key<2:return key+1
  raise IndexError
box=Box()
print(box[0])
print(box[2])
''',
'indexerror_hierarchy_and_identity':'''error=IndexError('outside')
print(isinstance(error,IndexError),isinstance(error,LookupError),isinstance(error,Exception),isinstance(error,BaseException),isinstance(error,ValueError))
print(isinstance(ValueError(),Exception),isinstance(RuntimeError(),LookupError))
print(IndexError is IndexError,IndexError is LookupError,str(error),repr(error))
''',
'plain_source_slot_alias':'''class Box:
 def __init__(self):self.values=[5]
 def read(self,key):return self.values[key]
 def write(self,key,value):self.values[key]=value
 __getitem__=read
 __setitem__=write
box=Box()
box[0]+=7
print(box[0])
''',
'slot_alias_retains_original_binding':'''class Box:
 def __init__(self):self.values=[5]
 def read(self,key):return self.values[key]
 def replacement(self,key):return 90
 __getitem__=read
 read=replacement
box=Box()
print(box[0],Box.read(box,0),Box.__getitem__ is Box.read)
''',
'global_read_at_callback_time':'''value=3
class Box:
 def __getitem__(self,key):return value+key
box=Box()
print(box[1])
value=8
print(box[1])
''',
}

class SourceItemExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_source_item_protocols(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(SourceItemExecutionTests,_name,None)

class SourceItemGuards(unittest.TestCase):
 def test_alias_does_not_admit_an_unimplemented_protocol(self):
  from py2fastrust.native_class_operators import SUPPORTED_SLOTS
  for slot in ('__len__','__reversed__'):
   if slot in SUPPORTED_SLOTS:continue
   source='class Box:\n def operation(self):return 0\n '+slot+'=operation\nprint(bool(Box()))\n'
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn(slot,result.diagnostics[0].message)

 def test_unsupported_item_protocols_name_the_missing_construct(self):
  cases=(
   ('class Box:\n def __getitem__(self,key):return key\nprint(Box()[:2])\n','slice-object'),
   ('class Box:\n def __getitem__(self,key):return key\nprint(Box()[1,:2])\n','slice-object'),
   ('class Box:\n def __setitem__(self,key,value):return None\nbox=Box()\nbox[:2]=[3]\n','slice-object'),
   ('class Box:\n @staticmethod\n def __getitem__(key):return key\nprint(Box()[0])\n','descriptor'),
   ('class Box:\n def __getitem__(self,key):return key\nbox=Box()\nbox[0]=3\n','__setitem__'),
   ('class Box:\n def read(self,key):return key\n read=3\n __getitem__=read\nprint(Box()[0])\n','__getitem__'),
   ('class Box:\n def __getitem__(self,key):return key\n del __getitem__\nprint(Box()[0])\n','deleted'),
   ('class Box:\n def __getitem__(self,key):return key\n __getitem__=3\nprint(Box()[0])\n','slot'),
   ('class Box:pass\nprint(slice(1,2))\n','slice object'),
  )
  for source,fragment in cases:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)
