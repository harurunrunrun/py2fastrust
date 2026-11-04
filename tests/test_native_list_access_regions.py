"""Loop-wide list borrows preserve aliasing, failures and control-flow exits."""
import shutil
import unittest
import test_native_lambda_callbacks as helpers


CASES={
    'read_loop_stable_alias': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n total=0\n for i in range(4):\n  total+=a[i]+a[-i-1]\n return total\nbox=Box()\nprint(solve(box),box.values)\n',
    'readonly_two_aliases': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n b=a\n total=0\n for i in range(4):\n  total+=a[i]*b[3-i]\n return total\nprint(solve(Box()))\n',
    'readonly_two_roots': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n b=box.other\n total=0\n for i in range(4):\n  total+=a[i]*b[i]\n return total\nprint(solve(Box()))\n',
    'mutating_scalar_dp': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(1,len(a)):\n  a[i]=a[i]+a[i-1]\nbox=Box()\nalias=box.values\nsolve(box)\nprint(box.values,alias,alias is box.values)\n',
    'augmented_own_reads': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(1,4):\n  a[i]+=a[i-1]+a[-1]\nbox=Box()\nsolve(box)\nprint(box.values)\n',
    'while_scalar_updates': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n i=0\n while i<len(a):\n  a[i]^=i+3\n  i+=1\nbox=Box()\nsolve(box)\nprint(box.values)\n',
    'augmented_get_before_rhs_error': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(1):\n  a[99]+=1//0\nsolve(Box())\n',
    'assign_rhs_error_before_bad_index': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(1):\n  a[99]=1//0\nsolve(Box())\n',
    'read_negative_out_of_bounds': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n total=0\n for i in range(1):\n  total+=a[-5]\n return total\nprint(solve(Box()))\n',
    'store_negative_out_of_bounds': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(1):\n  a[-5]=8\nsolve(Box())\n',
    'zero_trip_missing_local': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n if False:\n  a=box.values\n total=19\n for i in range(0):\n  total+=a[i]\n return total\nprint(solve(Box()))\n',
    'while_false_missing_local': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n if False:\n  a=box.values\n total=19\n while False:\n  total+=a[0]\n return total\nprint(solve(Box()))\n',
    'branch_without_first_read': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n if False:\n  a=box.values\n total=0\n for i in range(4):\n  if i<0:\n   total+=a[i]\n return total\nprint(solve(Box()))\n',
    'first_owner_error_before_index_error': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n if False:\n  a=box.values\n total=0\n for i in range(1):\n  total+=a[1//0]\n return total\nprint(solve(Box()))\n',
    'nested_mutable_loops': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(3):\n  for j in range(1,4):\n   a[j]+=a[j-1]+i\nbox=Box()\nsolve(box)\nprint(box.values)\n',
    'break_continue_else': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(4):\n  if i==1:\n   continue\n  a[i]+=i\n  if a[i]>8:\n   break\n else:\n  a[0]=99\nbox=Box()\nsolve(box)\nprint(box.values)\n',
    'return_inside_borrowed_loop': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n i=0\n while i<4:\n  a[i]+=1\n  if a[i]>4:\n   return a[i]\n  i+=1\n return -1\nbox=Box()\nprint(solve(box))\nbox.values.append(41)\nprint(box.values)\n',
    'callback_mutates_same_root': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef touch(a):\n a.append(9)\n return -1\ndef solve(box):\n a=box.values\n total=0\n for i in range(2):\n  total+=a[touch(a)]\n return total\nbox=Box()\nprint(solve(box),box.values)\n',
    'different_name_mutates_alias': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n b=a\n for i in range(4):\n  a[i]+=b[-1]\n  b[-1]+=1\nbox=Box()\nsolve(box)\nprint(box.values)\n',
    'root_rebinding_in_loop': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n total=0\n for i in range(4):\n  total+=a[0]\n  if i==1:\n   a=box.other\n return total\nprint(solve(Box()))\n',
    'nonlocal_callback_rebinds_owner': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n def touch():\n  nonlocal a\n  a=box.other\n  return 0\n total=0\n for i in range(2):\n  total+=a[touch()]\n return total\nprint(solve(Box()))\n',
    'list_method_under_loop': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n total=0\n for i in range(2):\n  total+=a.pop()\n  a[0]+=1\n return total\nbox=Box()\nprint(solve(box),box.values)\n',
    'list_iterator_and_live_growth': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n total=0\n for value in a:\n  total+=value\n  a[0]+=1\n  if value==3:\n   a.append(11)\n return total\nbox=Box()\nprint(solve(box),box.values)\n',
    'bool_indices_and_len': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n for i in range(3):\n  a[i==1]+=len(a)+a[False]\nbox=Box()\nsolve(box)\nprint(box.values)\n',
    'negative_zero_trip_for_else': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n if False:\n  a=box.values\n for i in range(-4):\n  a[0]+=1\n else:\n  return 31\nprint(solve(Box()))\n',
    'field_rebinding_through_alias': 'class Box:\n def __init__(self):\n  self.values=[2,3,5,7]\n  self.other=[11,13,17,19]\ndef solve(box):\n a=box.values\n total=0\n for i in range(3):\n  total+=a[0]\n  box.values=box.other\n return total\nbox=Box()\nprint(solve(box),box.values)\n',
    'retype_root_while_break': 'class Box:\n def __init__(self):self.values=[2,3,5]\ndef solve(box):\n a=box.values\n result=0\n while True:\n  result=a[0]\n  a=0\n  break\n return result+a\nprint(solve(Box()))\n',
    'nested_for_target_collision': 'class Box:\n def __init__(self):self.values=[2,3,5]\ndef solve(box):\n a=box.values\n result=0\n for i in range(1):\n  result=a[0]\n  for a in range(2):\n   result+=a\n  break\n return result+a\nprint(solve(Box()))\n',
    'annotated_root_retype': 'class Box:\n def __init__(self):self.values=[2,3,5]\ndef solve(box):\n a=box.values\n result=0\n while True:\n  result=a[0]\n  a:int=3\n  break\n return result+a\nprint(solve(Box()))\n',
    'dead_branch_root_retype': 'class Box:\n def __init__(self):self.values=[2,3,5]\ndef solve(box):\n a=box.values\n result=0\n for i in range(3):\n  result+=a[i]\n  if False:\n   a=0\n return result\nprint(solve(Box()))\n',
    'dead_branch_unresolved_operand': 'class Box:\n def __init__(self):self.values=[2,3,5]\ndef solve(box):\n a=box.values\n result=0\n for i in range(3):\n  result+=a[i]\n  if False:\n   result+=not_defined_here\n return result\nprint(solve(Box()))\n',
    'dead_branch_effectful_call': 'class Box:\n def __init__(self):self.values=[2,3,5]\ndef solve(box):\n a=box.values\n result=0\n for i in range(3):\n  result+=a[i]\n  if False:\n   not_defined_here(a)\n return result\nprint(solve(Box()))\n',
}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeListAccessRegionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise


def install_case(name,source):
    def test(self):
        self.exercise(source)
    test.__name__="test_"+name
    setattr(NativeListAccessRegionTests,test.__name__,test)


for name,source in CASES.items():
    install_case(name,source)
