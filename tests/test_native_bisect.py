"""Independent bisection boundary, storage and argument-order comparisons."""
import shutil
import unittest

from py2fastrust import TranspileOptions,transpile
from tests import test_native_heapq as _heap


class BisectProofTests(unittest.TestCase):
    def test_remaining_callback_and_custom_comparison_boundaries_are_explicit(self):
        for source in ('import bisect\nprint(bisect.bisect_left([1,2],1,key=lambda x:x))\n',
                       'import bisect\nprint(bisect.bisect_left([None],None))\n'):
            for mode in('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')

    def test_fixed_width_bisection_does_not_embed_bigint_kernel(self):
        for mode in('i64','i128'):
            result=transpile('from bisect import bisect_left\nprint(bisect_left([],7))\n',TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('struct Int',result.rust_source)
            self.assertNotIn('UNICODE LICENSE V3',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class BisectExecutionTests(unittest.TestCase):
    def compare(self,*args,**kwargs):return _heap.HeapExecutionTests.compare(self,*args,**kwargs)

    def test_integer_bounds_include_empty_intervals_and_index_errors(self):
        self.compare('''import bisect
a=[-7,-1,0,2,2,9]
x,lo,hi=map(int,input().split())
print('start')
print(bisect.bisect_left(a,x,lo,hi),bisect.bisect_right(a,x,lo,hi))
bisect.insort(a,x,lo,hi)
print(a)
''',tuple(f'{x} {lo} {hi}\n'for x in(-8,0,2,99)for lo,hi in((0,6),(0,-1),(0,-2),(1,5),(5,1),(100,0),(-1,6),(0,100))))

    def test_empty_payload_still_validates_bounds_without_comparing_item(self):
        self.compare('''import bisect
def find(a,x,lo,hi):
 print('find',lo,hi)
 return bisect.bisect_left(a,x,lo,hi)
lo,hi=map(int,input().split())
print(find([],'not an integer',lo,hi))
print(bisect.bisect_right([],None,lo,hi))
''',('0 -1\n','0 0\n','7 0\n','0 1\n','-1 0\n'))

    def test_module_aliases_local_imports_and_scalar_function_mutation(self):
        self.compare('''import bisect as b
from bisect import insort_left as insert
module=b
left=module.bisect_left
def add(a):
 import bisect as local
 local.insort(a,3)
def find(a,x):
 from bisect import bisect_right as right
 return right(a,x)
a=[1,4]
alias=a
add(a)
insert(alias,3)
print(a is alias,a,left(a,3),find(a,3))
''')
        # This is the unchanged formerly negative module-call fixture.
        self.compare('import bisect\ndef insert(a):bisect.insort(a,3)\na=[1,4]\ninsert(a)\nprint(*a)\n')

    def test_string_bytes_and_fixed_dynamic_tuple_ordering(self):
        self.compare('''import bisect
strings=['a','b','b','z']
bisect.insort_left(strings,'b')
print(strings,bisect.bisect_right(strings,'b'))
bytes_values=[b'a',b'bc',b'z']
print(bisect.bisect_left(bytes_values,b'bb'))
fixed=[(1,2),(1,3),(2,0)]
item=tuple(map(int,input().split()))
print(bisect.bisect_left(fixed,item),bisect.bisect_right(fixed,item))
dynamic=[tuple([1,2]),tuple([1,3]),tuple([2,0])]
print(bisect.bisect_left(dynamic,(1,2)),bisect.bisect_right(dynamic,(1,2)))
bisect.insort(dynamic,item)
print(dynamic)
''',('\n','1\n','1 2\n','1 2 0\n','3 4\n'))

    def test_keyword_expression_order_precedes_borrow_and_index_conversion(self):
        self.compare('''import bisect
def mark(label,value):
 print(label)
 return value
def nothing():
 print('key')
 return None
a=[1,3]
print(bisect.bisect_left(x=mark('x',2),hi=mark('hi',2),a=a,lo=mark('lo',0),key=nothing()))
print(bisect.bisect_right(a,(a.clear(),2)[1]))
rows=[[1,3]]
print(bisect.bisect_left(rows[0],(rows.clear(),2)[1]))
print(rows)
rows=[[]]
print(bisect.bisect_left(rows[0],(rows[0].append(3),2)[1]))
print(rows)
''')

    def test_bool_integer_ties_and_shared_row_insertion(self):
        self.compare('''import bisect
a=[False,0,True,1]
alias=a
bisect.insort_left(a,False)
bisect.insort_right(alias,True)
print(a,alias,bisect.bisect_left(a,0),bisect.bisect_right(a,1))
rows=[[]]
row=rows[0]
bisect.insort(row,5)
print(next(iter(row)))
bisect.insort_left(rows[0],2)
print(row,rows)
''')

    def test_float_right_search_uses_reversed_less_including_nan(self):
        self.compare('''import bisect
a=[float(input()) for _ in range(4)]
item=float(input())
print(bisect.bisect_left(a,item),bisect.bisect_right(a,item))
bisect.insort_right(a,item)
print(a)
''',('0\n1\n2\n3\nnan\n','nan\n0\n1\n2\n1\n','-0.0\n0.0\n1\n2\n-0.0\n'),modes=('i64','i128'))

    def test_all_argument_effects_happen_before_bound_overflow_validation(self):
        self.compare('''import bisect
def mark(label):
 print(label)
 return int(input())
print('before')
print(bisect.bisect_left([],mark('item'),mark('lo'),mark('hi')))
''',('2\n-1\n9223372036854775808\n','bad\n-1\n0\n','2\n0\n9223372036854775808\n','2\n-1\n0\n'),modes=('i128','bigint'))


if __name__=='__main__':unittest.main()
