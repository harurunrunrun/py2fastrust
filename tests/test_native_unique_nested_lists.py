"""Unique rows use vectors; escaped rows retain identity and iterator lifetimes."""
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_mapping_mutations as execution
import test_native_unpack_exact_lengths as harness


class UniqueNestedListSelection(unittest.TestCase):
    def shared(self, source):
        result = transpile(source, TranspileOptions(license='none'))
        self.assertTrue(result.success, result.diagnostics)
        return 'native_shared_list(' in result.rust_source

    def test_fresh_rows_have_unique_owned_storage(self):
        for source in (
                'rows=[[] for _ in range(3)]\nrows[0].append(7)\nfor x in rows[0]:\n print(x)\n',
                'rows=[[1,2],[],[3]]\nrows[1].append(-9)\nprint(len(rows),len(rows[1]),rows[1][0])\n'):
            with self.subTest(source=source):
                self.assertFalse(self.shared(source))

    def test_aliases_copies_repeated_rows_and_owner_rebinding_keep_shared_storage(self):
        for source in (
                'rows=[[] for _ in range(2)]\nrow=rows[0]\nrow.append(7)\nprint(rows)\n',
                'rows=[[1],[2]]\nother=rows.copy()\nother[0].append(7)\nprint(rows,other)\n',
                'rows=[[1]]*3\nrows[0].append(7)\nprint(rows)\n',
                'rows=[[1,2]]\nfor x in rows[0]:\n rows[0].append(7)\n break\nprint(rows)\n',
                'rows=[[1,2]]\nfor x in rows[0]:\n rows=[[3,4]]\n print(x)\nprint(rows)\n'):
            with self.subTest(source=source):
                self.assertTrue(self.shared(source))

    def test_numeric_repeated_rows_and_cell_updates_have_owned_storage(self):
        for source in (
                'rows=[[False]*3 for _ in range(2)]\nrows[0][1]=True\nprint(rows[0][1],rows[1][1])\n',
                'rows=[[1.5]*3 for _ in range(2)]\nrows[0][-1]+=0.5\nprint(rows[0][2],rows[1][2])\n',
                'rows=[[1,2],[3,4]]\nrows[1][1]=rows[0][0]+rows[0][1]\nprint(rows[1][1])\n'):
            with self.subTest(source=source):self.assertFalse(self.shared(source))

    def test_cell_mutation_during_row_iteration_keeps_shared_storage(self):
        self.assertTrue(self.shared('rows=[[False,False]]\nfor item in rows[0]:\n print(item)\n rows[0][1]=True\n'))


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class UniqueNestedListExecution(unittest.TestCase):
    compare = execution.NativeMappingMutationTests.compare

    def test_literal_rows_have_independent_mutation_and_scalar_reads(self):
        self.compare('''rows=[[1,2],[],[3]]
rows[1].append(-9)
print(len(rows),len(rows[1]),rows[1][0])
answer=0
for x in rows[1]:
 answer+=x
print(answer)
''')

    def test_rebinding_and_shallow_copies_preserve_live_rows(self):
        self.compare('''rows=[[1,2],[3]]
other=rows.copy()
other[0].append(7)
for x in rows[0]:
 rows=[[9]]
 print(x)
print(rows,other)
''')

    def test_repeated_bool_rows_are_independent(self):
        self.compare('''rows=[[False]*3 for _ in range(2)]
rows[0][1]=True
print(rows[0][1],rows[1][1],len(rows),len(rows[0]))
''')

    def test_fresh_constructor_rows_remain_independent(self):
        self.compare('''rows=[list([False,True]) for _ in range(2)]
rows[0][0]=True
print(rows[0][0],rows[1][0],rows[0][1],rows[1][1])
''')

    def test_float_updates_and_nested_scalar_rhs_read_the_original_rows(self):
        self.compare('''rows=[[1.5]*3 for _ in range(2)]
rows[0][-1]+=0.5
rows[1][0]=rows[0][0]+rows[0][2]
rows[1][1]*=rows[1][0]
print(rows[0][0],rows[0][2],rows[1][0],rows[1][1],rows[1][2])
''')

    def test_integer_cell_writes_and_augmented_reads_keep_the_matrix_owner(self):
        self.compare('''rows=[[1,2],[3,4]]
rows[1][-1]=rows[0][0]+rows[0][1]
rows[0][-1]+=rows[1][-1]
print(rows[0][0],rows[0][1],rows[1][0],rows[1][1])
''')

    def test_cell_assignment_runs_rhs_before_owner_and_index_errors(self):
        source='''rows=[[1.5,2.5],[3.5,4.5]]
r=int(input())
c=int(input())
divisor=float(input())
print('before')
rows[r][c]=1.0/divisor
print(rows[0][0],rows[1][1])
'''
        self.compare(source,('0\n0\n2\n','-1\n-1\n2\n','2\n0\n0\n',
                             '2\n0\n2\n','0\n2\n0\n','0\n2\n2\n'))

    def test_cell_augassign_reads_before_rhs_errors(self):
        source='''rows=[[1.5,2.5],[3.5,4.5]]
r=int(input())
c=int(input())
divisor=float(input())
print('before')
rows[r][c]+=1.0/divisor
print(rows[0][0],rows[1][1])
'''
        self.compare(source,('0\n0\n2\n','-1\n-1\n2\n','2\n0\n0\n',
                             '2\n0\n2\n','0\n2\n0\n','0\n0\n0\n'))

    def test_outer_repetition_and_row_aliases_keep_identity(self):
        self.compare('''rows=[[False]*2]*2
rows[0][1]=True
print(rows[1][1])
fresh=[[False]*2 for _ in range(2)]
row=fresh[0]
row[0]=True
print(fresh[0][0],fresh[1][0],row is fresh[0])
''')

    def test_mutation_during_row_iteration_remains_observable(self):
        self.compare('''rows=[[False,False]]
for item in rows[0]:
 print(item)
 rows[0][1]=True
''')


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class UniqueNestedListInputExecution(harness.ExactUnpackLengthTests):
    def test_eager_lengths_and_lazy_error_order(self):
        source='''n=int(input())
rows=[[] for _ in range(n)]
for i in range(n):
 for j in range(i):
  rows[i].append(j-i)
answer=0
for i in range(n):
 for x in rows[i]:
  answer+=x
print(answer)
'''
        for mode in ('i64','i128','bigint'):
            for optimized in (False,True):
                compiled=self.compile(source,mode,release=optimized)
                for n in (-3,0,1,5,17):
                    data=str(n)+'\n'
                    expected=subprocess.run([sys.executable,'-I','-c',source],input=data,text=True,capture_output=True,timeout=10)
                    actual=subprocess.run([str(compiled[1])],input=data,text=True,capture_output=True,timeout=10)
                    with self.subTest(integer=mode,optimized=optimized,n=n):
                        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),
                            (expected.returncode,expected.stdout,expected.stderr))


if __name__=='__main__':
    unittest.main()
