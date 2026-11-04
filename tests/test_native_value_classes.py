"""Closed Copy-field value layouts preserve publication and source semantics."""
import shutil
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_lambda_callbacks as helpers


CASES = {'main_readonly_values_in_containers_0': ('class Amount:\n'
                                          ' def __init__(self,value=0):self.value=value\n'
                                          ' def read(self):return self.value\n'
                                          ' def __add__(self,other):return '
                                          'Amount(self.value+other.value)\n'
                                          ' def __mul__(self,other):return '
                                          'Amount(self.value*other.value)\n'
                                          'rows=[(Amount(i),i+1) for i in range(7)]\n'
                                          'total=Amount()\n'
                                          'for value,weight in rows:\n'
                                          ' total=total+value*Amount(weight)\n'
                                          'print(total.read(),rows[3][0].read())\n',
                                          ('',)),
 'main_alias_after_publication_mutates_0': ('class Token:\n'
                                            ' def __init__(self,value=0):self.value=value\n'
                                            ' def read(self):return self.value\n'
                                            'a=Token(3)\n'
                                            'b=a\n'
                                            'a.value=19\n'
                                            'print(a.read(),b.read())\n',
                                            ('',)),
 'main_constructor_self_published_0': ('published=[]\n'
                                       'class Token:\n'
                                       ' def __init__(self,value):\n'
                                       '  published.append(self)\n'
                                       '  self.value=value\n'
                                       'item=Token(17)\n'
                                       'print(item.value,published[0].value)\n',
                                       ('',)),
 'main_constructor_self_readonly_method_0': ('class Token:\n'
                                             ' def __init__(self,value):\n'
                                             '  self.value=value\n'
                                             '  self.value=self.read()+1\n'
                                             ' def read(self):return self.value\n'
                                             'print(Token(3).read())\n',
                                             ('',)),
 'main_classmethod_fresh_factory_0': ('class Token:\n'
                                      ' def __init__(self,value=0):self.value=value\n'
                                      ' @classmethod\n'
                                      ' def make(cls,value):\n'
                                      '  result=cls()\n'
                                      '  result.value=value\n'
                                      '  return result\n'
                                      'print(Token.make(13).value)\n',
                                      ('',)),
 'main_source_is_observer_0': ('class Token:\n'
                               ' def __init__(self,value=0):self.value=value\n'
                               ' def read(self):return self.value\n'
                               'a=Token(3)\n'
                               'b=a\n'
                               'c=Token(3)\n'
                               'print(a is b,a is c)\n',
                               ('',)),
 'main_source_id_observer_0': ('class Token:\n'
                               ' def __init__(self,value=0):self.value=value\n'
                               ' def read(self):return self.value\n'
                               'a=Token(3)\n'
                               'b=a\n'
                               'c=Token(3)\n'
                               'print(id(a)==id(b),id(a)!=id(c))\n',
                               ('',)),
 'main_instance_representation_observer_0': ('class Token:\n'
                                             ' def __init__(self,value=0):self.value=value\n'
                                             ' def read(self):return self.value\n'
                                             'a=Token(3)\n'
                                             'print(str(a).startswith("<__main__.Token object at '
                                             '0x"))\n',
                                             ('',)),
 'main_container_representation_observer_0': ('class Token:\n'
                                              ' def __init__(self,value=0):self.value=value\n'
                                              ' def read(self):return self.value\n'
                                              'a=Token(3)\n'
                                              'print(str([a,a]).count("Token object at"))\n',
                                              ('',)),
 'main_container_implicit_identity_0': ('class Token:\n'
                                        ' def __init__(self,value=0):self.value=value\n'
                                        ' def read(self):return self.value\n'
                                        'a=Token(3)\n'
                                        'b=Token(3)\n'
                                        'print([a]==[a],[a]==[b],b in [a],a in [a])\n',
                                        ('',)),
 'main_escaping_bound_method_0': ('class Token:\n'
                                  ' def __init__(self,value=0):self.value=value\n'
                                  ' def read(self):return self.value\n'
                                  'a=Token(3)\n'
                                  'read=a.read\n'
                                  'print(read(),read==a.read)\n',
                                  ('',)),
 'main_external_function_mutates_published_0': ('class Token:\n'
                                                ' def __init__(self,value=0):self.value=value\n'
                                                ' def read(self):return self.value\n'
                                                'def mutate(value):value.value+=7\n'
                                                'a=Token(3)\n'
                                                'b=a\n'
                                                'mutate(a)\n'
                                                'print(a.value,b.value)\n',
                                                ('',)),
 'main_fresh_loop_and_old_published_alias_0': ('class Token:\n'
                                               ' def __init__(self,value=0):self.value=value\n'
                                               ' def read(self):return self.value\n'
                                               'rows=[]\n'
                                               'previous=Token(0)\n'
                                               'for i in range(4):\n'
                                               ' current=Token(i)\n'
                                               ' previous.value+=10\n'
                                               ' rows.append(current)\n'
                                               ' previous=current\n'
                                               'print([row.value for row in rows])\n',
                                               ('',)),
 'main_none_and_absent_field_0': ('class Token:\n'
                                  ' def __init__(self):self.value=None\n'
                                  'item=Token()\n'
                                  'print(item.value)\n'
                                  'del item.value\n'
                                  'print(item.value)\n',
                                  ('',)),
 'main_conditional_partial_constructor_0': ('class Token:\n'
                                            ' def __init__(self,enabled):\n'
                                            '  if enabled:self.value=17\n'
                                            'item=Token(int(input())!=0)\n'
                                            'print(item.value)\n',
                                            ('0\n', '1\n')),
 'main_explicit_initializer_after_publication_0': ('class Token:\n'
                                                   ' def __init__(self,value=0):self.value=value\n'
                                                   ' def read(self):return self.value\n'
                                                   'a=Token(3)\n'
                                                   'b=a\n'
                                                   'a.__init__(19)\n'
                                                   'print(a.value,b.value)\n',
                                                   ('',)),
 'main_immutable_alias_reads_only_0': ('class Token:\n'
                                       ' def __init__(self,value=0):self.value=value\n'
                                       ' def read(self):return self.value\n'
                                       'a=Token(3)\n'
                                       'b=a\n'
                                       'print(a.read()+b.read())\n',
                                       ('',)),
 'factory_free_factory_fresh_scalar_0': ('class Token:\n'
                                         ' def __init__(self,value=0):self.value=value\n'
                                         ' def read(self):return self.value\n'
                                         'def make(value):\n'
                                         ' result=Token()\n'
                                         ' result.value=value\n'
                                         ' return result\n'
                                         'rows=[make(i*3)for i in range(5)]\n'
                                         'print(sum(row.read()for row in rows))\n',
                                         ('',)),
 'factory_free_factory_alias_before_write_0': ('class Token:\n'
                                               ' def __init__(self,value=0):self.value=value\n'
                                               ' def read(self):return self.value\n'
                                               'def make(value):\n'
                                               ' result=Token()\n'
                                               ' alias=result\n'
                                               ' alias.value=value\n'
                                               ' return result\n'
                                               'print(make(19).value)\n',
                                               ('',)),
 'factory_free_factory_container_alias_before_write_0': ('class Token:\n'
                                                         ' def '
                                                         '__init__(self,value=0):self.value=value\n'
                                                         ' def read(self):return self.value\n'
                                                         'def make(value):\n'
                                                         ' result=Token()\n'
                                                         ' aliases=(result,)\n'
                                                         ' result.value=value\n'
                                                         ' return aliases[0]\n'
                                                         'print(make(19).value)\n',
                                                         ('',)),
 'factory_free_factory_publication_before_write_0': ('published=[]\n'
                                                     'class Token:\n'
                                                     ' def '
                                                     '__init__(self,value=0):self.value=value\n'
                                                     ' def read(self):return self.value\n'
                                                     'def make(value):\n'
                                                     ' result=Token()\n'
                                                     ' published.append(result)\n'
                                                     ' result.value=value\n'
                                                     ' return result\n'
                                                     'item=make(11)\n'
                                                     'print(item.value,published[0].value)\n',
                                                     ('',)),
 'factory_free_factory_conditional_fields_0': ('class Token:\n'
                                               ' def __init__(self,value=0):self.value=value\n'
                                               ' def read(self):return self.value\n'
                                               'def make(value):\n'
                                               ' result=Token()\n'
                                               ' if value<0:result.value=-value\n'
                                               ' else:result.value=value+1\n'
                                               ' return result\n'
                                               'print(make(-3).value,make(4).value)\n',
                                               ('',)),
 'factory_free_factory_fresh_branch_merge_0': ('class Token:\n'
                                               ' def __init__(self,value=0):self.value=value\n'
                                               ' def read(self):return self.value\n'
                                               'def make(value):\n'
                                               ' if value<0:result=Token(-value)\n'
                                               ' else:result=Token(value)\n'
                                               ' result.value+=2\n'
                                               ' return result\n'
                                               'print(make(-3).value,make(4).value)\n',
                                               ('',)),
 'factory_free_factory_fresh_loop_0': ('class Token:\n'
                                       ' def __init__(self,value=0):self.value=value\n'
                                       ' def read(self):return self.value\n'
                                       'def make(n):\n'
                                       ' results=[]\n'
                                       ' for i in range(n):\n'
                                       '  result=Token()\n'
                                       '  result.value=i*2\n'
                                       '  results.append(result)\n'
                                       ' return results\n'
                                       'print([item.value for item in make(5)])\n',
                                       ('',)),
 'factory_free_factory_old_alias_same_allocation_site_0': ('class Token:\n'
                                                           ' def '
                                                           '__init__(self,value=0):self.value=value\n'
                                                           ' def read(self):return self.value\n'
                                                           'def make(n):\n'
                                                           ' results=[]\n'
                                                           ' previous=Token()\n'
                                                           ' for i in range(n):\n'
                                                           '  result=Token()\n'
                                                           '  previous.value=i+10\n'
                                                           '  result.value=i*2\n'
                                                           '  results.append(result)\n'
                                                           '  previous=result\n'
                                                           ' return results\n'
                                                           'print([item.value for item in '
                                                           'make(5)])\n',
                                                           ('',)),
 'factory_free_factory_delete_before_publication_0': ('class Token:\n'
                                                      ' def '
                                                      '__init__(self,value=0):self.value=value\n'
                                                      ' def read(self):return self.value\n'
                                                      'def make(value):\n'
                                                      ' result=Token(value)\n'
                                                      ' del result.value\n'
                                                      ' return result\n'
                                                      'item=make(11)\n'
                                                      'print(item.value)\n',
                                                      ('',)),
 'factory_free_factory_read_only_call_before_store_0': ('class Token:\n'
                                                        ' def '
                                                        '__init__(self,value=0):self.value=value\n'
                                                        ' def read(self):return self.value\n'
                                                        'def make(value):\n'
                                                        ' result=Token(value)\n'
                                                        ' initial=result.read()\n'
                                                        ' result.value=initial+7\n'
                                                        ' return result\n'
                                                        'print(make(3).value)\n',
                                                        ('',)),
 'factory_free_factory_capture_before_write_0': ('class Token:\n'
                                                 ' def __init__(self,value=0):self.value=value\n'
                                                 ' def read(self):return self.value\n'
                                                 'def make(value):\n'
                                                 ' result=Token()\n'
                                                 ' read=lambda:result.value\n'
                                                 ' result.value=value\n'
                                                 ' return result,read\n'
                                                 'item,read=make(13)\n'
                                                 'print(item.value,read())\n',
                                                 ('',)),
 'factory_free_factory_call_publishes_before_write_0': ('published=[]\n'
                                                        'class Token:\n'
                                                        ' def '
                                                        '__init__(self,value=0):self.value=value\n'
                                                        ' def read(self):return self.value\n'
                                                        'def publish(item):published.append(item)\n'
                                                        'def make(value):\n'
                                                        ' result=Token()\n'
                                                        ' publish(result)\n'
                                                        ' result.value=value\n'
                                                        ' return result\n'
                                                        'item=make(11)\n'
                                                        'print(item.value,published[0].value)\n',
                                                        ('',)),
 'factory_free_factory_exception_before_publication_0': ('class Token:\n'
                                                         ' def '
                                                         '__init__(self,value=0):self.value=value\n'
                                                         ' def read(self):return self.value\n'
                                                         'def make(value):\n'
                                                         ' result=Token(17)\n'
                                                         ' result.value=1//value\n'
                                                         ' return result\n'
                                                         'print(make(int(input())).value)\n',
                                                         ('0\n', '2\n')),
 'factory_isinstance_source_nominal_0': ('class Token:\n'
                                         ' def __init__(self,value=0):self.value=value\n'
                                         ' def read(self):return self.value\n'
                                         'item=Token(3)\n'
                                         'print(isinstance(item,Token),isinstance(3,Token))\n',
                                         ('',)),
 'shadow_shadowed_constructor_returns_existing': ('class C:\n'
                                                  ' def __init__(self,value):self.value=value\n'
                                                  '\n'
                                                  'def keep(value):return value\n'
                                                  '\n'
                                                  'def mutate(existing):\n'
                                                  ' C=keep\n'
                                                  ' item=C(existing)\n'
                                                  ' item.value=99\n'
                                                  '\n'
                                                  'def main():\n'
                                                  ' original=C(1)\n'
                                                  ' mutate(original)\n'
                                                  ' print(original.value)\n'
                                                  '\n'
                                                  'main()\n',
                                                  ('',)),
 'defaults_def_keyword_default': ('class Token:\n'
                                  '    def __init__(self, value):\n'
                                  '        self.value = value\n'
                                  '\n'
                                  'def produce():\n'
                                  '    item = Token(3)\n'
                                  '    def read(*, saved=item):\n'
                                  '        return saved.value\n'
                                  '    item.value = 17\n'
                                  '    return read()\n'
                                  '\n'
                                  'print(produce())\n',
                                  ('',)),
 'defaults_lambda_keyword_default': ('class Token:\n'
                                     '    def __init__(self, value):\n'
                                     '        self.value = value\n'
                                     '\n'
                                     'def produce():\n'
                                     '    item = Token(3)\n'
                                     '    read = lambda *, saved=item: saved.value\n'
                                     '    item.value = 17\n'
                                     '    return read()\n'
                                     '\n'
                                     'print(produce())\n',
                                     ('',)),
 'defaults_def_positional_default': ('class Token:\n'
                                     '    def __init__(self, value):\n'
                                     '        self.value = value\n'
                                     '\n'
                                     'def produce():\n'
                                     '    item = Token(3)\n'
                                     '    def read(saved=item):\n'
                                     '        return saved.value\n'
                                     '    item.value = 17\n'
                                     '    return read()\n'
                                     '\n'
                                     'print(produce())\n',
                                     ('',))}


CASES.update({'mapped_identity': ('class Token:\n'
                     '    def __init__(self, value):\n'
                     '        self.value=value\n'
                     '\n'
                     'a=Token(3)\n'
                     'others=[a,a,Token(4)]\n'
                     'markers=list(map(id,others))\n'
                     'print(markers[0]==markers[1],markers[0]==markers[2])\n',
                     ('',)),
 'mapped_representation': ('class Token:\n'
                           '    def __init__(self, value):\n'
                           '        self.value=value\n'
                           '\n'
                           'a=Token(3)\n'
                           'texts=list(map(str,[a,a]))\n'
                           'print(texts[0]==texts[1],texts[0].startswith("<__main__.Token object '
                           'at 0x"))\n',
                           ('',))})


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeValueClassTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise

    def test_proved_fresh_factory_uses_values_in_fixed_width_modes(self):
        source = CASES["factory_free_factory_fresh_scalar_0"][0]
        for mode in ("i64", "i128"):
            result = transpile(source, TranspileOptions(integer=mode))
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("type ClassHandle_0=ClassData_0;", result.rust_source)
            self.assertIn("class_argument_0:&ClassHandle_0", result.rust_source)
        result = transpile(source, TranspileOptions(integer="bigint"))
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("type ClassHandle_0=Rc<RefCell<ClassData_0>>", result.rust_source)

    def test_unproved_alias_mutation_keeps_reference_identity(self):
        source = CASES["factory_free_factory_alias_before_write_0"][0]
        for mode in ("i64", "i128"):
            result = transpile(source, TranspileOptions(integer=mode))
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("type ClassHandle_0=Rc<ClassData_0>", result.rust_source)

    def test_main_readonly_values_in_containers_0(self):
        self.exercise(*CASES['main_readonly_values_in_containers_0'])

    def test_main_alias_after_publication_mutates_0(self):
        self.exercise(*CASES['main_alias_after_publication_mutates_0'])

    def test_main_constructor_self_published_0(self):
        self.exercise(*CASES['main_constructor_self_published_0'])

    def test_main_constructor_self_readonly_method_0(self):
        self.exercise(*CASES['main_constructor_self_readonly_method_0'])

    def test_main_classmethod_fresh_factory_0(self):
        self.exercise(*CASES['main_classmethod_fresh_factory_0'])

    def test_main_source_is_observer_0(self):
        self.exercise(*CASES['main_source_is_observer_0'])

    def test_main_source_id_observer_0(self):
        self.exercise(*CASES['main_source_id_observer_0'])

    def test_main_instance_representation_observer_0(self):
        self.exercise(*CASES['main_instance_representation_observer_0'])

    def test_main_container_representation_observer_0(self):
        self.exercise(*CASES['main_container_representation_observer_0'])

    def test_main_container_implicit_identity_0(self):
        self.exercise(*CASES['main_container_implicit_identity_0'])

    def test_main_escaping_bound_method_0(self):
        self.exercise(*CASES['main_escaping_bound_method_0'])

    def test_main_external_function_mutates_published_0(self):
        self.exercise(*CASES['main_external_function_mutates_published_0'])

    def test_main_fresh_loop_and_old_published_alias_0(self):
        self.exercise(*CASES['main_fresh_loop_and_old_published_alias_0'])

    def test_main_none_and_absent_field_0(self):
        self.exercise(*CASES['main_none_and_absent_field_0'])

    def test_main_conditional_partial_constructor_0(self):
        self.exercise(*CASES['main_conditional_partial_constructor_0'])

    def test_main_explicit_initializer_after_publication_0(self):
        self.exercise(*CASES['main_explicit_initializer_after_publication_0'])

    def test_main_immutable_alias_reads_only_0(self):
        self.exercise(*CASES['main_immutable_alias_reads_only_0'])

    def test_factory_free_factory_fresh_scalar_0(self):
        self.exercise(*CASES['factory_free_factory_fresh_scalar_0'])

    def test_factory_free_factory_alias_before_write_0(self):
        self.exercise(*CASES['factory_free_factory_alias_before_write_0'])

    def test_factory_free_factory_container_alias_before_write_0(self):
        self.exercise(*CASES['factory_free_factory_container_alias_before_write_0'])

    def test_factory_free_factory_publication_before_write_0(self):
        self.exercise(*CASES['factory_free_factory_publication_before_write_0'])

    def test_factory_free_factory_conditional_fields_0(self):
        self.exercise(*CASES['factory_free_factory_conditional_fields_0'])

    def test_factory_free_factory_fresh_branch_merge_0(self):
        self.exercise(*CASES['factory_free_factory_fresh_branch_merge_0'])

    def test_factory_free_factory_fresh_loop_0(self):
        self.exercise(*CASES['factory_free_factory_fresh_loop_0'])

    def test_factory_free_factory_old_alias_same_allocation_site_0(self):
        self.exercise(*CASES['factory_free_factory_old_alias_same_allocation_site_0'])

    def test_factory_free_factory_delete_before_publication_0(self):
        self.exercise(*CASES['factory_free_factory_delete_before_publication_0'])

    def test_factory_free_factory_read_only_call_before_store_0(self):
        self.exercise(*CASES['factory_free_factory_read_only_call_before_store_0'])

    def test_factory_free_factory_capture_before_write_0(self):
        self.exercise(*CASES['factory_free_factory_capture_before_write_0'])

    def test_factory_free_factory_call_publishes_before_write_0(self):
        self.exercise(*CASES['factory_free_factory_call_publishes_before_write_0'])

    def test_factory_free_factory_exception_before_publication_0(self):
        self.exercise(*CASES['factory_free_factory_exception_before_publication_0'])

    def test_factory_isinstance_source_nominal_0(self):
        self.exercise(*CASES['factory_isinstance_source_nominal_0'])

    def test_shadow_shadowed_constructor_returns_existing(self):
        self.exercise(*CASES['shadow_shadowed_constructor_returns_existing'])

    def test_defaults_def_keyword_default(self):
        self.exercise(*CASES['defaults_def_keyword_default'])

    def test_defaults_lambda_keyword_default(self):
        self.exercise(*CASES['defaults_lambda_keyword_default'])

    def test_defaults_def_positional_default(self):
        self.exercise(*CASES['defaults_def_positional_default'])


    def test_indirect_builtin_observers_keep_reference_identity(self):
        for key in ("mapped_identity", "mapped_representation"):
            for mode in ("i64", "i128"):
                result = transpile(CASES[key][0], TranspileOptions(integer=mode))
                self.assertTrue(result.success, result.diagnostics)
                self.assertIn("type ClassHandle_0=Rc<ClassData_0>", result.rust_source)

    def test_mapped_identity(self):
        self.exercise(*CASES['mapped_identity'])

    def test_mapped_representation(self):
        self.exercise(*CASES['mapped_representation'])


if __name__ == "__main__":
    unittest.main()
