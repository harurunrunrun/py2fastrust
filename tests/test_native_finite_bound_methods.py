"""Finite source method acquisition preserves lookup order and receiver identity."""
import hashlib,shutil,unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_finite_tuple_unpacking as helpers

CASES = [('optional_direct_method_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'print(obj.val())\n',
  '0\n',
  'd2707f6bdeae4d127db9654365b8286f2ed119d4a605d715dd1a3c66b0afe4eb'),
 ('optional_direct_method_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'print(obj.val())\n',
  '1\n',
  'd2707f6bdeae4d127db9654365b8286f2ed119d4a605d715dd1a3c66b0afe4eb'),
 ('optional_saved_method_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'saved=obj.val\n'
  'print(saved(4))\n',
  '0\n',
  '2c26f125c3f54dad7f69cea642b6c352a73cd892f6c5d4a6c0c0f6a0f3ec0e6a'),
 ('optional_saved_method_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'saved=obj.val\n'
  'print(saved(4))\n',
  '1\n',
  '2c26f125c3f54dad7f69cea642b6c352a73cd892f6c5d4a6c0c0f6a0f3ec0e6a'),
 ('multiple_class_owners_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Other:\n'
  ' def val(self,amount=3):return amount*4\n'
  'obj=Box(5)if int(input())else Other()\n'
  'print(obj.val(),obj.val(7))\n',
  '0\n',
  '2238ee50f77fb7ea2c49be5c343ab651ca79cdc4245134d61ad51692148afeb4'),
 ('multiple_class_owners_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Other:\n'
  ' def val(self,amount=3):return amount*4\n'
  'obj=Box(5)if int(input())else Other()\n'
  'print(obj.val(),obj.val(7))\n',
  '1\n',
  '2238ee50f77fb7ea2c49be5c343ab651ca79cdc4245134d61ad51692148afeb4'),
 ('lookup_precedes_call_argument_effects_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  "def owner(flag):print('owner');return Box(5)if flag else None\n"
  "def argument():print('argument');return 4\n"
  'print(owner(int(input())).val(argument()))\n',
  '0\n',
  '5d9380c2b1af0caf798ea29cd0930f3150e9a21dcc3627241a22d88ad1965c33'),
 ('lookup_precedes_call_argument_effects_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  "def owner(flag):print('owner');return Box(5)if flag else None\n"
  "def argument():print('argument');return 4\n"
  'print(owner(int(input())).val(argument()))\n',
  '1\n',
  '5d9380c2b1af0caf798ea29cd0930f3150e9a21dcc3627241a22d88ad1965c33'),
 ('captured_receiver_survives_rebinding_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'def argument():\n'
  ' global obj\n'
  ' obj=None\n'
  " print('argument')\n"
  ' return 4\n'
  'print(obj.val(argument()),obj is None)\n',
  '0\n',
  'de114cce73dcbb66387f0799f91e97a04ee9965682f928bad07ea25c3ddbb121'),
 ('captured_receiver_survives_rebinding_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'def argument():\n'
  ' global obj\n'
  ' obj=None\n'
  " print('argument')\n"
  ' return 4\n'
  'print(obj.val(argument()),obj is None)\n',
  '1\n',
  'de114cce73dcbb66387f0799f91e97a04ee9965682f928bad07ea25c3ddbb121'),
 ('saved_alias_identity_and_receiver_mutation_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'saved=obj.val\n'
  'alias=saved\n'
  'other=obj.val\n'
  'obj.value=8\n'
  'print(saved is alias,saved is other,saved==other,saved(1))\n',
  '0\n',
  '64a505729631bfca463aef9b77749f4e9ea49ff5a928eb649a6fa75a9971689d'),
 ('saved_alias_identity_and_receiver_mutation_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'obj=Box(5)if int(input())else None\n'
  'saved=obj.val\n'
  'alias=saved\n'
  'other=obj.val\n'
  'obj.value=8\n'
  'print(saved is alias,saved is other,saved==other,saved(1))\n',
  '1\n',
  '64a505729631bfca463aef9b77749f4e9ea49ff5a928eb649a6fa75a9971689d'),
 ('multiple_owner_signature_errors_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Other:\n'
  ' def val(self):return 9\n'
  "def argument():print('argument');return 4\n"
  'obj=Box(5)if int(input())else Other()\n'
  'print(obj.val(argument()))\n',
  '0\n',
  '86eb93742e509b3d0fb1bb2c337ffa9b74dbce25c3907bde6aadd891f000effb'),
 ('multiple_owner_signature_errors_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Other:\n'
  ' def val(self):return 9\n'
  "def argument():print('argument');return 4\n"
  'obj=Box(5)if int(input())else Other()\n'
  'print(obj.val(argument()))\n',
  '1\n',
  '86eb93742e509b3d0fb1bb2c337ffa9b74dbce25c3907bde6aadd891f000effb'),
 ('missing_source_class_method_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Missing:pass\n'
  'obj=Box(5)if int(input())else Missing()\n'
  "def argument():print('argument');return 4\n"
  'print(obj.val(argument()))\n',
  '0\n',
  '809b54e0e383d84297fa02e8d8f4e75ed9bd2a920267d50359ff62e03808ebde'),
 ('missing_source_class_method_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Missing:pass\n'
  'obj=Box(5)if int(input())else Missing()\n'
  "def argument():print('argument');return 4\n"
  'print(obj.val(argument()))\n',
  '1\n',
  '809b54e0e383d84297fa02e8d8f4e75ed9bd2a920267d50359ff62e03808ebde'),
 ('multiple_owner_shared_result_identity_0',
  'class Left:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def get(self):return self.value\n'
  'class Right:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def get(self):return self.value\n'
  'values=[1]\n'
  'obj=Left(values)if int(input())else Right(values)\n'
  'saved=obj.get\n'
  'result=saved()\n'
  'result.append(4)\n'
  'print(result is values,values)\n',
  '0\n',
  '073e36fd31afb6690b214fac8de926811fb8508806ed53785e600ed92ac414e3'),
 ('multiple_owner_shared_result_identity_1',
  'class Left:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def get(self):return self.value\n'
  'class Right:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def get(self):return self.value\n'
  'values=[1]\n'
  'obj=Left(values)if int(input())else Right(values)\n'
  'saved=obj.get\n'
  'result=saved()\n'
  'result.append(4)\n'
  'print(result is values,values)\n',
  '1\n',
  '073e36fd31afb6690b214fac8de926811fb8508806ed53785e600ed92ac414e3'),
 ('optional_receiver_across_function_frames_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'def run(obj):return obj.val(4)\n'
  'print(run(Box(5)))\n'
  'print(run(None))\n',
  '',
  '3fea9fd79868adb934cfc14794ee8b8987dff824dbd2d8666eb5079b782a6739'),
 ('finite_method_passed_to_map_0',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Other:\n'
  ' def val(self,amount=3):return amount*4\n'
  'obj=Box(5)if int(input())else Other()\n'
  'saved=obj.val\n'
  'print(list(map(saved,[1,2,3])))\n',
  '0\n',
  '88cc72ae77eb8f88db6a33c2c9c0aeb90ed292757db91889a3f024640d6bfe04'),
 ('finite_method_passed_to_map_1',
  'class Box:\n'
  ' def __init__(self,value):self.value=value\n'
  ' def val(self,amount=2):return self.value+amount\n'
  'class Other:\n'
  ' def val(self,amount=3):return amount*4\n'
  'obj=Box(5)if int(input())else Other()\n'
  'saved=obj.val\n'
  'print(list(map(saved,[1,2,3])))\n',
  '1\n',
  '88cc72ae77eb8f88db6a33c2c9c0aeb90ed292757db91889a3f024640d6bfe04')]

CASES += [('private_method_error_spelling_0',
  'class Box:\n'
  ' def __secret(self):return 7\n'
  ' def run(self,other):return other.__secret()\n'
  'box=Box()\n'
  'obj=box if int(input())else None\n'
  'print(box.run(obj))\n',
  '0\n',
  'd99eefdeef31f86c1fa7ca5884ae84b9d6b04edb5db9074258214e55873cf4c1'),
 ('private_method_error_spelling_1',
  'class Box:\n'
  ' def __secret(self):return 7\n'
  ' def run(self,other):return other.__secret()\n'
  'box=Box()\n'
  'obj=box if int(input())else None\n'
  'print(box.run(obj))\n',
  '1\n',
  'd99eefdeef31f86c1fa7ca5884ae84b9d6b04edb5db9074258214e55873cf4c1')]

UNSUPPORTED = {'builtin_descriptor_mixed_receiver': 'class Item:\n'
                                      ' def count(self,value):return value+2\n'
                                      "obj=Item()if int(input())else 'abba'\n"
                                      "print(obj.count('a'))\n",
 'mixed_data_and_method_value': 'class Item:\n'
                                ' def val(self):return 3\n'
                                'class Other:\n'
                                ' def __init__(self):self.val=7\n'
                                'obj=Item()if int(input())else Other()\n'
                                "def argument():print('argument');return 4\n"
                                'print(obj.val(argument()))\n',
 'finite_classmethod_descriptor': 'class Item:\n'
                                  ' @classmethod\n'
                                  ' def val(cls):return 3\n'
                                  'class Other:\n'
                                  ' def val(self):return 7\n'
                                  'obj=Item()if int(input())else Other()\n'
                                  'print(obj.val())\n'}


class FiniteMethodBoundaryTests(unittest.TestCase):
    def test_mixed_descriptor_families_are_positioned(self):
        for name,source in UNSUPPORTED.items():
            for mode in ("i64","i128","bigint"):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename="main.py",integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,"E006")
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn("method acquisition",result.diagnostics[0].message)
                    self.assertIn("adapter" if name!="finite_classmethod_descriptor" else "descriptor",result.diagnostics[0].message)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class FiniteMethodExecutionTests(unittest.TestCase):
    exercise=helpers.FiniteTupleUnpackExecutionTests.exercise


def _execution(source,stdin,digest):
    def test(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.exercise(source,stdin)
    return test


for _name,_source,_stdin,_digest in CASES:
    setattr(FiniteMethodExecutionTests,"test_"+_name,_execution(_source,_stdin,_digest))
