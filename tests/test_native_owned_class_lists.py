"""Embedded class Vec fields preserve aliases, child identities and callbacks."""
import re
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_lambda_callbacks as helpers

CASES={'fixed_field_alias_object': ('class Box:\n'
                              ' def __init__(self,n):self.data=[0]*n\n'
                              ' def add(self,i,x):self.data[i]+=x\n'
                              ' def read(self,i):return self.data[i]\n'
                              'a=Box(3)\n'
                              'b=a\n'
                              'b.add(1,7)\n'
                              'print(a.read(1),len(a.data))\n',
                              ['']),
 'distinct_objects_same_allocation': ('class Box:\n'
                                      ' def __init__(self,x):self.data=[x]\n'
                                      'boxes=[Box(i)for i in range(3)]\n'
                                      'boxes[0].data[0]=9\n'
                                      'print(boxes[0].data[0],boxes[1].data[0],boxes[2].data[0])\n',
                                      ['']),
 'tuple_elements': ('class Box:\n'
                    ' def __init__(self):self.data=[(1,"one"),(2,"two")]\n'
                    'b=Box()\n'
                    'b.data[1]=(3,"three")\n'
                    'x,y=b.data[1]\n'
                    'print(x,y,b.data[0])\n',
                    ['']),
 'finite_union_elements': ('class Box:\n'
                           ' def __init__(self):self.data=[1,"two"]\n'
                           'b=Box()\n'
                           'print(b.data[0],b.data[1])\n'
                           'b.data[0]="changed"\n'
                           'b.data[1]=7\n'
                           'print(b.data[0],b.data[1])\n',
                           ['']),
 'shared_mutable_children': ('class Box:\n'
                             ' def __init__(self):self.data=[[0]]*2\n'
                             'b=Box()\n'
                             'row=b.data[0]\n'
                             'row.append(3)\n'
                             'print(b.data[1])\n'
                             'b.data[0]=[7]\n'
                             'print(row,b.data[0],b.data[1])\n',
                             ['']),
 'index_callback_reentry': ('class Box:\n'
                            ' def __init__(self):self.data=[10,20]\n'
                            ' def index(self):\n'
                            '  self.data[0]+=1\n'
                            '  print("index")\n'
                            '  return 0\n'
                            ' def read(self):return self.data[self.index()]\n'
                            'b=Box()\n'
                            'print(b.read(),b.data[0])\n',
                            ['']),
 'augmented_rhs_reentry': ('class Box:\n'
                           ' def __init__(self):self.data=[10,20]\n'
                           ' def rhs(self):\n'
                           '  self.data[0]=50\n'
                           '  print("rhs")\n'
                           '  return 3\n'
                           ' def run(self):self.data[0]+=self.rhs()\n'
                           'b=Box()\n'
                           'b.run()\n'
                           'print(b.data[0])\n',
                           ['']),
 'assignment_rhs_target_order': ('class Box:\n'
                                 ' def __init__(self):self.data=[1,2]\n'
                                 ' def rhs(self):\n'
                                 '  print("rhs")\n'
                                 '  self.data[0]=7\n'
                                 '  return 9\n'
                                 ' def index(self):\n'
                                 '  print("index",self.data[0])\n'
                                 '  return 1\n'
                                 ' def run(self):self.data[self.index()]=self.rhs()\n'
                                 'b=Box()\n'
                                 'b.run()\n'
                                 'print(b.data[0],b.data[1])\n',
                                 ['']),
 'owner_name_rebound_during_index': ('class Box:\n'
                                     ' def __init__(self,x):self.data=[x]\n'
                                     'current=Box(1)\n'
                                     'def index():\n'
                                     ' global current\n'
                                     ' current=Box(9)\n'
                                     ' return 0\n'
                                     'print(current.data[index()])\n'
                                     'print(current.data[0])\n',
                                     ['']),
 'missing_field_before_index': ('class Box:\n'
                                ' def __init__(self,ready):\n'
                                '  if ready:self.data=[7]\n'
                                'def index():\n'
                                ' print("index")\n'
                                ' return 0\n'
                                'b=Box(int(input()))\n'
                                'print(b.data[index()])\n',
                                ['0\n', '1\n']),
 'empty_negative_and_bounds': ('class Box:\n'
                               ' def __init__(self,n):self.data=[5]*n\n'
                               'n,i=map(int,input().split())\n'
                               'b=Box(n)\n'
                               'print(len(b.data))\n'
                               'print(b.data[i])\n',
                               ['0 0\n', '2 -1\n', '2 -3\n']),
 'explicit_initializer_reentry_shared': ('class Box:\n'
                                         ' def __init__(self,x):self.data=[x]*x\n'
                                         'b=Box(2)\n'
                                         'def index():\n'
                                         ' b.__init__(4)\n'
                                         ' return 0\n'
                                         'print(b.data[index()],b.data[0])\n',
                                         ['']),
 'aliased_initializer_reentry_shared': ('class Box:\n'
                                        ' def __init__(self,x):self.data=[x]*x\n'
                                        'b=Box(2)\n'
                                        'reset=Box.__init__\n'
                                        'def index():\n'
                                        ' reset(b,4)\n'
                                        ' return 0\n'
                                        'print(b.data[index()],b.data[0])\n',
                                        ['']),
 'field_replacement_during_index_shared': ('class Box:\n'
                                           ' def __init__(self):self.data=[1,2]\n'
                                           'b=Box()\n'
                                           'def index():\n'
                                           ' b.data=[9,8]\n'
                                           ' return 0\n'
                                           'print(b.data[index()],b.data[0])\n',
                                           ['']),
 'field_alias_escape_shared': ('class Box:\n'
                               ' def __init__(self):self.data=[1,2]\n'
                               'b=Box()\n'
                               'alias=b.data\n'
                               'alias[0]=7\n'
                               'b.data=[9,8]\n'
                               'print(alias[0],b.data[0])\n',
                               ['']),
 'constructor_shared_argument': ('class Box:\n'
                                 ' def __init__(self,data):self.data=data\n'
                                 'source=[1,2]\n'
                                 'b=Box(source)\n'
                                 'source[0]=7\n'
                                 'print(b.data[0])\n'
                                 'b.data[1]=9\n'
                                 'print(source)\n',
                                 ['']),
 'initializer_self_rebind_shared': ('saved=None\n'
                                    'class Box:\n'
                                    ' def __init__(self,x):\n'
                                    '  global saved\n'
                                    '  if saved is None:saved=self\n'
                                    '  else:self=saved\n'
                                    '  self.data=[x]\n'
                                    'a=Box(1)\n'
                                    'def index():\n'
                                    ' Box(9)\n'
                                    ' return 0\n'
                                    'print(a.data[index()],a.data[0])\n',
                                    ['']),
 'partial_target_updates': ('class Box:\n'
                            ' def __init__(self):self.data=[1,2]\n'
                            'class Guard:\n'
                            ' def __enter__(self):return None\n'
                            ' def __exit__(self,a,b,c):\n'
                            '  print(holder.data[0])\n'
                            '  return True\n'
                            'holder=Box()\n'
                            'with Guard():holder.data[0],holder.data[4]=7,9\n'
                            'print(holder.data[0],holder.data[1])\n',
                            [''])}

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeOwnedClassListTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_existing_unbound_initializer_metadata_diagnostic(self):
        for integer in ("i64","i128","bigint"):
            result=transpile(CASES["aliased_initializer_reentry_shared"][0],TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertIn("Box.__init__",str(result.diagnostics))
            self.assertIn("metadata descriptor",str(result.diagnostics))

    def generated(self,name):
        result=transpile(CASES[name][0],TranspileOptions(license="none"))
        self.assertTrue(result.success,result.diagnostics)
        return result.rust_source

    def test_storage_is_vec_and_generic_field_getter_is_absent(self):
        rust=self.generated("fixed_field_alias_object")
        self.assertIn("field_0:Option<Vec<NativeInt>>",rust)
        self.assertIn("class_owned_field_0_0_get",rust)
        self.assertNotIn("fn class_get_0_0(",rust)

    def test_tuple_elements_keep_heterogeneous_leaf_types(self):
        rust=self.generated("tuple_elements")
        self.assertIn("field_0:Option<Vec<(NativeInt,NativeText)>>",rust)

    def test_finite_union_elements_keep_the_existing_carrier(self):
        rust=self.generated("finite_union_elements")
        self.assertRegex(rust,r"field_0:Option<Vec<[^>]*[Uu]nion")

    def test_shared_children_remain_reference_handles(self):
        rust=self.generated("shared_mutable_children")
        self.assertIn("field_0:Option<Vec<ClassList<NativeInt>>>",rust)

    def test_escaping_or_replaced_fields_keep_shared_storage(self):
        for name in ("field_alias_escape_shared","field_replacement_during_index_shared","constructor_shared_argument","initializer_self_rebind_shared","explicit_initializer_reentry_shared"):
            with self.subTest(name=name):
                rust=self.generated(name)
                self.assertNotIn("field_0:Option<Vec<",rust)
                self.assertIn("fn class_get_0_0(",rust)

    def test_conditional_initialization_keeps_presence_check_before_index(self):
        rust=self.generated("missing_field_before_index")
        self.assertIn("class_owned_field_0_0_ensure",rust)
        self.assertIn("field_0:Option<Vec<NativeInt>>",rust)


def install(name):
    def test(self):self.exercise(*CASES[name])
    test.__name__="test_"+name
    setattr(NativeOwnedClassListTests,test.__name__,test)
for name in CASES:
    if name!="aliased_initializer_reentry_shared":install(name)
