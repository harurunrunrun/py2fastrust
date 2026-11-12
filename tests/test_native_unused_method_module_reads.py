"""Skip receiver module acquisition only when the actual call cannot use it."""
import ast
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_owned_object_places as places
from py2fastrust.native_call_context_effects import incoming_module
from py2fastrust.native_private_module_demands import module_unused
from tests import test_native_module_linking as modules


PURE='''class Box:
 def __init__(self):self.values=[2,3]
 def read(self,index):return self.values[index]
 def combine(self,left,right):return self.read(left)+self.read(right)
'''
PROJECTS={
 'pure':{'library.py':PURE,'main.py':'''from library import Box
def main():
 box=Box()
 print(box.combine(0,1),box.read(-1))
main()
'''},
 'foreign_global':{'library.py':'''bias=7
class Box:
 def __init__(self):self.values=[2,3]
 def read(self,index):return self.values[index]+bias
''','main.py':'''import library
bias=100
def argument():
 library.bias=13
 print('argument')
 return 0
def main():
 box=library.Box()
 print(box.read(argument()))
main()
'''},
 'evaluated_default':{'library.py':'''offset=1
def pick():
 print('default')
 return offset
class Box:
 def __init__(self):self.values=[2,3]
 def read(self,index=pick()):return self.values[index]
''','main.py':'''import library
library.offset=0
def main():
 box=library.Box()
 print(box.read(),box.read(0))
main()
'''},
 'error_source':{'library.py':PURE,'main.py':'''from library import Box
def main():
 box=Box()
 print('before')
 print(box.read(8))
main()
'''},
 'missing_field':{'library.py':'''class Box:
 def __init__(self,flag):
  if flag:self.values=[2,3]
 def read(self,index):return self.values[index]
''','main.py':'''from library import Box
def main():
 box=Box(False)
 print('before')
 print(box.read(0))
main()
'''},
 'mutable_receiver':{'library.py':PURE+''' def update(self,index):
  self.values[index]=self.read(index)+1
  return self.read(index)
''','main.py':'''from library import Box
def main():
 box=Box()
 print(box.update(0),box.combine(0,1))
main()
'''},
 'saved_class':{'library.py':PURE,'main.py':'''import library
Saved=library.Box
library.Box=0
def main():
 box=Saved()
 print(box.combine(0,1))
main()
'''},
}


class UnusedMethodModuleProofs(unittest.TestCase):
 def inspect(self,name):
  records=[];original=places.call_receiver
  def observe(emitter,node,callee):
   before=ast.dump(emitter.model.unit.tree,include_attributes=True)
   needed=incoming_module(emitter.model,callee) and not module_unused(emitter,node,callee)
   result=original(emitter,node,callee)
   self.assertEqual(before,ast.dump(emitter.model.unit.tree,include_attributes=True))
   if result is not None:
    records.append((callee.node.name,needed,result[2],result[0]))
   return result
  with tempfile.TemporaryDirectory(prefix='pytors-method-module-proof-') as directory:
   root=Path(directory)
   for filename,source in PROJECTS[name].items():(root/filename).write_text(source)
   main=root/'main.py'
   with patch.object(places,'call_receiver',observe):
    result=transpile(main.read_text(),TranspileOptions(filename=str(main),license='none'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertTrue(records)
  return records

 def test_unused_body_module_has_no_lookup_or_temporary_capture(self):
  records=self.inspect('pure')
  rows=[row for row in records if row[0] in {'read','combine'}]
  self.assertTrue(rows)
  for name,needed,module,setup in rows:
   self.assertFalse(needed)
   self.assertIsNone(module)
   self.assertNotIn('class_definition.module.clone()',setup)

 def test_real_module_and_default_consumers_keep_their_context(self):
  for name in ('foreign_global','evaluated_default'):
   with self.subTest(name=name):
    rows=[row for row in self.inspect(name) if row[0]=='read']
    self.assertTrue(rows)
    self.assertTrue(any(row[1] for row in rows))
    for method,needed,module,setup in rows:
     self.assertEqual(module is not None,needed)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class UnusedMethodModuleExecution(unittest.TestCase):
 def exercise(self,name):modules.NativeLinkedModuleTests.exercise(self,PROJECTS[name])


def runtime_case(name):
 def test(self):self.exercise(name)
 return test
for _name in PROJECTS:
 setattr(UnusedMethodModuleExecution,'test_'+_name,runtime_case(_name))
