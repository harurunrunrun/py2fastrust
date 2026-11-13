"""Repeated immutable operands materialize before their containing tuple."""
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
import test_native_annotations_assertions as assertion_tests

CASES={
 'nested_nullable_union_return':('def pack(value):return value,(value,False)\nfor value in (3,"text",None):\n result=pack(value)\n print(result)\n',('',)),
 'repeated_union_in_call_and_list':('def pair(first,second):return first,(second,first)\nfor item in (7,"word",None):\n print(pair(item,item))\n print([item,item,(item,item)])\n print(item)\n',('',)),
 'repeated_nullable_numeric':('def pack(item):return item,(item,item)\nfor item in (None,7,None,-4):\n print(pack(item),item)\n',('',)),
 'repeated_nonnumeric_union':('def pack(item):return item,(item,item)\nfor item in ("word",b"bytes",None):\n print(pack(item),item)\n',('',)),
 'nested_noncopy_tuple_fields':('def pack(item):return item,(item,item)\nfor item in ((3,"first"),(4,"second")):\n print(pack(item),item)\n',('',)),
 'repeated_bytes_fields':('def pack(item):return item,(item,item)\nitem=b"raw"\nprint(pack(item),item)\n',('',)),
 'repeated_string_fields':('def pack(item):return item,(item,item)\nitem="word"\nprint(pack(item),item)\n',('',)),
 'repeated_wide_integer':('def pack(item):return item,(item,item)\nitem=2**60+13\nprint(pack(item),item)\n',('',)),
 'repeated_tuple_comparison':('def pack(item):return item,(item,item)\nfor item in (3,"word",None):\n result=pack(item)\n print(result==pack(item),result!=pack(item),item)\n',('',)),
 'copy_tuple_operands':('def pack(item):return item,(item,item)\nitem=(7,False,3.5)\nprint(pack(item),item)\n',('',)),
 'field_effect_order':('def mark(label,item):\n print(label)\n return item\ndef pack(item):return mark("first",item),(mark("second",item),mark("third",item))\nfor item in (3,"word",None):print(pack(item))\n',('',)),
 'field_error_before_later_effect':('def mark(label,item):\n print(label)\n return item\ndef pack(item):return mark("first",item),(10//int(input()),mark("last",item))\nfor item in (3,"word",None):print(pack(item))\n',('0\n','2\n0\n','2\n2\n2\n')),
 'missing_field_before_later_effect':('def pack(enabled):\n if enabled:item="bound"\n return item,(item,input())\nprint(pack(int(input())))\n',('0\nunread\n','1\nlast\n')),
 'shared_list_aliases':('row=[1]\nother=row\npair=(row,(row,other))\nrow.append(2)\nprint(pair,row,other,pair[0] is row,pair[1][0] is other)\n',('',)),
}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TupleOperandOwnershipTests(unittest.TestCase):
 compare=assertion_tests.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
for _name in CASES:setattr(TupleOperandOwnershipTests,'test_'+_name,_case(_name))

class TupleOperandOwnershipSelectionTests(unittest.TestCase):
 def test_repeated_finite_immutable_values_keep_ordinary_generation(self):
  for name in ('nested_nullable_union_return','repeated_nullable_numeric','nested_noncopy_tuple_fields','repeated_string_fields','repeated_wide_integer'):
   source=CASES[name][0]
   self.assertFalse(select_frames(build_program(source,'tuple_ownership.py').main).required,name)
 def test_primitive_and_owned_tuple_operands_do_not_gain_inner_clones(self):
  source='def pack(item):return item,(item,False)\nprint(pack(7))\n'
  for integer in ('i64','i128'):
   with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
    result=transpile(source,TranspileOptions(integer=integer,filename='tuple_ownership.py'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertIn('return Ok((native_var_0,(native_var_0,false)));',result.rust_source)

if __name__=='__main__':unittest.main()
