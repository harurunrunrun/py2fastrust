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
