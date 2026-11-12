"""Original source str/repr slots preserve publication, callbacks and errors."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'alias_identity_and_containers':'''class Row:
 def __init__(self,x):self.x=x
 def __str__(self):return f'Row({self.x})'
 __repr__=__str__
row=Row(3)
print(str(row),repr(row),[row],(row,),f'{row}')
print(Row.__repr__ is Row.__str__)
''',
'separate_str_repr_and_fallback':'''class Row:
 def __str__(self):return 'str'
 def __repr__(self):return 'repr'
class Fallback:
 def __repr__(self):return 'fallback'
row=Row()
print(row,str(row),repr(row),[row],str(Fallback()),repr(Fallback()))
''',
'nested_print_has_no_output_loan':'''class Row:
 def __str__(self):
  print('inside')
  return 'row'
row=Row()
print('before',row,'after',sep='|')
''',
'print_argument_and_conversion_interleaving':'''class First:
 def __str__(self):
  print('str first')
  return 'A'
class Second:
 def __str__(self):
  print('str second')
  return 'B'
def first():
 print('arg first')
 return First()
def second():
 print('arg second')
 return Second()
print(first(),second(),sep='|',end='!')
''',
'print_second_conversion_error_keeps_first_output':'''class First:
 def __str__(self):
  print('str first')
  return 'A'
class Second:
 def __str__(self):
  print('str second')
  return str(1//0)
print(First(),Second(),sep='|',end='!')
''',
'recursive_list_repr_keeps_original_owner':'''class Item:
 def __repr__(self):return repr(items)
items=[Item()]
print(items)
print(items)
''',
'recursive_dynamic_tuple_repr':'''class Item:
 def __repr__(self):return repr(items)
items=tuple([Item()])
print(items)
''',
'list_repr_callbacks_can_append':'''class Item:
 def __init__(self,value):self.value=value
 def __repr__(self):
  if len(items)<2:items.append(Item(2))
  print('item',self.value)
  return f'Item({self.value})'
items=[Item(1)]
print(items)
''',
'list_repr_callbacks_can_clear':'''class Item:
 def __init__(self,value):self.value=value
 def __repr__(self):
  items.clear()
  return str(self.value)
items=[Item(1),Item(2)]
print(items)
''',
'nested_optional_container_releases_outer_loan':'''class Item:
 def __repr__(self):
  groups.clear()
  return 'I'
groups=[None,[Item()]]
print(groups)
''',
'namedtuple_nonrecursive_custom_repr':'''from typing import NamedTuple
class Box(NamedTuple):
 item:int
class Item:
 def __repr__(self):return 'I'
print(Box(Item()))
''',
'alias_captures_old_binding_before_assignment':'''class Row:
 def original(self):return 'old'
 def replacement(self):return 'new'
 __repr__=original
 original=replacement
row=Row()
print(repr(row),Row.original(row),Row.__repr__ is Row.original)
''',
'alias_keeps_function_after_source_name_delete':'''class Row:
 def text(self):return 'kept'
 __repr__=text
 del text
print(repr(Row()))
''',
'alias_defaults_run_once':'''events=[]
def mark():
 events.append(1)
 return '!'
class Row:
 def text(self,suffix=mark()):return 'row'+suffix
 __str__=text
 __repr__=text
print(events)
row=Row()
print(str(row),repr(row),events)
''',
'field_conversion_order':'''width=1
class Row:
 def __str__(self):
  global width
  width=4
  return 'x'
 def __repr__(self):return 'R'
row=Row()
print(f'{row!s:>{width}}')
print(f'{row!r}',f'{row!a}',format(row),format(row,''))
print('{} {!r} {!s}'.format(row,row,row))
''',
'format_nonempty_never_calls_str':'''class Row:
 def __str__(self):
  print('str called')
  return 'row'
row=Row()
print(format(row,'x'))
''',
'str_return_type_error':'''class Row:
 def __str__(self):
  print('called')
  return 7
print(Row())
''',
'repr_return_type_error':'''class Row:
 def __repr__(self):return None
print(repr(Row()))
''',
'generator_return_type_error_does_not_enter_body':'''class Row:
 def __str__(self):
  print('body')
  yield 1
print(Row())
''',
'list_cursor_return_type_error':'''class Row:
 def __str__(self):return iter([1])
print(str(Row()))
''',
'class_return_type_error':'''class Row:
 def __str__(self):return Row
print(str(Row()))
''',
'singleton_return_type_error':'''class Row:
 def __str__(self):return NotImplemented
print(str(Row()))
''',
'reverse_list_return_type_error':'''class Row:
 def __str__(self):return reversed([1])
print(str(Row()))
''',
'deque_return_type_error':'''from collections import deque
class Row:
 def __str__(self):return deque()
print(str(Row()))
''',
'defaultdict_return_type_error':'''from collections import defaultdict
class Row:
 def __repr__(self):return defaultdict(int)
print(repr(Row()))
''',
'alias_error_uses_slot_name':'''class Row:
 def text(self):return 7
 __repr__=text
print(repr(Row()))
''',
'display_body_error_trace':'''class Row:
 def __str__(self):return str(1//0)
print('before')
print(Row())
''',
'list_display_error_trace':'''class Row:
 def __repr__(self):return str(1//0)
print([Row()])
''',
'unicode_ascii_and_repr':'''class Row:
 def __str__(self):return 'é😀'
 def __repr__(self):return 'é😀'
row=Row()
print(str(row),repr(row),ascii(row),f'{row!a}')
''',
'captured_builtin_and_nested_tuple':'''class Row:
 def __repr__(self):return 'R'
show=repr
row=Row()
print(show(row),((row,),[row]),tuple([row]))
''',
'finite_return_union':'''class Row:
 def __init__(self,valid):self.valid=valid
 def __str__(self):
  if self.valid:return 'yes'
  return 3
print(str(Row(True)))
print(str(Row(False)))
''',
'empty_custom_container_never_calls_repr':'''class Row:
 def __repr__(self):
  print('called')
  return 'R'
items=[]
if int(input()):items.append(Row())
print(items)
''',
}

class SourceDisplayExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 inputs={'empty_custom_container_never_calls_repr':'0\n'}
 def test_source_display_protocols(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(SourceDisplayExecutionTests,_name,None)

class SourceDisplayGuards(unittest.TestCase):
 def test_alias_counterexamples_never_guess_old_bindings(self):
  cases=(('class Row:\n def text(self):return "old"\n __repr__=text\n def text(self):return "new"\nprint(repr(Row()))\n','defined more than once'),
   ('class Row:\n def text(self):return "old"\n text=7\n __repr__=text\nprint(repr(Row()))\n','plain source function'),
   ('class Row:\n def text(self):return "old"\n text=lambda self:"new"\n __repr__=text\nprint(repr(Row()))\n','lambda'),
   ('class Row:\n def text(self):return "row"\n if int(input()):__repr__=text\nprint(repr(Row()))\n','conditional class-body publication'))
  for source,fragment in cases:
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn(fragment,result.diagnostics[0].message)

 def test_unimplemented_container_callbacks_are_explicit(self):
  for expression in ('{1:Row()}','{1:Row()}.values()','deque([Row()])'):
   source='from collections import deque\nclass Row:\n def __repr__(self):return "R"\nprint('+expression+')\n'
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn('callback-safe display for this container',result.diagnostics[0].message)

 def test_reassigned_instance_method_never_uses_stale_function(self):
  prefix='class Row:\n def text(self):return "old"\n def replacement(self):return "new"\n __repr__=text\n text=replacement\nrow=Row()\n'
  for suffix in ('print(row.text())\n','saved=row.text\nprint(saved())\n'):
   result=transpile(prefix+suffix,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn('reassigned during class publication',result.diagnostics[0].message)

 def test_fixed_tuple_recursive_repr_identity_is_explicit(self):
  for initial in ('(Item(),)','(Item() if int(input()) else None,)'):
   source='class Item:\n def __repr__(self):return repr(items)\nitems='+initial+'\nprint(items)\n'
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn('fixed-tuple display reaches recursive',result.diagnostics[0].message)

 def test_deleted_display_slot_fallback_is_not_silently_ignored(self):
  source='class Row:\n def __repr__(self):return "R"\n del __repr__\nprint(repr(Row()))\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertIn('deleted source display slot fallback',result.diagnostics[0].message)

 def test_deleted_source_function_read_is_not_reconstructed(self):
  source='class Row:\n def text(self):return "kept"\n __repr__=text\n del text\nprint(Row.text)\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertIn('deleted class function attribute lookup',result.diagnostics[0].message)

 def test_namedtuple_repr_cycles_never_use_untracked_recursion(self):
  source='from typing import NamedTuple\nclass Box(NamedTuple):\n item:int\nclass Item:\n def __repr__(self):return repr(box)\nbox=Box(Item())\nprint(box)\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertIn('NamedTuple display reaches recursive',result.diagnostics[0].message)
  source='from collections import namedtuple\nBox=namedtuple("Box","item")\nclass Item:\n def __repr__(self):return repr(box)\nbox=Box(Item())\nprint(box)\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertEqual(result.diagnostics[0].code,'E006')

if __name__=='__main__':unittest.main()
