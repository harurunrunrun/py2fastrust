"""Plain owned fields retain partial-construction errors and source order."""
import ast,shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_classes import Emitter
from tests import test_native_lambda_callbacks as helpers

SOURCES={'assignment_rhs_before_bad_index': ('def mark():\n'
                                     '    print("rhs")\n'
                                     '    return 19\n'
                                     'class Array:\n'
                                     '    def __init__(self):\n'
                                     '        self.size=2\n'
                                     '        self.data=[7,11]\n'
                                     '    def update(self,i):self.data[i]=mark()\n'
                                     '    def read(self,i):return self.data[i]+self.size\n'
                                     'def main():\n'
                                     '    a=Array()\n'
                                     '    i=int(input())\n'
                                     '    a.update(i)\n'
                                     '    print(a.read(i))\n'
                                     'main()\n',
                                     ['-1\n', '2\n']),
 'branch_scalar_assignment': ('class Array:\n'
                              '    def __init__(self,flag):\n'
                              '        self.data=[7,11]\n'
                              '        if flag:self.size=3\n'
                              '        else:self.size=5\n'
                              '    def read(self):return self.data[0]+self.size\n'
                              'def main():\n'
                              '    a=Array(int(input()))\n'
                              '    print(a.read())\n'
                              'main()\n',
                              ['0\n', '1\n']),
 'conditional_presence': ('class Array:\n'
                          '    def __init__(self,enabled):\n'
                          '        self.size=2\n'
                          '        if enabled:self.data=[8,13]\n'
                          '    def read(self):return self.data[-1]+self.size\n'
                          'def main():\n'
                          '    a=Array(int(input()))\n'
                          '    print(a.read())\n'
                          'main()\n',
                          ['0\n', '1\n']),
 'constructor_partial_failure': ('class Array:\n'
                                 '    def __init__(self,fail):\n'
                                 '        print("start")\n'
                                 '        self.size=2\n'
                                 '        self.data=[7,11]\n'
                                 '        if fail:raise ValueError("stopped")\n'
                                 '        print("ready")\n'
                                 '    def read(self):return self.data[-1]+self.size\n'
                                 'def main():\n'
                                 '    a=Array(int(input()))\n'
                                 '    print(a.read())\n'
                                 'main()\n',
                                 ['0\n', '1\n']),
 'early_method_read': ('class Array:\n'
                       '    def __init__(self,early):\n'
                       '        self.size=3\n'
                       '        if early:self.read()\n'
                       '        self.data=[21]\n'
                       '    def read(self):return self.data[-1]+self.size\n'
                       'def main():\n'
                       '    a=Array(int(input()))\n'
                       '    print(a.read())\n'
                       'main()\n',
                       ['0\n', '1\n']),
 'early_scalar_rhs': ('class Array:\n'
                      '    def __init__(self):\n'
                      '        self.data=[self.size]\n'
                      '        self.size=2\n'
                      '    def read(self):return self.data[0]+self.size\n'
                      'def main():\n'
                      '    a=Array()\n'
                      '    print(a.read())\n'
                      'main()\n',
                      ['']),
 'fill_method_after_store': ('class Array:\n'
                             '    def __init__(self,n):\n'
                             '        self.size=n\n'
                             '        self.data=[0]*n\n'
                             '        self.fill()\n'
                             '    def fill(self):\n'
                             '        for i in range(self.size):self.data[i]=i+1\n'
                             '    def read(self,i):return self.data[i]+self.size\n'
                             'def main():\n'
                             '    n,i=map(int,input().split())\n'
                             '    a=Array(n)\n'
                             '    print(a.read(i))\n'
                             'main()\n',
                             ['4 -1\n', '4 0\n', '0 0\n']),
 'helper_initializes_scalar': ('class Array:\n'
                               '    def __init__(self,n):self.setup(n)\n'
                               '    def setup(self,n):\n'
                               '        self.size=n\n'
                               '        self.data=[5]*n\n'
                               '    def read(self):return self.size+self.data[-1]\n'
                               'def main():\n'
                               '    a=Array(int(input()))\n'
                               '    print(a.read())\n'
                               'main()\n',
                               ['3\n', '0\n']),
 'zero_trip_scalar_assignment': ('class Array:\n'
                                 '    def __init__(self,n):\n'
                                 '        for i in range(n):self.size=i+1\n'
                                 '        self.data=[5]*n\n'
                                 '    def read(self):return self.size+len(self.data)\n'
                                 'def main():\n'
                                 '    a=Array(int(input()))\n'
                                 '    print(a.read())\n'
                                 'main()\n',
                                 ['0\n', '3\n'])}

SOURCES.update({'conditional_expression_early_read': ('class Array:\n'
                                       '    def __init__(self,flag):\n'
                                       '        self.data=[0]\n'
                                       '        value=0 if flag else self.size\n'
                                       '        self.size=9\n'
                                       '    def read(self):return self.data[0]+self.size\n'
                                       'def main():\n'
                                       '    a=Array(int(input()))\n'
                                       '    print(a.read())\n'
                                       'main()\n',
                                       ['0\n', '1\n']),
 'dictionary_pair_order': ('class Array:\n'
                           '    def __init__(self):\n'
                           '        self.data=[0]\n'
                           '        values={"first":self.size,self.setup():0}\n'
                           '        self.size=9\n'
                           '    def setup(self):\n'
                           '        print("late")\n'
                           '        self.size=3\n'
                           '        return "second"\n'
                           '    def read(self):return self.data[0]+self.size\n'
                           'def main():\n'
                           '    a=Array()\n'
                           '    print(a.read())\n'
                           'main()\n',
                           ['']),
 'stored_callback_after_field_initialization': ('def combine(a,b):return a+b\n'
                                                'class Array:\n'
                                                '    def __init__(self,n,operation):\n'
                                                '        self.operation=operation\n'
                                                '        self.size=n\n'
                                                '        self.data=[0]*n\n'
                                                '        self.fill()\n'
                                                '    def fill(self):\n'
                                                '        for i in '
                                                'range(self.size):self.data[i]=self.operation(i,self.size)\n'
                                                '    def read(self):return '
                                                'self.data[-1]+self.size\n'
                                                'def main():\n'
                                                '    a=Array(int(input()),combine)\n'
                                                '    print(a.read())\n'
                                                'main()\n',
                                                ['3\n', '0\n'])})

def inspect_source(name,integer='i64'):
    observed=[]
    original=Emitter.generate
    def generate(emitter):
        units=getattr(emitter.model.unit,'source_units',(emitter.model.unit,))
        before=[ast.dump(unit.tree,include_attributes=True)for unit in units]
        value=original(emitter)
        assert before==[ast.dump(unit.tree,include_attributes=True)for unit in units]
        observed.append(emitter.model)
        return value
    with patch.object(Emitter,'generate',generate):
        result=transpile(SOURCES[name][0],TranspileOptions(integer=integer,filename='fields.py',license='none'))
    return result,observed

class InitializedOwnedFieldProofs(unittest.TestCase):
    def fields(self,name,integer='i64'):
        result,models=inspect_source(name,integer)
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(models)
        model=models[0]
        fields={owner.fields[name].name for owner in model.classes.values()
                for index,name in enumerate(owner.fields)
                if (owner.index,index)in model.initialized_owned_fields.fields}
        return result,fields

    def test_fill_after_store_removes_optional_scalar_and_vector_fields_all_modes(self):
        for mode in ('i64','i128','bigint'):
            result,fields=self.fields('fill_method_after_store',mode)
            self.assertEqual(fields,{'size','data'})
            self.assertNotIn('checked stable field',result.rust_source)
            self.assertNotIn("AttributeError: 'Array' object has no attribute",result.rust_source)

    def test_missing_conditional_and_zero_trip_fields_keep_presence(self):
        _,fields=self.fields('conditional_presence')
        self.assertIn('size',fields);self.assertNotIn('data',fields)
        _,fields=self.fields('zero_trip_scalar_assignment')
        self.assertNotIn('size',fields)

    def test_early_method_and_rhs_reads_keep_their_original_error_path(self):
        _,fields=self.fields('early_method_read')
        self.assertNotIn('data',fields)
        _,fields=self.fields('early_scalar_rhs')
        self.assertNotIn('size',fields)

    def test_conditional_expression_and_dictionary_pairs_keep_early_errors(self):
        for name in ('conditional_expression_early_read','dictionary_pair_order'):
            _,fields=self.fields(name)
            self.assertNotIn('size',fields)

    def test_stored_callback_cannot_reach_the_private_owner(self):
        _,fields=self.fields('stored_callback_after_field_initialization')
        self.assertEqual(fields,{'size','data'})

    def test_helper_and_both_branch_initialization_are_proved(self):
        _,fields=self.fields('helper_initializes_scalar')
        self.assertIn('size',fields)
        _,fields=self.fields('branch_scalar_assignment')
        self.assertEqual(fields,{'size','data'})

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class InitializedOwnedFieldExecution(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def run_sources(self,names):
        for name in names:
            with self.subTest(name=name):self.exercise(*SOURCES[name])

    def test_normal_constructor_helpers_and_branch_stores(self):
        self.run_sources(('fill_method_after_store','helper_initializes_scalar','branch_scalar_assignment'))

    def test_partial_constructor_reads_and_zero_trip_presence(self):
        self.run_sources(('early_method_read','early_scalar_rhs','conditional_presence','zero_trip_scalar_assignment'))

    def test_source_rhs_and_constructor_failure_order(self):
        self.run_sources(('assignment_rhs_before_bad_index','constructor_partial_failure'))

    def test_adversarial_expression_order_and_stored_callback(self):
        self.run_sources(('conditional_expression_early_read','dictionary_pair_order','stored_callback_after_field_initialization'))
