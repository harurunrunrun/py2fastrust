"""Generic scalar instance storage preserves aliases, errors and metadata."""
import shutil
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_lambda_callbacks as helpers


CASES = {'alias_and_receiver_rebinding': ('class Number:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  ' def advance(self,step):self.value+=step\n'
                                  'a=Number(3)\n'
                                  'b=a\n'
                                  'a.advance(4)\n'
                                  'a=Number(19)\n'
                                  'b.value+=2\n'
                                  'print(a.value,b.value,a is b,b is b)\n',
                                  ('',)),
 'independent_scalar_fields': ('class State:\n'
                               ' def __init__(self):\n'
                               '  self.count=3\n'
                               '  self.flag=True\n'
                               '  self.weight=1.25\n'
                               '  self.empty=None\n'
                               ' def update(self):\n'
                               '  self.count+=4\n'
                               '  self.flag=not self.flag\n'
                               '  self.weight*=2.0\n'
                               's=State()\n'
                               's.update()\n'
                               'print(s.count,s.flag,s.weight,s.empty)\n',
                               ('',)),
 'partial_constructor_missing_field': ('class Partial:\n'
                                       ' def __init__(self,enabled):\n'
                                       '  self.seed=2\n'
                                       '  if enabled:self.value=7\n'
                                       'p=Partial(int(input())!=0)\n'
                                       'print(p.seed)\n'
                                       'print(p.value)\n',
                                       ('0\n', '1\n')),
 'delete_and_reassign': ('class Item:\n'
                         ' def __init__(self):self.value=11\n'
                         'a=Item()\n'
                         'b=a\n'
                         'del a.value\n'
                         'b.value=19\n'
                         'print(a.value,b.value)\n'
                         'del b.value\n'
                         'print(a.value)\n',
                         ('',)),
 'delete_twice': ('class Item:\n'
                  ' def __init__(self):self.value=11\n'
                  'a=Item()\n'
                  'del a.value\n'
                  'del a.value\n',
                  ('',)),
 'none_value_distinct_from_absent': ('class Item:\n'
                                     ' def __init__(self):self.value=None\n'
                                     'a=Item()\n'
                                     'print(a.value)\n'
                                     'del a.value\n'
                                     'print(a.value)\n',
                                     ('',)),
 'finite_owner_and_none': ('class First:\n'
                           ' def __init__(self):self.value=3\n'
                           'class Second:\n'
                           ' def __init__(self):self.value=7\n'
                           'choice=int(input())\n'
                           'if choice==0:a=First()\n'
                           'elif choice==1:a=Second()\n'
                           'else:a=None\n'
                           'a.value=13\n'
                           'print(a.value)\n',
                           ('0\n', '1\n', '2\n')),
 'class_namespace_shadow_and_delete': ('class Item:\n'
                                       ' value=7\n'
                                       ' def __init__(self,enabled):\n'
                                       '  if enabled:self.value=13\n'
                                       'a=Item(int(input()))\n'
                                       'print(a.value)\n'
                                       'a.value=19\n'
                                       'print(a.value,Item.value)\n'
                                       'del a.value\n'
                                       'print(a.value)\n'
                                       'Item.value=23\n'
                                       'print(a.value)\n',
                                       ('0\n', '1\n')),
 'heterogeneous_field_keeps_fallback': ('class Item:\n'
                                        ' def __init__(self):self.value=3\n'
                                        'a=Item()\n'
                                        'print(a.value)\n'
                                        'a.value="text"\n'
                                        'print(a.value)\n',
                                        ('',)),
 'container_field_keeps_fallback': ('class Item:\n'
                                    ' def __init__(self):\n'
                                    '  self.values=[2,3]\n'
                                    '  self.count=1\n'
                                    'a=Item()\n'
                                    'b=a\n'
                                    'b.values.append(5)\n'
                                    'a.count+=1\n'
                                    'print(a.values,b.count)\n',
                                    ('',)),
 'bool_to_int_field_keeps_fallback': ('class Item:\n'
                                      ' def __init__(self):self.value=True\n'
                                      'a=Item()\n'
                                      'print(a.value)\n'
                                      'a.value=7\n'
                                      'print(a.value)\n',
                                      ('',)),
 'gc_cycle_keeps_fallback': ('class Item:\n'
                             ' def __init__(self):\n'
                             '  self.value=3\n'
                             '  self.link=None\n'
                             'a=Item()\n'
                             'b=Item()\n'
                             'a.link=b\n'
                             'b.link=a\n'
                             'a.value+=2\n'
                             'print(a.value,b.value,a.link is b,b.link is a)\n',
                             ('',)),
 'augassign_rhs_observes_original': ('class Item:\n'
                                     ' def __init__(self):self.value=7\n'
                                     'def change(item):\n'
                                     ' print(item.value)\n'
                                     ' item.value=19\n'
                                     ' return 3\n'
                                     'a=Item()\n'
                                     'a.value+=change(a)\n'
                                     'print(a.value)\n',
                                     ('',)),
 'private_scalar_names': ('class Item:\n'
                          ' def __init__(self):self.__value=3\n'
                          ' def add(self,delta):self.__value+=delta\n'
                          ' def read(self):return self.__value\n'
                          'a=Item()\n'
                          'a.add(5)\n'
                          'print(a.read())\n',
                          ('',))}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeCopyScalarFieldTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise

    def test_fixed_width_fields_avoid_object_wide_borrow_flag(self):
        source = CASES["alias_and_receiver_rebinding"][0]
        for mode in ("i64", "i128"):
            result = transpile(source, TranspileOptions(integer=mode))
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("type ClassHandle_0=Rc<ClassData_0>", result.rust_source)
            self.assertIn("std::cell::Cell<Option<NativeInt>>", result.rust_source)
        result = transpile(source, TranspileOptions(integer="bigint"))
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("type ClassHandle_0=Rc<RefCell<ClassData_0>>", result.rust_source)

    def test_alias_and_receiver_rebinding(self):
        self.exercise(*CASES['alias_and_receiver_rebinding'])

    def test_independent_scalar_fields(self):
        self.exercise(*CASES['independent_scalar_fields'])

    def test_partial_constructor_missing_field(self):
        self.exercise(*CASES['partial_constructor_missing_field'])

    def test_delete_and_reassign(self):
        self.exercise(*CASES['delete_and_reassign'])

    def test_delete_twice(self):
        self.exercise(*CASES['delete_twice'])

    def test_none_value_distinct_from_absent(self):
        self.exercise(*CASES['none_value_distinct_from_absent'])

    def test_finite_owner_and_none(self):
        self.exercise(*CASES['finite_owner_and_none'])

    def test_class_namespace_shadow_and_delete(self):
        self.exercise(*CASES['class_namespace_shadow_and_delete'])

    def test_heterogeneous_field_keeps_fallback(self):
        self.exercise(*CASES['heterogeneous_field_keeps_fallback'])

    def test_container_field_keeps_fallback(self):
        self.exercise(*CASES['container_field_keeps_fallback'])

    def test_bool_to_int_field_keeps_fallback(self):
        self.exercise(*CASES['bool_to_int_field_keeps_fallback'])

    def test_gc_cycle_keeps_fallback(self):
        self.exercise(*CASES['gc_cycle_keeps_fallback'])

    def test_augassign_rhs_observes_original(self):
        self.exercise(*CASES['augassign_rhs_observes_original'])

    def test_private_scalar_names(self):
        self.exercise(*CASES['private_scalar_names'])


if __name__ == "__main__":
    unittest.main()
