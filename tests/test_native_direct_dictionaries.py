"""Original dictionary comprehensions and primitive dictionary copies."""
import ast
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
import test_native_annotations_assertions as support


CASES = {
    'range_collision_filter_order': (
        "def mark(label,value):\n print(label,value)\n return value\n"
        "n=int(input())\n"
        "data={mark('key',i%2):mark('value',i*3) for i in range(n) if mark('filter',i%3)}\n"
        "print(data,list(data),len(data))\n", ('0\n', '6\n')),
    'nested_clauses_and_outer_scope': (
        "i=90\nj=80\n"
        "data={i*j:i+j for i in [2,3,4] if i!=3 for j in range(i) if j}\n"
        "print(data,i,j)\n", ('',)),
    'tuple_targets_and_nested_filters': (
        "data={a-b:a*b for a,b in [(5,2),(7,3),(6,2)] if a>5 if b<4}\n"
        "print(data)\n", ('',)),
    'copy_has_independent_keys_and_values': (
        "n=int(input())\ndata={i%3:10*i for i in range(n)}\n"
        "other=data.copy()\ndata[0]=71\nother[9]=42\n"
        "print(data,other,len(data),len(other))\n", ('0\n', '8\n')),
    'explicit_integer_dict_copy': (
        "n=int(input())\ndata={}\n"
        "for i in range(n):\n data[i]=3*i\n"
        "other=data.copy()\nother[99]=7\nprint(data,other)\n", ('0\n', '4\n')),
    'key_failure_precedes_value': (
        "def mark(label,value):\n print(label,value)\n return value\n"
        "data={12//mark('key',i):mark('value',i) for i in [2,0,4]}\n"
        "print(data)\n", ('',)),
    'value_failure_precedes_insertion_and_next_item': (
        "def mark(label,value):\n print(label,value)\n return value\n"
        "data={mark('key',i):12//mark('value',i) for i in [3,0,2]}\n"
        "print(data)\n", ('',)),
    'later_clause_constructed_per_outer_item': (
        "def bound(value):\n print('bound',value)\n return value\n"
        "data={i+j:i-j for i in [1,2,3] for j in range(bound(i)) if j!=1}\n"
        "print(data)\n", ('',)),
    'tuple_keys_bool_int_representatives': (
        "data={(i%2,True):i for i in range(5)}\n"
        "other=data.copy()\nother[(1,1)]=9\nprint(data,other)\n", ('',)),
    'copy_alias_preserved_by_existing_shared_route': (
        "data={i:i+1 for i in range(4)}\nother=data.copy()\nalias=other\n"
        "alias[1]=80\nprint(data,other,alias is other)\n", ('',)),
    'empty_comprehension_copy': (
        "data={i:i for i in []}\nprint(data,data.copy())\n", ('',)),
    'mixed_numeric_keys_keep_first_representative': (
        "data={key:index for index,key in enumerate([True,1,False,0,2])}\n"
        "print(data,data.copy(),list(data))\n", ('',)),
    'shadowed_range_retains_real_callable': (
        "def range(n):\n print('source range',n)\n return [n,n-1]\n"
        "data={i:i*2 for i in range(4)}\nprint(data.copy())\n", ('',)),
}


class DirectDictionaryMetadataTests(unittest.TestCase):
    def test_original_comprehension_and_tables_are_preserved(self):
        source=CASES['nested_clauses_and_outer_scope'][0]
        unit=build_program(source,'direct_dict.py').main
        tree=ast.dump(unit.tree,include_attributes=True)
        table=unit.table
        from py2fastrust.native import try_generate_native
        diagnostics=[]
        result=try_generate_native(source,'direct_dict.py','i64',unit=unit,diagnostic_out=diagnostics)
        self.assertIsNotNone(result,diagnostics)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),tree)
        self.assertIs(unit.table,table)
        unit.check_identity(source,'direct_dict.py')
        self.assertFalse(select_frames(unit).required)

    def test_fixed_integer_copy_uses_direct_typed_storage(self):
        for name in ('copy_has_independent_keys_and_values','explicit_integer_dict_copy'):
            source=CASES[name][0]
            unit=build_program(source,'direct_dict.py').main
            self.assertFalse(select_frames(unit).required)
            for integer in ('i64','i128'):
                result=transpile(source,TranspileOptions(integer=integer,filename='direct_dict.py'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertIn('struct NativeDict',result.rust_source)
                self.assertNotIn('ClassFrame',result.rust_source)
                self.assertIn('native_dict_try_copy',result.rust_source)

    def test_precise_remaining_direct_boundaries(self):
        sources={
            'walrus':("data={i:(last:=i) for i in range(3)}\nprint(last)\n",1,'assignment expressions'),
            'copy_arguments':("data={0:1}\nother=data.copy(7)\n",2,'copy'),
            'copy_keywords':("data={0:1}\nother=data.copy(extra=7)\n",2,'copy'),
        }
        for name,(source,line,needle)in sources.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer,filename='direct_dict.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code=='E006'and d.line==line and needle in d.message for d in result.diagnostics),result.diagnostics)


class DirectDictionaryExecutionTests(unittest.TestCase):
    pass


def _case(name):
    def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*CASES[name])
    return test


for _name in CASES:
    setattr(DirectDictionaryExecutionTests,'test_'+_name,_case(_name))


if __name__=='__main__':
    unittest.main()
