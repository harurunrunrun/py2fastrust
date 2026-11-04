"""Record-like lists retain type bounds without changing list semantics."""
import ast
import subprocess
import unittest

from py2fastrust.native_classes import Cell,merge,shape
from py2fastrust.native_constraints import Allocation
from py2fastrust.native_types import ListType
from tests import test_native_classes as _classes


class ListPositionTests(unittest.TestCase):
    compile=_classes.NativeClassTests.compile
    compare=_classes.NativeClassTests.compare

    def test_heterogeneous_pair_unpacking(self):
        self.compare('''class Marker: pass
def solve():
 record=[7,'label']
 number,label=record
 print(number+1,label.upper())
solve()
''')

    def test_heterogeneous_record_iteration(self):
        self.compare('''class Marker: pass
def solve():
 records=[[7,'alpha'],[9,'beta']]
 for number,label in records:
  print(number+1,label.upper())
solve()
''')

    def test_record_sort_key_and_indexed_members(self):
        self.compare('''class Marker: pass
def solve():
 records=[[7,'alpha'],[2,'beta'],[4,'gamma']]
 records.sort(key=lambda item:item[0])
 print(records[0][0]+1,records[0][1].upper())
solve()
''')

    def test_negative_index_and_readonly_length(self):
        self.compare('''class Marker: pass
a=[7,'alpha']
a[-1]='beta'
print(len(a),a[-2]+1,a[-1].upper())
''')

    def test_alias_mutation_and_resizing_widen_position_bounds(self):
        self.compare('''class Marker: pass
a=[7,'alpha']
b=a
a.append(13)
first=b.pop(0)
print(first,a[0],a[1],a is b)
b[0]=12
print(a[0],a[1])
''')

    def test_dynamic_index_keeps_actual_value_types(self):
        source='''class Marker: pass
a=[7,'alpha']
a[int(input())]=12
print(a[0],a[1])
'''
        self.compare(source,data='0\n')
        self.compare(source,data='1\n')

    def test_unregistered_finite_sequence_producer_uses_generic_elements(self):
        self.compare('''class Marker: pass
a=[1,'old'] if int(input()) else None
b=a+a
b[2]='changed'
print(b[-2])
''',data='1\n')

    def test_large_literal_store_uses_selected_integer_normalization(self):
        source='''class Marker: pass
a=[1,'old']
a[18446744073709551616]='new'
print(a[0])
'''
        for mode in ('i64','i128','bigint'):
            with self.subTest(mode=mode):
                binary,_=self.compile(source,mode)
                actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                if mode=='i64':
                    self.assertEqual((actual.returncode,actual.stdout),(0,'new\n'))
                else:
                    self.assertNotEqual(actual.returncode,0)
                    self.assertTrue(actual.stderr.rstrip().splitlines()[-1].startswith('IndexError:'))

    def test_equal_shape_union_payloads_keep_every_list_origin(self):
        first=Allocation(('left',1),'list')
        second=Allocation(('right',2),'list')
        for nested in (False,True):
            with self.subTest(nested=nested):
                a=Cell('list',(Cell('int'),),list_origins=frozenset({first}))
                b=Cell('list',(Cell('int'),),list_origins=frozenset({second}))
                left=Cell('tuple',(a,))if nested else a
                right=Cell('tuple',(b,))if nested else b
                joined=merge(Cell('union',(left,Cell('none'))),right,ast.Constant(0))
                payload=next(value for value in joined.args if shape(value)!='none')
                retained=payload.args[0]if nested else payload
                self.assertEqual(retained.list_origins,frozenset({first,second}))
                self.assertEqual(len(joined.args),2)

    def test_tuple_carrier_projects_its_field_union(self):
        self.compare('''class Marker: pass
records=[(1,2),('tag',3)]
print(records[0][0]+1,records[1][0].upper())
''')

    def test_tuple_carrier_projects_multiple_columns(self):
        self.compare('''class Marker: pass
records=[(1,'alpha'),('beta',2)]
first=records[0]
print(first[0]+2,first[1].upper())
''')

    def test_tuple_carrier_projects_nested_fields(self):
        self.compare('''class Marker: pass
records=[((1,'alpha'),3),(('beta',2),4)]
first=records[0]
print(first[0][0]+2,first[0][1].upper(),first[1])
''')

    def test_projected_tuple_preserves_shared_leaf_identity(self):
        self.compare('''class Marker: pass
row=[1]
records=[(row,'alpha'),(row,2)]
first=records[0]
first[0][0]=9
print(records[1][0][0],first[1].upper(),first[0] is row)
''')

    def test_unproved_callable_projection_retains_generic_native_dispatch(self):
        self.compare('''class Marker: pass
def first():return 7
def second():return 9
functions=[first,second]
print(functions[0](),functions[1]())
''')

    def test_descriptor_tagged_list_does_not_inherit_known_origins(self):
        origin=Allocation(('known',1),'list')
        known=Cell('list',(Cell('int'),),list_origins=frozenset({origin}))
        unknown=Cell(ListType('int'))
        result=merge(Cell('union',(known,Cell('none'))),unknown,ast.Constant(0))
        retained=next(value for value in result.args if shape(value)!='none')
        self.assertIsNone(retained.list_origins)


if __name__=='__main__':unittest.main()
