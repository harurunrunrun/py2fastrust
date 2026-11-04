"""Class-reference borrows retain namespace reads and captured call effects."""
import re
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_lambda_callbacks as helpers
import test_native_value_parameter_abi as abi

CASES={'argument_effect_before_class_read': ['class Sample:\n'
                                       ' values=[3,7]\n'
                                       ' def __init__(self,n):self.n=n\n'
                                       ' @classmethod\n'
                                       ' def lookup(cls,index):return '
                                       'cls.values[index]\n'
                                       'sample=Sample(5)\n'
                                       'def change():\n'
                                       ' Sample.values.append(11)\n'
                                       ' return -1\n'
                                       'print(Sample.lookup(change()),sample.n)\n',
                                       ['']],
 'class_reference_alias': ['class Sample:\n'
                           ' values=[3,7]\n'
                           ' def __init__(self,n):self.n=n\n'
                           ' @classmethod\n'
                           ' def lookup(cls,index):return cls.values[index]\n'
                           'sample=Sample(5)\n'
                           'def read(owner):\n'
                           ' alias=owner\n'
                           ' return alias.values[0]\n'
                           'print(read(Sample),sample.n)\n',
                           ['']],
 'class_reference_capture': ['class Sample:\n'
                             ' values=[3,7]\n'
                             ' def __init__(self,n):self.n=n\n'
                             ' @classmethod\n'
                             ' def lookup(cls,index):return cls.values[index]\n'
                             'sample=Sample(5)\n'
                             'def make(owner):\n'
                             ' def read():return owner.values[0]\n'
                             ' return read\n'
                             'read=make(Sample)\n'
                             'print(read(),sample.n)\n',
                             ['']],
 'class_reference_return': ['class Sample:\n'
                            ' values=[3,7]\n'
                            ' def __init__(self,n):self.n=n\n'
                            ' @classmethod\n'
                            ' def lookup(cls,index):return cls.values[index]\n'
                            'sample=Sample(5)\n'
                            'def same(owner):return owner\n'
                            'print(same(Sample).values[0],sample.n)\n',
                            ['']],
 'classmethod_list_field': ['class Sample:\n'
                            ' values=[3,7]\n'
                            ' def __init__(self,n):self.n=n\n'
                            ' @classmethod\n'
                            ' def lookup(cls,index):return cls.values[index]\n'
                            'sample=Sample(5)\n'
                            'print(sample.n,Sample.lookup(int(input())))\n',
                            ['0\n', '-1\n']],
 'default_class_argument': ['class Sample:\n'
                            ' values=[3,7]\n'
                            ' def __init__(self,n):self.n=n\n'
                            ' @classmethod\n'
                            ' def lookup(cls,index):return cls.values[index]\n'
                            'sample=Sample(5)\n'
                            'def read(owner=Sample):return owner.values[-1]\n'
                            'print(read(),sample.n)\n',
                            ['']],
 'index_failure_stops_next_argument': ['class Sample:\n'
                                       ' values=[3,7]\n'
                                       ' def __init__(self,n):self.n=n\n'
                                       ' @classmethod\n'
                                       ' def lookup(cls,index):return '
                                       'cls.values[index]\n'
                                       'sample=Sample(5)\n'
                                       'def mark():\n'
                                       " print('argument')\n"
                                       ' return 9\n'
                                       'print(Sample.lookup(7),mark())\n',
                                       ['']],
 'live_class_list_mutation': ['class Sample:\n'
                              ' values=[3,7]\n'
                              ' def __init__(self,n):self.n=n\n'
                              ' @classmethod\n'
                              ' def lookup(cls,index):return '
                              'cls.values[index]\n'
                              'sample=Sample(5)\n'
                              'Sample.values.append(9)\n'
                              'print(Sample.lookup(-1),sample.n)\n',
                              ['']],
 'missing_class_attribute': ['class Sample:\n'
                             ' def __init__(self,n):self.n=n\n'
                             ' @classmethod\n'
                             ' def read(cls):return cls.missing\n'
                             'sample=Sample(5)\n'
                             'print(sample.n)\n'
                             'print(Sample.read())\n',
                             ['']],
 'ordinary_class_argument': ['class Sample:\n'
                             ' values=[3,7]\n'
                             ' def __init__(self,n):self.n=n\n'
                             ' @classmethod\n'
                             ' def lookup(cls,index):return cls.values[index]\n'
                             'sample=Sample(5)\n'
                             'def read(owner):return owner.values[0]\n'
                             'print(read(Sample),sample.n)\n',
                             ['']],
 'parameter_rebinding': ['class Sample:\n'
                         ' values=[3,7]\n'
                         ' def __init__(self,n):self.n=n\n'
                         ' @classmethod\n'
                         ' def lookup(cls,index):return cls.values[index]\n'
                         'sample=Sample(5)\n'
                         'def read(owner):\n'
                         ' owner=Sample\n'
                         ' return owner.values[0]\n'
                         'print(read(Sample),sample.n)\n',
                         ['']],
 'stored_bound_classmethod': ['class Sample:\n'
                              ' values=[3,7]\n'
                              ' def __init__(self,n):self.n=n\n'
                              ' @classmethod\n'
                              ' def lookup(cls,index):return '
                              'cls.values[index]\n'
                              'sample=Sample(5)\n'
                              'read=Sample.lookup\n'
                              'print(read(1),Sample.lookup(0),sample.n)\n',
                              ['']]}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassReferenceExecution(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise


def install(name,source,inputs):
    def test(self):self.exercise(source,inputs)
    setattr(ClassReferenceExecution,'test_'+name,test)
for name,(source,inputs)in CASES.items():install(name,source,inputs)


class ClassReferenceProofs(unittest.TestCase):
    def code(self,name):
        result=transpile(CASES[name][0],TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        return result.rust_source

    def test_plain_class_data_reads_borrow_parameters(self):
        for name in ('classmethod_list_field','ordinary_class_argument','stored_bound_classmethod','default_class_argument'):
            self.assertRegex(self.code(name),r'class_argument_\d+:&ClassClassRef')

    def test_alias_capture_return_and_rebinding_keep_owned_parameters(self):
        for name in ('class_reference_alias','class_reference_capture','class_reference_return','parameter_rebinding'):
            self.assertNotRegex(self.code(name),r'class_argument_\d+:&ClassClassRef')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassReferenceABI(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    check=abi.NativeValueParameterABIContractTests.check

    @staticmethod
    def nominal(code):return code.replace('ClassHandle_0','ClassClassRef').replace('ClassData_0','ClassClassData')

    def test_drop_through_class_reference_alias_retains_owned_abi(self):
        self.check(self.nominal(abi.DROP),{(0,0):'ClassClassRef'},'drop 7\n7\n',True)

    def test_future_retains_owned_class_reference(self):
        self.check(self.nominal(abi.ASYNC),{(0,0):'ClassClassRef'},'',True)

    def test_address_taken_class_reader_keeps_its_abi(self):
        self.check(self.nominal(abi.POINTER),{(0,0):'ClassClassRef'},'7\n',True)

    def test_nested_class_argument_effect_order(self):
        self.check(self.nominal(abi.NESTED),{(0,0):'ClassClassRef',(1,0):'ClassClassRef'},'make 2\nmake 7\n9\n',False)
