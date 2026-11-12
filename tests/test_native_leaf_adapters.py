"""Inline hints cover one bounded leaf-adapter layer, preserving real calls."""
import ast
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_call_context_effects as contexts
from tests import test_native_module_linking as modules

SOURCE="""def operation(left,right):return left[0]+right[0],left[1]*right[1]
class Box:
 def __init__(self,op):
  self.values=[(3,2),(5,4)]
  self.operation=op
 def update(self,index,value):self.values[index]=self.operation(value,self.values[index])
 def read(self,index):return self.values[index]
def main():
 box=Box(operation)
 box.update(-1,(7,3))
 print(box.read(0),box.read(1))
main()
"""
PROJECTS={
 'one_leaf':{'main.py':SOURCE},
 'argument_side_effect':{'main.py':SOURCE.replace(' def update(self,index,value):',' def argument(self,value):\n  print("argument")\n  self.values[1]=(20,5)\n  return value\n def update(self,index,value):').replace('self.operation(value,self.values[index])','self.operation(self.argument(value),self.values[index])')},
 'bad_index':{'main.py':SOURCE.replace('box.update(-1,','box.update(5,')},
 'callback_error':{'main.py':SOURCE.replace('left[0]+right[0]','right[0]//left[1]').replace('box.update(-1,(7,3))','box.update(-1,(7,0))')},
 'mutable_callback':{'main.py':SOURCE.replace('def operation(left,right):return left[0]+right[0],left[1]*right[1]','state=[0]\ndef operation(left,right):\n state[0]+=1\n return left[0]+right[0],left[1]*right[1]').replace('print(box.read(0),box.read(1))','print(box.read(0),box.read(1),state)')},
 'foreign_definition':{'library.py':SOURCE[:SOURCE.index('def main():')],'main.py':'from library import Box, operation\n'+SOURCE[SOURCE.index('def main():'):]},
}


class LeafAdapterProofs(unittest.TestCase):
 def inspect(self,source):
  rows=[];original=contexts.inline_entry
  def inspect(model,plan):
   before=ast.dump(model.unit.tree,include_attributes=True)
   result=original(model,plan)
   self.assertEqual(before,ast.dump(model.unit.tree,include_attributes=True))
   rows.append((getattr(plan.node,'name','<module>'),result,contexts.small_entry(model,plan)))
   return result
  with patch.object(contexts,'inline_entry',inspect):
   result=transpile(source,TranspileOptions(license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return rows

 def test_one_source_adapter_to_closed_leaves_is_exposed(self):
  rows=self.inspect(SOURCE)
  self.assertIn(('update',True,False),rows)
  self.assertIn(('operation',True,True),rows)

 def test_source_loops_are_not_forced_inline(self):
  source=SOURCE.replace(' def update(self,index,value):self.values[index]=self.operation(value,self.values[index])',' def update(self,index,value):\n  for _ in range(3):self.values[index]=self.operation(value,self.values[index])')
  self.assertIn(('update',False,False),self.inspect(source))

 def test_only_one_transitive_layer_is_exposed(self):
  source=SOURCE.replace(' def read(self,index):',' def again(self,index,value):return self.update(index,value)\n def read(self,index):').replace('box.update(-1,','box.again(-1,')
  self.assertIn(('again',False,False),self.inspect(source))

 def test_large_leaf_body_stays_bounded(self):
  operation='def operation(left,right):\n'+''.join(' value=left[0]+right[0]\n'for _ in range(24))+' return value,left[1]*right[1]\n'
  source=operation+SOURCE[SOURCE.index('class Box:'):]
  self.assertIn(('update',False,False),self.inspect(source))

 def test_real_module_consumers_keep_ordinary_context(self):
  rows=self.inspect(PROJECTS['mutable_callback']['main.py'])
  self.assertIn(('operation',False,False),rows)
  self.assertIn(('update',False,False),rows)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class LeafAdapterExecution(unittest.TestCase):
 def exercise(self,name):modules.NativeLinkedModuleTests.exercise(self,PROJECTS[name])


def runtime_case(name):
 def test(self):self.exercise(name)
 return test
for _name in PROJECTS:
 setattr(LeafAdapterExecution,'test_'+_name,runtime_case(_name))
