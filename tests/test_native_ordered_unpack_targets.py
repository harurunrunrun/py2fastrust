"""Unpacking snapshots each level before ordered name and list-place stores."""
import unittest

import test_native_lambda_callbacks as helpers
from py2fastrust import transpile, TranspileOptions

CASES={'alias_row_swap': ['first=[1]\n'
                    'second=[2]\n'
                    'rows=[first,second]\n'
                    'rows[0],rows[1]=rows[1],rows[0]\n'
                    'rows[0].append(3)\n'
                    'print(first,second,rows)\n',
                    ['']],
 'all_rhs_before_index_calls': ['def rhs(value):\n'
                                ' print("rhs",value)\n'
                                ' return value\n'
                                'def index(value):\n'
                                ' print("index",value)\n'
                                ' return value\n'
                                'a=[0,0]\n'
                                'a[index(0)],a[index(1)]=rhs(5),rhs(6)\n'
                                'print(a)\n',
                                ['']],
 'attribute_target_order': ['class Box:\n'
                            ' def __init__(self):self.value=0\n'
                            'box=Box()\n'
                            'items=[0]\n'
                            'box.value,items[box.value]=0,7\n'
                            'print(box.value,items)\n',
                            ['']],
 'dynamic_nested_list_snapshot': ['a=[0,0,0]\na[0],(a[1],a[2])=7,[8,9]\nprint(a)\n', ['']],
 'generator_to_indexed_targets': ['a=[0,0]\n'
                                  'a[0],a[1]=(int(word)for word in input().split())\n'
                                  'print(a)\n',
                                  ['7 8\n', '7 8 9\n']],
 'index_after_prior_name': ['i=0\na=[10,20,30]\ni,a[i]=2,99\nprint(i,a)\n', ['']],
 'later_index_after_store': ['a=[0,1,2]\na[0],a[a[0]]=2,9\nprint(a)\n', ['']],
 'missing_owner_precedes_index': ['def index():\n'
                                  ' print("index")\n'
                                  ' return 0\n'
                                  'if int(input()):\n'
                                  ' a=[0]\n'
                                  'a[index()],other=7,8\n'
                                  'print(other)\n',
                                  ['0\n', '1\n']],
 'mixed_name_and_dynamic_tuple': ['a=[0,0]\n'
                                  'values=tuple(map(int,input().split()))\n'
                                  'head,a[0]=values\n'
                                  'print(head,a)\n',
                                  ['5 6\n', '5\n']],
 'negative_and_big_index': ['a=["x","y"]\ni=int(input())\na[-1],a[i]="z","w"\nprint(a)\n',
                            ['0\n']],
 'nested_fixed_targets': ['a=[0,0,0]\na[0],(a[1],a[2])=(3,(4,5))\nprint(a)\n', ['']],
 'nested_row_places': ['rows=[[1,2],[3,4]]\n'
                       'rows[0][0],rows[1][1]=rows[1][1],rows[0][0]\n'
                       'print(rows)\n',
                       ['']],
 'new_row_used_for_later_target': ['rows=[[1],[2]]\n'
                                   'saved=rows[1]\n'
                                   'rows[0],rows[0][0]=saved,9\n'
                                   'print(rows,saved)\n',
                                   ['']],
 'partial_store_visible_before_bad_index': ['def show(values):\n'
                                            ' print(values)\n'
                                            ' return 5\n'
                                            'a=[0,1]\n'
                                            'a[0],a[show(a)]=7,8\n',
                                            ['']],
 'pure_name_nested_partial_failure': ['first,(second,third)=(7,(8,))\nprint(first)\n', ['']],
 'rhs_failure_prevents_targets': ['def index():\n'
                                  ' print("index")\n'
                                  ' return 0\n'
                                  'def bad():\n'
                                  ' print("rhs")\n'
                                  ' return 1//0\n'
                                  'a=[0]\n'
                                  'a[index()],a[0]=bad(),2\n',
                                  ['']],
 'saved_tuple_aliases': ['first=[1]\n'
                         'second=[2]\n'
                         'pair=(first,second)\n'
                         'rows=[first,second]\n'
                         'rows[1],rows[0]=pair\n'
                         'first.append(7)\n'
                         'print(rows,pair)\n',
                         ['']],
 'target_failure_stops_later': ['def index(value):\n'
                                ' print("index",value)\n'
                                ' return value\n'
                                'a=[0,1]\n'
                                'a[index(3)],a[index(0)]=5,6\n',
                                ['']],
 'text_swap': ['tags=list(input())\n'
               'a,b=map(int,input().split())\n'
               'tags[a],tags[b]=tags[b],tags[a]\n'
               'print("".join(tags))\n',
               ['abcd\n0 3\n', 'abcd\n2 2\n']],
 'wrong_tuple_length_stops_indices': ['def index():\n'
                                      ' print("index")\n'
                                      ' return 0\n'
                                      'a=[0]\n'
                                      'a[index()],a[0]=(7,)\n',
                                      ['']]}

SLICE_UNPACK_SOURCE='values=[0,1,2]\nvalues[:1],values[1:]=[7],[8,9]\n'
CASES.update({
 'supported_slice_unpacking_original': (SLICE_UNPACK_SOURCE, ('',)),
 'slice_unpacking_observable_result': (SLICE_UNPACK_SOURCE+'print(values)\n', ('',)),
 'extended_slice_unpacking_keeps_aliases': (
     'values=[0,1,2,3]\nalias=values\n'
     'values[::2],values[1::2]=[7,8],[9,10]\n'
     'print(values,alias,alias is values)\n', ('',)),
})

class OrderedUnpackExecution(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise


def _test(source, inputs):
    def test(self):
        self.exercise(source, inputs)
    return test


for _name, (_source, _inputs) in CASES.items():
    setattr(OrderedUnpackExecution, 'test_'+_name, _test(_source, _inputs))


class OrderedUnpackDiagnostics(unittest.TestCase):
    def test_slice_unpacking_uses_the_proved_store_adapter(self):
        for integer in ('i64','i128','bigint'):
            result=transpile(SLICE_UNPACK_SOURCE,TranspileOptions(integer=integer,filename='targets.py'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')

    def test_mapping_unpacking_names_the_unproved_place(self):
        source='values={0:1}\nvalues[0],other=2,3\nprint(values,other)\n'
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer,filename='targets.py'))
            self.assertFalse(result.success)
            message=' '.join(str(item)for item in result.diagnostics)
            self.assertIn('indexed/attribute unpacking',message)
            self.assertIn('mapping/deque/alternative receiver stores',message)
            self.assertIn('targets.py:2:',message)


if __name__=='__main__':unittest.main()
