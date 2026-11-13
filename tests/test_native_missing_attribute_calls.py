"""Known failed lookups stop before call arguments, including specialized frames."""
import ast
import unittest

import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames


BOX='''class Box:
 def __init__(self,value):self.value=value
 def val(self,amount=2):return self.value+amount
'''

CASES={
'original_optional_specialization':BOX+'''def run(obj):return obj.val(4)
print(run(Box(5)))
print(run(None))
''',
'callee_receiver_once_before_arguments':'''def owner():print('owner');return None
def argument():print('unexpected');return 3
owner().missing(argument())
''',
'lookup_precedes_all_positional_and_keyword_effects':'''def argument(tag):print(tag);return 3
value=None
value.missing(argument('positional'),key=argument('keyword'))
''',
'starred_arguments_are_unreachable':'''def arguments():print('unexpected');return [1,2]
value=None
value.missing(*arguments())
''',
'keyword_expansion_is_unreachable':'''def keywords():print('unexpected');return {'key':3}
value=None
value.missing(**keywords())
''',
'unimplemented_expansions_are_unreachable':'''value=None
value.missing(*(x for x in [1,2]),**{str(x):x for x in [1,2]})
''',
'saved_missing_attribute_stops_before_later_statement':'''value=None
saved=value.missing
print('unexpected')
saved(3)
''',
'receiver_exception_precedes_attribute_and_arguments':'''def owner():print('owner');return 1//0
def argument():print('unexpected');return 3
owner().missing(argument())
''',
'real_none_callee_evaluates_arguments':'''def argument():print('argument');return 3
value=None
value(argument())
''',
'real_none_instance_field_evaluates_arguments':'''class Item:
 def __init__(self):self.val=None
def argument():print('argument');return 3
Item().val(argument())
''',
'private_lookup_spelling_in_specialization':'''class Box:
 def __secret(self):return 9
 def run(self,other):return other.__secret()
value=Box()
print(value.run(value))
print(value.run(None))
''',
'builtin_existing_members_keep_their_adapters':'''def read(value):return value.bit_length()
print(read(31),read(True))
print(' a b '.strip().split())
''',
'argument_exception_precedes_noncallable_error':'''def argument():print('argument');return 1//0
value=None
value(argument())
''',
'finite_callable_and_none_join':'''def valid(value):return value+7
def argument():print('argument');return 3
for choice in [True,False]:
 selected=valid if choice else None
 print(selected(argument()))
''',
'rebound_callee_is_captured_before_argument':'''def valid(value):return value+7
selected=valid
def argument():
 global selected
 print('argument')
 selected=None
 return 3
print(selected(argument()))
print(selected(argument()))
''',
}

for _label,_literal in (('none','None'),('int','3'),('bool','True'),('float','1.5'),('str',"'text'"),('bytes',"b'bytes'"),('list','[1,2]'),('tuple','(1,2)')):
 CASES['specialized_'+_label]=BOX+'''def argument():print('argument');return 4
def run(obj):return obj.val(argument())
print(run(Box(5)))
print(run('''+_literal+'''))
'''


class MissingAttributeExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_missing_attribute_call_order(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(MissingAttributeExecutionTests,_name,None)


class MissingAttributeProofTests(unittest.TestCase):
 def test_known_missing_receiver_and_keyword_spread_select_without_ast_edits(self):
  for source in ('value=None\nvalue.missing(3)\n','value=1\nvalue.missing\n','value=None\nvalue.missing(**{})\n'):
   unit=build_program(source,'case.py').main;original=ast.dump(unit.tree,include_attributes=True)
   self.assertTrue(select_frames(unit).required)
   self.assertEqual(ast.dump(unit.tree,include_attributes=True),original)

 def test_real_none_and_existing_members_do_not_become_failed_lookup_proofs(self):
  source='value=None\nvalue(**{})\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertIn('expansion',result.diagnostics[0].message)
  source='class Source:\n def __getattr__(self,name):return 1\nprint(Source().missing())\n'
  result=transpile(source,TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertIn('__getattr__',result.diagnostics[0].message)


if __name__=='__main__':unittest.main()
