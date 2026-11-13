"""Uninhabited attribute receivers never reach lookup or argument effects."""
import unittest
import test_native_annotations_assertions as support

CASES={'original_mutable_tuple_fields': ('def values(shared):\n yield shared,[7]\n yield shared,[9]\nshared=[3]\nfor first,second in values(shared):\n first.append(second[0])\n second.append(11)\n print(shared,first,second)\nprint(shared)\n', ('',)), 'empty_generator_method_body': ('def argument():\n print("argument")\n return 7\ndef values():\n if False:yield [],[]\nfor first,second in values():first.append(argument())\nprint("done")\n', ('',)), 'receiver_failure_precedes_argument': ('def receiver():\n print("receiver")\n return [][0]\ndef argument():\n print("argument")\n return 7\nreceiver().append(argument())\nprint("after")\n', ('',)), 'attribute_failure_prefix': ('def receiver():\n print("receiver")\n return [][0]\nreceiver().missing\nprint("after")\n', ('',)), 'chained_attribute_failure': ('def receiver():\n print("receiver")\n return [][0]\nreceiver().first.second\nprint("after")\n', ('',)), 'property_failure_precedes_method_arguments': ('class Box:\n @property\n def values(self):\n  print("getter")\n  return [][0]\ndef argument():\n print("argument")\n return 7\nBox().values.append(argument())\nprint("after")\n', ('',)), 'live_none_attribute_error': ('def receiver():\n print("receiver")\n return None\ndef argument():\n print("argument")\n return 7\nreceiver().missing(argument())\nprint("after")\n', ('',)), 'live_integer_attribute_error': ('def argument():\n print("argument")\n return 7\nvalue=3\nvalue.append(argument())\nprint("after")\n', ('',)), 'live_list_missing_attribute_error': ('def argument():\n print("argument")\n return 7\nvalues=[]\nvalues.missing(argument())\nprint("after")\n', ('',)), 'abrupt_or_live_receiver': ('def receiver(enabled):\n print("receiver")\n if enabled:return [][0]\n return []\ndef argument():\n print("argument")\n return 7\nreceiver(int(input())).append(argument())\nprint("after")\n', ('0\n', '1\n')), 'expanded_receiver_failure': ('def receiver():\n print("receiver")\n return [][0]\ndef arguments():\n print("arguments")\n return [7]\nreceiver().extend(*arguments())\nprint("after")\n', ('',))}

class AbruptAttributeOperandExecutionTests(unittest.TestCase):
 compare=support.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
for _name in CASES:setattr(AbruptAttributeOperandExecutionTests,'test_'+_name,_case(_name))

class AbruptAttributeOperandMetadataTests(unittest.TestCase):
 def test_selector_uses_only_actual_reached_empty_receiver_facts(self):
  from py2fastrust.frontend import build_program
  from py2fastrust.native_constraints import analyze
  from py2fastrust.native_frame_selection import select_frames
  from py2fastrust.native_abrupt_values import requires_attribute_frames
  source=CASES['receiver_failure_precedes_argument'][0]
  unit=build_program(source,'abrupt_attribute.py').main
  self.assertTrue(requires_attribute_frames(unit,analyze(unit)))
  selection=select_frames(unit)
  self.assertTrue(selection.required)
  self.assertIn('uninhabited attribute receiver',selection.reasons)
  for source in ('def unused():return [][0].missing\nprint(7)\n',
                 'value=None\nvalue.missing\n',
                 'def unused(value):return value.missing\nprint(7)\n'):
   unit=build_program(source,'abrupt_attribute.py').main
   self.assertFalse(requires_attribute_frames(unit,analyze(unit)))
 def test_receiver_prefix_proof_is_removed_when_the_producer_becomes_live(self):
  from unittest.mock import patch
  from py2fastrust import transpile,TranspileOptions
  from py2fastrust.native_classes import shape
  from py2fastrust.native_types import EmptyType,ListType
  import py2fastrust.native_abrupt_values as abrupt
  original=abrupt.attribute_operand;observed=[]
  def observe(model,plan,node,receiver):
   result=original(model,plan,node,receiver)
   kind=shape(receiver);key=plan.index,id(node)
   if isinstance(kind,(EmptyType,ListType)):
    observed.append((model.final,kind,key in model.abrupt_attribute_operands))
    self.assertEqual(key in model.abrupt_attribute_operands,isinstance(kind,EmptyType))
   return result
  with patch.object(abrupt,'attribute_operand',observe):
   result=transpile(CASES['original_mutable_tuple_fields'][0],TranspileOptions(filename='abrupt_attribute.py'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertTrue(any(isinstance(kind,EmptyType)for final,kind,marked in observed))
  self.assertTrue(any(final and isinstance(kind,ListType)and not marked for final,kind,marked in observed))

if __name__=='__main__':unittest.main()
