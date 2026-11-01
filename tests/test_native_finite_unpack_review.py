"""Independent fixed-tuple unpack order, sharing, and capability boundaries."""
import hashlib,shutil,unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_finite_tuple_unpacking as helpers

CASES = [('same_shape_tuple_alias_leaves_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'left=[1]\n'
  'right=[2]\n'
  'flag=int(input())\n'
  'item=(left,Node(3))if flag==1 else(right,Node(4))if flag==2 else None\n'
  'values,obj=item\n'
  "values.append('x')\n"
  'print(left,right,values is left,values is right,obj.value)\n',
  '0\n',
  '5cabc1fe4b8d03d82067800977b7cabd52331e426ca666c8679a28f88cab1a41'),
 ('same_shape_tuple_alias_leaves_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'left=[1]\n'
  'right=[2]\n'
  'flag=int(input())\n'
  'item=(left,Node(3))if flag==1 else(right,Node(4))if flag==2 else None\n'
  'values,obj=item\n'
  "values.append('x')\n"
  'print(left,right,values is left,values is right,obj.value)\n',
  '1\n',
  '5cabc1fe4b8d03d82067800977b7cabd52331e426ca666c8679a28f88cab1a41'),
 ('same_shape_tuple_alias_leaves_2',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'left=[1]\n'
  'right=[2]\n'
  'flag=int(input())\n'
  'item=(left,Node(3))if flag==1 else(right,Node(4))if flag==2 else None\n'
  'values,obj=item\n'
  "values.append('x')\n"
  'print(left,right,values is left,values is right,obj.value)\n',
  '2\n',
  '5cabc1fe4b8d03d82067800977b7cabd52331e426ca666c8679a28f88cab1a41'),
 ('lhs_index_depends_on_prior_target_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'values=[0,0,0]\n'
  'item=(2,9)if int(input())else None\n'
  'i,values[i]=item\n'
  'print(i,values)\n',
  '0\n',
  'f3d68fd3b8082607f7efa34603660590e4a9bcefc366e049cb14ef62cd55139e'),
 ('lhs_index_depends_on_prior_target_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'values=[0,0,0]\n'
  'item=(2,9)if int(input())else None\n'
  'i,values[i]=item\n'
  'print(i,values)\n',
  '1\n',
  'f3d68fd3b8082607f7efa34603660590e4a9bcefc366e049cb14ef62cd55139e'),
 ('same_attribute_target_twice_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'owner=Node(0)\n'
  "item=(3,'last')if int(input())else None\n"
  'owner.value,owner.value=item\n'
  'print(owner.value)\n',
  '0\n',
  'b8d7454b81703777112cce3679b2e9ce7c82f27347dd01568567fdc5d5cbc2cd'),
 ('same_attribute_target_twice_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'owner=Node(0)\n'
  "item=(3,'last')if int(input())else None\n"
  'owner.value,owner.value=item\n'
  'print(owner.value)\n',
  '1\n',
  'b8d7454b81703777112cce3679b2e9ce7c82f27347dd01568567fdc5d5cbc2cd'),
 ('lhs_owner_calls_after_arity_check_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'events=[]\n'
  'owner=Node(0)\n'
  'def target():events.append(1);return owner\n'
  'item=(3,4)if int(input())else(5,)\n'
  'target().value,target().value=item\n'
  'print(owner.value,events)\n',
  '0\n',
  'a8a64ec084b36ca12567d3c39ac717c751aaa40719c91db8a57f11fc08f2a600'),
 ('lhs_owner_calls_after_arity_check_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'events=[]\n'
  'owner=Node(0)\n'
  'def target():events.append(1);return owner\n'
  'item=(3,4)if int(input())else(5,)\n'
  'target().value,target().value=item\n'
  'print(owner.value,events)\n',
  '1\n',
  'a8a64ec084b36ca12567d3c39ac717c751aaa40719c91db8a57f11fc08f2a600'),
 ('nested_failure_preserves_prior_store_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'owner=Node(0)\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  " def __exit__(self,a,b,c):print('stored',owner.value)\n"
  'item=(3,(4,5))if int(input())else(7,(8,))\n'
  'with Guard():owner.value,(a,b)=item\n'
  'print(owner.value,a,b)\n',
  '0\n',
  '91b0c0da62c850aad4b9cdbfa1c84eac6c603078fcf1b5a15c279553427d43c0'),
 ('nested_failure_preserves_prior_store_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'owner=Node(0)\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  " def __exit__(self,a,b,c):print('stored',owner.value)\n"
  'item=(3,(4,5))if int(input())else(7,(8,))\n'
  'with Guard():owner.value,(a,b)=item\n'
  'print(owner.value,a,b)\n',
  '1\n',
  '91b0c0da62c850aad4b9cdbfa1c84eac6c603078fcf1b5a15c279553427d43c0'),
 ('chained_targets_reuse_original_rhs_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'left=[1]\n'
  'item=(left,Node(3))if int(input())else None\n'
  'whole=values,obj=item\n'
  'values.append(7)\n'
  'print(whole is item,whole[0]is values,left,obj.value)\n',
  '0\n',
  '3f1c96552408a8c2ec4dbaabe8bc696301d2327401a3c8a4d4ac7f82978ee6a7'),
 ('chained_targets_reuse_original_rhs_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'left=[1]\n'
  'item=(left,Node(3))if int(input())else None\n'
  'whole=values,obj=item\n'
  'values.append(7)\n'
  'print(whole is item,whole[0]is values,left,obj.value)\n',
  '1\n',
  '3f1c96552408a8c2ec4dbaabe8bc696301d2327401a3c8a4d4ac7f82978ee6a7'),
 ('for_targets_preserve_position_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else None\n'
  'for number,obj in [item]:print(number,obj.value)\n',
  '0\n',
  '2ecb4175ffb3e45a8bab1348f25ef438dac6cc04ff4a2ca556d6c4f8e759984e'),
 ('for_targets_preserve_position_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else None\n'
  'for number,obj in [item]:print(number,obj.value)\n',
  '1\n',
  '2ecb4175ffb3e45a8bab1348f25ef438dac6cc04ff4a2ca556d6c4f8e759984e'),
 ('comprehension_targets_preserve_position_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else None\n'
  'print([(number,obj.value)for number,obj in [item]])\n',
  '0\n',
  '6a413e3306d20616f37192ddd959d19c5945c01110e8ab42f8a256cbe1fba089'),
 ('comprehension_targets_preserve_position_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'item=(3,Node(7))if int(input())else None\n'
  'print([(number,obj.value)for number,obj in [item]])\n',
  '1\n',
  '6a413e3306d20616f37192ddd959d19c5945c01110e8ab42f8a256cbe1fba089'),
 ('source_function_value_noniterable_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def callback():return 4\n'
  'item=(3,Node(7))if int(input())else callback\n'
  'number,obj=item\n'
  'print(number,obj.value)\n',
  '0\n',
  '81e388475c51e29e94cafb4202343ba3e20be9761c52d1ff5d92ff909b07274c'),
 ('source_function_value_noniterable_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def callback():return 4\n'
  'item=(3,Node(7))if int(input())else callback\n'
  'number,obj=item\n'
  'print(number,obj.value)\n',
  '1\n',
  '81e388475c51e29e94cafb4202343ba3e20be9761c52d1ff5d92ff909b07274c'),
 ('nested_mutation_updates_original_inner_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'values=[1]\n'
  'item=(3,(values,Node(7)))if int(input())else None\n'
  'number,(inner,obj)=item\n'
  "inner.append('more')\n"
  'print(values,inner is values,number,obj.value)\n',
  '0\n',
  '69a2ed3d6be8c9c704463b9bf8313a1975599e1a3a2af34a0607a462301546be'),
 ('nested_mutation_updates_original_inner_1',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'values=[1]\n'
  'item=(3,(values,Node(7)))if int(input())else None\n'
  'number,(inner,obj)=item\n'
  "inner.append('more')\n"
  'print(values,inner is values,number,obj.value)\n',
  '1\n',
  '69a2ed3d6be8c9c704463b9bf8313a1975599e1a3a2af34a0607a462301546be'),
 ('deferred_empty_local_producer_after_loop_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def run():\n'
  ' values=[]\n'
  ' for item in values:print(item.value)\n'
  ' values.append(Node(7))\n'
  ' return values[0].value\n'
  'print(run())\n',
  '',
  '74a17b3c77522234bc7edfe003653c5823865cb017de0c08ceaf385ef099ffb9'),
 ('deferred_empty_local_producer_inside_later_call_0',
  'class Node:\n'
  ' def __init__(self,value):self.value=value\n'
  'def fill(values):values.append(Node(7))\n'
  'def run():\n'
  ' values=[]\n'
  ' for item in values:print(item.value)\n'
  ' fill(values)\n'
  ' return values[0].value\n'
  'print(run())\n',
  '',
  'b1b121e1ad8220d0de8e4b42be174a3c0d43bafeb1d52f67c7ffe911d1eae34e')]


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class IndependentFiniteUnpackExecutionTests(unittest.TestCase):
    exercise=helpers.FiniteTupleUnpackExecutionTests.exercise


class IndependentFiniteUnpackBoundaryTests(unittest.TestCase):
    def check_boundary(self,source):
        for mode in ("i64","i128","bigint"):
            with self.subTest(integer=mode):
                result=transpile(source,TranspileOptions(filename="main.py",integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(len(result.diagnostics),1)
                diagnostic=result.diagnostics[0]
                self.assertEqual(diagnostic.code,"E006")
                self.assertEqual(diagnostic.line,7)
                self.assertEqual(diagnostic.column,7)
                self.assertIn("Cannot lower comparison 'is'",diagnostic.message)
                self.assertIn("tuple[list[int], Node]",diagnostic.message)
                self.assertIn("whole is item",diagnostic.message)


def _execution(source,stdin,digest):
    def test(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.exercise(source,stdin)
    return test


def _boundary(source,stdin,digest):
    def test(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.assertIn(stdin,("0\n","1\n"))
        self.check_boundary(source)
    return test


for _name,_source,_stdin,_digest in CASES:
    if _name.startswith("chained_targets_reuse_original_rhs_"):
        setattr(IndependentFiniteUnpackBoundaryTests,"test_"+_name,_boundary(_source,_stdin,_digest))
    else:
        setattr(IndependentFiniteUnpackExecutionTests,"test_"+_name,_execution(_source,_stdin,_digest))
