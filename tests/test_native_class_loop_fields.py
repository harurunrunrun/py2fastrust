"""Concrete field-read reuse retains Python effects and exception order."""
import shutil
import unittest

import test_native_lambda_callbacks as helpers


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeClassLoopFieldTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_zero_trip_and_first_read_keep_missing_attribute_errors(self):
        self.exercise('''class Box:
 def read(self,n):
  index=0
  result=0
  while index<n:
   print("before",index)
   result+=self.value
   index+=1
  return result
print(Box().read(int(input())))
''',("0\n","1\n"))

    def test_mutating_list_contents_keeps_the_same_field_handle(self):
        self.exercise('''class Bag:
 def __init__(self):self.values=[2,5,7]
 def consume(self):
  total=0
  while self.values:
   total+=self.values.pop()
  return total
bag=Bag()
alias=bag.values
print(bag.consume(),alias,bag.values is alias)
''')

    def test_attribute_assignment_through_alias_is_observed(self):
        self.exercise('''class Box:
 def __init__(self):self.value=2
 def total(self,n):
  other=self
  index=0
  total=0
  while index<n:
   other.value+=index
   total+=self.value
   index+=1
  return total
print(Box().total(int(input())))
''',("0\n","5\n"))

    def test_user_calls_in_body_and_condition_keep_field_replacements(self):
        self.exercise('''class Box:
 def __init__(self):self.value=4
 def step(self):
  self.value-=1
  return self.value>0
 def run(self):
  total=0
  while self.step():total+=self.value
  return total
 def second(self):
  total=0
  for index in range(4):
   self.step()
   total+=self.value
  return total
box=Box()
print(box.run(),box.value,box.second(),box.value)
''')

    def test_receiver_name_rebinding_and_for_targets_keep_object_identity(self):
        self.exercise('''class Box:
 def __init__(self,value):self.value=value
first=Box(2)
second=Box(9)
current=first
total=0
for index in range(4):
 total+=current.value
 current=second
for current in [first,second,first]:total+=current.value
print(total,first.value,second.value)
''')

    def test_nested_loops_and_private_field_reads(self):
        self.exercise('''class Grid:
 def __init__(self):
  self.__rows=[[2,3],[5]]
  self.__offset=7
 def total(self):
  total=0
  for row in self.__rows:
   for value in row:total+=value+self.__offset
  return total
print(Grid().total())
''')

    def test_comprehension_shadowing_remains_separate_from_outer_receiver(self):
        self.exercise('''class Box:
 def __init__(self,value):self.value=value
 def total(self,items):
  total=0
  for index in range(3):
   rows=[self.value for self in items]
   total+=rows[0]+self.value
  return total
items=[Box(1),Box(5)]
print(Box(9).total(items))
''')


if __name__=="__main__":unittest.main()
