"""Finite builtin list receivers append through their original shared handles."""
import unittest
import test_native_annotations_assertions as assertion_tests
from py2fastrust import transpile,TranspileOptions

CASES={
 'module_aliases_keep_selected_allocation':('left=[1]\nright=["x"]\nselected=left if int(input()) else right\nprint(selected.append(7))\nprint(left,right,selected,selected is left,selected is right)\n',('0\n','1\n')),
 'returned_three_layouts':('def make(which):\n if which==0:return [1]\n if which==1:return ["x"]\n return [b"bytes"]\nselected=make(int(input()))\nselected.append(None)\nprint(selected)\n',('0\n','1\n','2\n')),
 'branch_assignment_and_helper_forwarding':('def add(values,item):\n values.append(item)\n return values\nleft=[2]\nright=["word"]\nif int(input()):selected=left\nelse:selected=right\nprint(add(selected,9),left,right)\n',('0\n','1\n')),
 'field_receiver_is_captured_before_rebinding':('class Store:\n def __init__(self,which):self.items=[1] if which else ["x"]\n def replace(self):\n  self.items=[3.5]\n  return 8\nstore=Store(int(input()))\nold=store.items\nstore.items.append(store.replace())\nprint(old,store.items,old is store.items)\n',('0\n','1\n')),
 'callback_mutates_captured_receiver':('class Store:\n def __init__(self,which):self.items=[1] if which else ["x"]\n def before(self):\n  self.items.append(6)\n  return 8\nstore=Store(int(input()))\nstore.items.append(store.before())\nprint(store.items)\n',('0\n','1\n')),
 'temporary_owner_expression':('flag=int(input())\n([1] if flag else ["x"]).append(3)\nprint("done")\n',('0\n','1\n')),
 'no_arguments_reports_builtin_arity':('left=[1]\nright=["x"]\nselected=left if int(input()) else right\nselected.append()\n',('0\n','1\n')),
 'all_arguments_evaluated_before_arity_error':('def mark(value):\n print(value)\n return value\nleft=[1]\nright=["x"]\nselected=left if int(input()) else right\nselected.append(mark("first"),mark("second"))\n',('0\n','1\n')),
 'keyword_value_runs_before_builtin_keyword_error':('def mark():\n print("argument")\n return 7\nleft=[1]\nright=["x"]\nselected=left if int(input()) else right\nselected.append(value=mark())\n',('0\n','1\n')),
 'argument_error_precedes_arity_error':('def mark():\n print("later")\n return 7\nleft=[1]\nright=["x"]\nselected=left if int(input()) else right\nselected.append(10//int(input()),mark())\n',('0\n0\n','1\n2\n')),
 'returned_receiver_capture_before_global_rebind':('left=[1]\nright=["x"]\nselected=left if int(input()) else right\ndef owner():return selected\ndef replace():\n global selected\n selected=[b"new"]\n return 7\nold=selected\nowner().append(replace())\nprint(old,selected,old is selected)\n',('0\n','1\n')),
 'mutable_payload_keeps_its_own_alias':('left=[[1]]\nright=[["x"]]\nselected=left if int(input()) else right\nrow=[7]\nselected.append(row)\nrow.append(8)\nprint(left,right,row,selected[-1] is row)\n',('0\n','1\n')),
 'numeric_alternatives_preserve_bool_values':('left=[True]\nright=[2.5]\nselected=left if int(input()) else right\nselected.append(7)\nprint(left,right,selected)\n',('0\n','1\n')),
 'append_result_is_actual_none':('def add(values):return values.append(7)\nleft=[1]\nright=["x"]\nselected=left if int(input()) else right\nprint(add(selected),selected)\n',('0\n','1\n')),
}
BOUNDARIES={
 'stored_method_value':'left=[1]\nright=["x"]\nselected=left if int(input()) else right\nsaved=selected.append\nsaved(7)\n',
 'actual_nonlist_alternative':'selected=[1] if int(input()) else None\nselected.append(7)\n',
 'user_method_and_builtin_list':'class Other:\n def append(self,value):print("custom",value)\nselected=[1] if int(input()) else Other()\nselected.append(7)\n',
}

class FiniteListAppendExecutionTests(unittest.TestCase):
 compare=assertion_tests.AnnotationAndAssertionExecutionTests.compare

def _case(name):
 def test(self):self.compare(*CASES[name])
 return test
for _name in CASES:setattr(FiniteListAppendExecutionTests,'test_'+_name,_case(_name))

class FiniteListAppendBoundaryTests(unittest.TestCase):
 def test_stored_and_nonlist_method_families_remain_positioned_boundaries(self):
  for name,source in BOUNDARIES.items():
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,filename='finite_append.py'))
    self.assertFalse(result.success,(name,integer))
    self.assertTrue(any(item.code=='E006'and item.line>=2 and 'append'in item.message for item in result.diagnostics),(name,result.diagnostics))

if __name__=='__main__':unittest.main()
