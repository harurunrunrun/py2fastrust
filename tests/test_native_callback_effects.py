"""Semantic callback effects invalidate field caches for every source operation."""
import ast
import shutil
from types import SimpleNamespace
import unittest
from py2fastrust.native_callback_effects import register,may_call
from tests import test_native_module_linking as linked_helpers


class CallbackExtensionTests(unittest.TestCase):
    def test_noncall_operation_uses_its_registered_source_effect(self):
        read=ast.parse('values[index]').body[0].value
        unrelated=ast.parse('other[index]').body[0].value
        plan=SimpleNamespace(index=2)
        model=SimpleNamespace()
        register(model,lambda active,node:active.index==2 and node is read)
        self.assertTrue(may_call(model,plan,read))
        self.assertFalse(may_call(model,plan,unrelated))
        self.assertFalse(may_call(model,SimpleNamespace(index=3),read))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class CallbackCacheExecutionTests(unittest.TestCase):
    exercise=linked_helpers.NativeLinkedModuleTests.exercise

    def test_min_scalar(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.value=0
 def key(self,value):
  self.value+=value
  return value
 def run(self):
  for unused in range(2):
   print(self.value)
   min([7,9],key=self.key)
   print(self.value)
Box().run()
"""})

    def test_min_list(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.values=[]
 def key(self,value):
  self.values=[value]
  return value
 def run(self):
  for unused in range(2):
   print(len(self.values))
   min([7,16],key=self.key)
   print(self.values[0])
Box().run()
"""})

    def test_max_scalar(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.value=0
 def key(self,value):
  self.value+=value
  return value
 def run(self):
  for unused in range(2):
   print(self.value)
   max([7,9],key=self.key)
   print(self.value)
Box().run()
"""})

    def test_max_list(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.values=[]
 def key(self,value):
  self.values=[value]
  return value
 def run(self):
  for unused in range(2):
   print(len(self.values))
   max([7,16],key=self.key)
   print(self.values[0])
Box().run()
"""})

    def test_sorted_scalar(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.value=0
 def key(self,value):
  self.value+=value
  return value
 def run(self):
  for unused in range(2):
   print(self.value)
   sorted([7,9],key=self.key)
   print(self.value)
Box().run()
"""})

    def test_sorted_list(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.values=[]
 def key(self,value):
  self.values=[value]
  return value
 def run(self):
  for unused in range(2):
   print(len(self.values))
   sorted([7,16],key=self.key)
   print(self.values[0])
Box().run()
"""})
