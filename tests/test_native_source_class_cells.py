"""Implicit class cells follow official lexical owners and module generations."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'lexical_constructor_after_name_rebind':'''class Row:
 def __init__(self,value):self.value=value
 def copy(self):return __class__(self.value+1)
 def original(self):return __class__
saved=Row
Row=7
row=saved(3)
print(row.copy().value,row.original() is saved)
''',
'lexical_class_after_name_delete':'''class Row:
 def __init__(self,value):self.value=value
 def copy(self):return __class__(self.value+2)
saved=Row
row=Row(5)
del Row
print(row.copy().value,saved(7).copy().value)
''',
'static_and_class_methods_keep_lexical_owner':'''class Row:
 @staticmethod
 def original():return __class__
 @classmethod
 def pair(cls):return cls is __class__
saved=Row
static=Row.original
bound=Row.pair
del Row
print(static() is saved,bound(),saved().original() is saved)
''',
'local_and_global_spelling_are_distinct':'''__class__=7
class Row:
 def original(self):return __class__
 def local(self,__class__):return __class__
 def global_value(self):
  global __class__
  return __class__
row=Row()
print(row.original() is Row,row.local(4),row.global_value())
''',
'nested_lexical_function':'''class Row:
 def original(self):
  def read():return __class__
  return read
saved=Row
Row=8
row=saved()
read=row.original()
print(read() is saved)
''',
'nested_class_owners':'''class Outer:
 class Inner:
  def original(self):return __class__
 def original(self):return __class__
outer=Outer
inner=Outer.Inner
del Outer
print(outer().original() is outer,inner().original() is inner)
''',
'captured_bound_and_unbound_methods':'''class Row:
 def original(self):return __class__
row=Row()
bound=row.original
unbound=Row.original
saved=Row
del Row
print(bound() is saved,unbound(row) is saved)
''',
'class_cell_is_empty_during_body':'''class Row:
 def original():return __class__
 value=original()
''',
'global_class_spelling_without_implicit_cell':'''__class__=4
def read():return __class__
print(read())
''',
}


CASES['comprehension_keeps_lexical_owner']='''class Row:
 def values(self):return [__class__ for _ in range(2)]
row=Row()
print(row.values()[0] is Row,row.values()[1] is Row)
'''

class SourceClassCellExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_implicit_class_cell_protocol(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(SourceClassCellExecutionTests,_name,None)

class SourceClassCellGuards(unittest.TestCase):
 def test_nonlocal_cell_writers_remain_explicit(self):
  for operation in ('__class__=3','del __class__'):
   source='class Row:\n def change(self):\n  nonlocal __class__\n  '+operation+'\n def original(self):return __class__\nprint(Row().original())\n'
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn('class-cell',result.diagnostics[0].message)

 def test_inheritance_and_super_keep_existing_diagnostics(self):
  for source in ('class Base:\n def original(self):return __class__\nclass Child(Base):pass\nprint(Child().original())\n',
                 'class Row:\n def original(self):return super()\nprint(Row().original())\n'):
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertTrue(result.diagnostics[0].message)


class SourceClassCellModuleTests(unittest.TestCase):
 def exercise(self,files):
  from test_native_module_linking import NativeLinkedModuleTests
  NativeLinkedModuleTests.exercise(self,files)

 def test_captured_module_survives_public_name_replacement(self):
  self.exercise({'main.py':"from library import Row as Original\nimport library\nlibrary.Row=7\nrow=Original(4)\nprint(row.copy().value,row.original() is Original)\n",
   'library.py':"class Row:\n def __init__(self,value):self.value=value\n def copy(self):return __class__(self.value+2)\n def original(self):return __class__\n"})

 def test_same_named_source_classes_keep_distinct_module_cells(self):
  library="class Row:\n def __init__(self,value):self.value=value\n def copy(self):return __class__(self.value+1)\n def original(self):return __class__\n"
  self.exercise({'main.py':"from left import Row as Left\nfrom right import Row as Right\nleft=Left(2)\nright=Right(5)\nprint(left.copy().value,right.copy().value,left.original() is Left,right.original() is Right,left.original() is right.original())\n",
   'left.py':library,'right.py':library})

if __name__=='__main__':unittest.main()
