"""Mutable byte buffers retain their real class through native class objects."""
import unittest
import test_native_class_iterators as helpers

CASES={
'class_identity_and_builtin_rebinding':'''value=bytearray(b'72')
kind=type(value)
original=bytearray
print(kind,kind is bytearray,kind==bytearray,type(kind)is type)
print(isinstance(value,kind),kind(3),int(value))
bytearray=int
print(kind is original,kind is bytearray,type(value)is kind,kind(b'a'))
''',
'class_values_in_fields_and_callbacks':'''class Factory:
 build=type(bytearray())
factory=Factory()
print(factory.build(b'23'),Factory.build(2))
def actual(value):return type(value)
print(list(map(actual,[bytearray(b'1'),bytearray(b'2')])))
print(list(map(type,[bytearray(b'3'),bytearray(b'4')])))
''',
'finite_class_results':'''for value in [bytearray(b'8'),b'9',[1,2]]:
 kind=type(value)
 print(kind,isinstance(value,kind),kind is bytearray,kind())
''',
}

class BytearrayTypeObjects(unittest.TestCase):
 cases=CASES
 check=helpers.IteratorExecutionTests.check
 def test_actual_bytearray_class_across_native_protocols(self):
  for name in self.cases:
   with self.subTest(name=name):self.check(name)
