"""Truth-only contexts short-circuit without mutable value-result unions."""
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeConditionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_if_list_boolean_short_circuit_skips_empty_index(self):
        self.exercise('''values=list(range(int(input())))
if values and values[-1]>=0:
 print("present")
if values or False:
 print("truth")
print(values)
''',('0\n','1\n','3\n'))

    def test_while_stack_conditions_read_current_contents(self):
        self.exercise('''values=list(range(int(input())))
while values and values[-1]>=0:
 print(values.pop(),end="|")
print(values)
''',('0\n','1\n','4\n'))

    def test_skipped_pops_do_not_create_false_empty_length_proofs(self):
        for initial in ([],[7],[7,8]):
            source='values='+repr(initial)+'''
if True or values.pop():pass
print(values,next(iter(values),None))
if False and values.pop():pass
print(values,next(iter(values),None))
'''
            self.exercise(source,('',))

    def test_executed_pops_are_lowered_and_run_once(self):
        self.exercise('''values=[1,2]
if values and values.pop()>0:
 print("yes")
print(values,next(iter(values),None))
if values and values.pop():
 print("last")
print(values,next(iter(values),None))
''',('',))


    def test_condition_ifexp_selects_none_or_existing_container(self):
        self.exercise('''flag=int(input())
values=[2]
if (values if flag else None)and values[-1]==2:
 print("yes")
if (None if flag else values)or not values:
 print("other")
print(values)
''',('0\n','1\n'))

    def test_not_and_canonical_bool_use_truth_only_operands(self):
        self.exercise('''values=list(range(int(input())))
print(not(values and values[-1]),bool(values and values[-1]),bool(values or None),bool())
print(bool(values if values else None),not(None if values else values))
print(values)
''',('0\n','1\n','3\n'))

    def test_ifexp_value_uses_truth_only_test_and_keeps_branch_value(self):
        self.exercise('''values=list(range(int(input())))
answer="yes"if values and values[-1]>=0 else 7
print(answer,values)
''',('0\n','1\n','3\n'))

    def test_supported_comprehension_filters_share_condition_api(self):
        self.exercise('''values=list(range(int(input())))
print([x for x in range(4)if values and x<len(values)])
print(sum(x for x in range(4)if values or x==2))
print([x for x in range(4)if not(values and x>=len(values))])
''',('0\n','1\n','3\n'))

    def test_comprehension_filter_mutations_keep_parent_facts_conservative(self):
        self.exercise('''values=[1,2]
print([x for x in range(4)if values and values.pop()])
print(values,next(iter(values),None))
''',('',))

    def test_operand_order_and_unbound_errors_are_short_circuited(self):
        self.exercise('''def mark(tag,value):
 print(tag,end="|")
 return value
if int(input()):item=3
if mark("first",[1])or mark("skip",item):
 print("true")
if mark("second",[])or mark("read",item):
 print("item")
''',('0\n','1\n'))

    def test_generator_filter_error_preserves_frames_and_prior_effects(self):
        self.exercise('''values=[1]
print("before",end="|")
print(sum(x for x in range(3)if values and values[x]))
''',('',))

    def test_ifexp_branches_and_bool_calls_skip_mutations_in_other_branch(self):
        self.exercise('''values=[1,2]
flag=int(input())
if (values.pop() if flag else values.clear())and values:
 print("selected")
print(values,next(iter(values),None))
''',('0\n','1\n'))

    def test_float_truth_and_nan_follow_builtin_truth(self):
        self.exercise('''value=float(input())
if []or value:print("true")
print(not(value and []),bool([]or value))
''',('0\n','-0\n','nan\n','1.5\n'),modes=('i64','i128'))

    def test_actual_value_returning_mixed_boolop_preserves_selected_value(self):
        self.exercise('values=[]\nresult=values and 7\nprint(result)\n',('',))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassConditionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_class_fields_in_if_and_while_are_truth_only(self):
        self.exercise('''class Stack:
 def __init__(self,n):self.values=list(range(n))
 def drain(self):
  while self.values and self.values[-1]>=0:
   print(self.values.pop(),end="|")
  if self.values or False:print("unreachable")
  print(self.values)
Stack(int(input())).drain()
''',('0\n','1\n','4\n'))

    def test_class_not_bool_and_ifexp_predicates_preserve_effect_order(self):
        self.exercise('''class Box:
 def __init__(self):self.values=[1,2]
 def choose(self,flag):
  print(not(self.values and self.values[-1]),bool(self.values and self.values[-1]))
  if(self.values.pop()if flag else self.values.clear())and self.values:
   print("selected")
  print(self.values)
Box().choose(int(input()))
''',('0\n','1\n'))

    def test_class_comprehension_filters_use_truth_only_values(self):
        self.exercise('''class Box:
 def __init__(self,n):self.values=list(range(n))
 def select(self):
  return [x for x in range(4)if self.values and x<len(self.values)]
box=Box(int(input()))
print(box.select(),box.values)
''',('0\n','1\n','3\n'))

    def test_default_object_constructors_and_tuple_elements_still_execute(self):
        self.exercise('''class Box:
 def __init__(self):print("made",end="|")
def mark():
 print("item",end="|")
 return 3
if Box()and(mark(),):print("yes")
print(not Box(),bool(Box()or []))
''',('',))

    def test_custom_truth_protocol_is_not_silently_ignored(self):
        source='class Box:\n def __bool__(self):return False\nif Box()and True:print(1)\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
