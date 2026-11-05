"""Unique non-Copy source objects keep owned fields and delayed receiver loans."""
import re
import shutil
import unittest
from py2fastrust import transpile, TranspileOptions
import test_native_lambda_callbacks as helpers

# These originals also have separately frozen, strict external CP oracles.
CASES = {'local_buffer': ('class Buffer:\n'
                  ' def __init__(self,n):\n'
                  '  self.n=n\n'
                  '  self.values=[0]*n\n'
                  ' def add(self,index,value):self.values[index]+=value\n'
                  ' def total(self):\n'
                  '  result=0\n'
                  '  for i in range(self.n):result+=self.values[i]\n'
                  '  return result\n'
                  'def main():\n'
                  ' data=Buffer(4)\n'
                  ' data.add(1,7)\n'
                  ' data.add(3,5)\n'
                  ' print(data.total())\n'
                  'main()\n',
                  ['']),
 'local_reassignment': ('class Buffer:\n'
                        ' def __init__(self,n):\n'
                        '  self.n=n\n'
                        '  self.values=[0]*n\n'
                        ' def add(self,index,value):self.values[index]+=value\n'
                        ' def total(self):\n'
                        '  result=0\n'
                        '  for i in range(self.n):result+=self.values[i]\n'
                        '  return result\n'
                        'def main():\n'
                        ' data=Buffer(2)\n'
                        ' data.add(1,4)\n'
                        ' data=Buffer(data.total())\n'
                        ' print(data.total())\n'
                        'main()\n',
                        ['']),
 'self_method_calls': ('class Buffer:\n'
                       ' def __init__(self,n):\n'
                       '  self.n=n\n'
                       '  self.values=[0]*n\n'
                       ' def add(self,index,value):self.values[index]+=value\n'
                       ' def total(self):\n'
                       '  result=0\n'
                       '  for i in range(self.n):result+=self.values[i]\n'
                       '  return result\n'
                       'class Counter:\n'
                       ' def __init__(self):self.values=[1,2,3]\n'
                       ' def read(self,i):return self.values[i]\n'
                       ' def replace(self,i,value):self.values[i]=value\n'
                       ' def combine(self):\n'
                       '  self.replace(1,self.read(0)+self.read(2))\n'
                       '  return self.read(1)\n'
                       'def main():\n'
                       ' data=Counter()\n'
                       ' print(data.combine())\n'
                       'main()\n',
                       ['']),
 'index_callback_reentry': ('class Counter:\n'
                            ' def __init__(self):\n'
                            '  self.values=[2,3]\n'
                            '  self.events=0\n'
                            ' def index(self):\n'
                            '  self.events+=1\n'
                            '  return 0\n'
                            ' def run(self):\n'
                            '  self.values[self.index()]+=5\n'
                            '  return self.values[0]+self.events\n'
                            'def main():\n'
                            ' data=Counter()\n'
                            ' print(data.run())\n'
                            'main()\n',
                            ['']),
 'plain_alias_negative': ('class Buffer:\n'
                          ' def __init__(self,n):\n'
                          '  self.n=n\n'
                          '  self.values=[0]*n\n'
                          ' def add(self,index,value):self.values[index]+=value\n'
                          ' def total(self):\n'
                          '  result=0\n'
                          '  for i in range(self.n):result+=self.values[i]\n'
                          '  return result\n'
                          'def main():\n'
                          ' data=Buffer(2)\n'
                          ' alias=data\n'
                          ' alias.add(0,8)\n'
                          ' print(data.total(),alias.total())\n'
                          'main()\n',
                          ['']),
 'factory_escape_negative': ('class Buffer:\n'
                             ' def __init__(self,n):\n'
                             '  self.n=n\n'
                             '  self.values=[0]*n\n'
                             ' def add(self,index,value):self.values[index]+=value\n'
                             ' def total(self):\n'
                             '  result=0\n'
                             '  for i in range(self.n):result+=self.values[i]\n'
                             '  return result\n'
                             'def factory():\n'
                             ' data=Buffer(2)\n'
                             ' return data\n'
                             'def main():\n'
                             ' data=factory()\n'
                             ' data.add(1,8)\n'
                             ' print(data.total())\n'
                             'main()\n',
                             ['']),
 'callback_capture_negative': ('class Buffer:\n'
                               ' def __init__(self,n):\n'
                               '  self.n=n\n'
                               '  self.values=[0]*n\n'
                               ' def add(self,index,value):self.values[index]+=value\n'
                               ' def total(self):\n'
                               '  result=0\n'
                               '  for i in range(self.n):result+=self.values[i]\n'
                               '  return result\n'
                               'def main():\n'
                               ' data=Buffer(2)\n'
                               ' def change():\n'
                               '  data.add(1,6)\n'
                               '  return 0\n'
                               ' data.add(change(),3)\n'
                               ' print(data.total())\n'
                               'main()\n',
                               ['']),
 'argument_receiver_rebind_negative': ('class Buffer:\n'
                                       ' def __init__(self,n):\n'
                                       '  self.n=n\n'
                                       '  self.values=[0]*n\n'
                                       ' def add(self,index,value):self.values[index]+=value\n'
                                       ' def total(self):\n'
                                       '  result=0\n'
                                       '  for i in range(self.n):result+=self.values[i]\n'
                                       '  return result\n'
                                       'def main():\n'
                                       ' data=Buffer(2)\n'
                                       ' print(data.add(0,(data:=Buffer(3)).total()),data.n)\n'
                                       'main()\n',
                                       ['']),
 'missing_field': ('class Buffer:\n'
                   ' def __init__(self,enabled):\n'
                   '  if enabled:self.values=[7]\n'
                   ' def read(self,index):return self.values[index]\n'
                   'def main():\n'
                   ' data=Buffer(int(input()))\n'
                   ' print(data.read(0))\n'
                   'main()\n',
                   ['1\n', '0\n']),
 'zero_trip_owner_lookup': ('class Buffer:\n'
                            ' def __init__(self,n):\n'
                            '  self.n=n\n'
                            '  self.values=[0]*n\n'
                            ' def add(self,index,value):self.values[index]+=value\n'
                            ' def total(self):\n'
                            '  result=0\n'
                            '  for i in range(self.n):result+=self.values[i]\n'
                            '  return result\n'
                            'def argument():\n'
                            ' print("argument")\n'
                            ' return 0\n'
                            'def main():\n'
                            ' for i in range(int(input())):data=Buffer(2)\n'
                            ' print(data.add(argument(),3))\n'
                            'main()\n',
                            ['0\n', '2\n']),
 'constructor_error': ('class Buffer:\n'
                       ' def __init__(self,denominator):\n'
                       '  self.values=[1,2]\n'
                       '  self.factor=9//denominator\n'
                       ' def read(self):return self.values[0]*self.factor\n'
                       'def main():\n'
                       ' data=Buffer(int(input()))\n'
                       ' print(data.read())\n'
                       'main()\n',
                       ['3\n', '0\n'])}

@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeOwnedObjectPlaceTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise

    def generated(self, name, integer="i64"):
        result = transpile(CASES[name][0], TranspileOptions(integer=integer, license="none"))
        self.assertTrue(result.success, result.diagnostics)
        return result.rust_source

    def test_unique_noncopy_data_has_no_shared_owner_or_clone(self):
        for name in ("local_buffer", "local_reassignment", "self_method_calls",
                     "index_callback_reentry", "missing_field", "zero_trip_owner_lookup",
                     "constructor_error"):
            for mode in ("i64", "i128", "bigint"):
                with self.subTest(source=name, mode=mode):
                    rust = self.generated(name, mode)
                    owners = re.findall(r"type ClassHandle_(\d+)=ClassData_\1;", rust)
                    self.assertEqual(len(owners), 1)
                    number = owners[0]
                    self.assertNotIn("type ClassHandle_" + number + "=Rc<", rust)
                    self.assertIn("Option<Vec<NativeInt>>", rust)
                    self.assertIn("class_argument_0:&mut ClassHandle_" + number, rust)
                    self.assertNotIn("#[derive(Clone)]\nstruct ClassData_" + number, rust)
                    constructor = re.search(r"fn class_construct_" + number + r"\([^\n]+", rust).group()
                    self.assertNotIn("Rc::new", constructor)
                    self.assertNotIn("Rc::try_unwrap", constructor)

    def test_aliased_escaped_captured_or_rebound_owners_keep_sharing(self):
        for name in ("plain_alias_negative", "factory_escape_negative",
                     "callback_capture_negative", "argument_receiver_rebind_negative"):
            for mode in ("i64", "i128", "bigint"):
                with self.subTest(source=name, mode=mode):
                    self.assertIn("type ClassHandle_0=Rc<RefCell<ClassData_0>>;",
                                  self.generated(name, mode))

    def test_owned_vec_setter_borrows_the_actual_owner_mutably(self):
        rust = self.generated("local_buffer")
        self.assertIn("class_owned_field_0_1_set(owner:&mut ClassHandle_0", rust)
        self.assertNotIn("fn class_get_0_1(", rust)
        self.assertIn("fn borrow_mut(&mut self)->&mut Self{self}", rust)


def install(name):
    def test(self):
        self.exercise(*CASES[name])
    test.__name__ = "test_" + name
    setattr(NativeOwnedObjectPlaceTests, test.__name__, test)
for name in CASES:
    install(name)
