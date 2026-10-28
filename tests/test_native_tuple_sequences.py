"""Variable-length tuple input remains immutable and checks arity at use time."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


class NativeTupleSequenceBoundaryTests(unittest.TestCase):
    def test_mutable_payload_and_unproved_sort_protocols_are_explicit(self):
        sources=["t=tuple([[1]])\n", "rows=[tuple([1.0]),tuple([2.0])]\nrows.sort()\n", "rows=[tuple([1,'a']),tuple([2,'b'])]\nrows.sort()\n"]
        for source in sources:
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_dict_display_preserves_tuple_sequence_key(self):
        NativeTupleSequenceTests().compare("a=tuple(range(2))\nd={a:7}\nprint(d)\n")


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeTupleSequenceTests(unittest.TestCase):
    def compare(self,source,inputs=('',),error_frame=None):
        with tempfile.TemporaryDirectory(prefix='pytors-tuple-sequence-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename='tuples.py'))
                self.assertTrue(result.success,result.diagnostics)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                self.assertLess(len(result.rust_source.encode()),512*1024)
                path=Path(directory)/(mode+'.rs');path.write_text(result.rust_source)
                for release in (False,True):
                    binary=path.with_name(mode+str(release))
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data in inputs:
                        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,text=True,capture_output=True,timeout=10)
                        actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+expected.stderr)
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(':')[0],expected.stderr.splitlines()[-1].split(':')[0])
                            if error_frame:self.assertIn('in '+error_frame,actual.stderr)

    def test_dynamic_input_tuple_index_length_truth_repr_and_iteration(self):
        self.compare('''t=tuple(map(int,input().split()))
print(t,len(t),bool(t),t[0],t[-1])
print([x*2 for x in t])
print(*t)
''',('4 7 9\n','5\n','\n','bad\n'))

    def test_immutable_tuple_alias_identity_and_value_protocols(self):
        self.compare('''a=tuple(map(int,input().split()))
b=tuple(a)
c=tuple(list(a))
print(a is b,a is c,a==c,a!=c)
print(a==(1,2),a!=(1,2),a<(1,2,3),(1,2,3)>a)
print(2 in a,7 not in a,a==c!=None)
''',('1 2\n','1 2 4\n','\n'))

    def test_comprehension_and_generator_unpack_errors_keep_producer_frames(self):
        prefix='''def add(a,b):
 print('add',a,b)
 return a+b
rows=[tuple(map(int,input().split()))for _ in range(2)]
print('read')
'''
        inputs=('1 2\n3 4\n','1 2\n3\n','1 2\n3 4 5\n')
        self.compare(prefix+'print([add(a,b) for a,b in rows])\n',inputs)
        self.compare(prefix+'print(sum(add(a,b) for a,b in rows))\n',inputs,error_frame='<genexpr>')

    def test_variable_length_tuple_dictionary_and_set_keys_use_value_hashing(self):
        self.compare('''a=tuple(map(int,input().split()))
d={a:7}
print(list(d),d[a],a in d)
s=set([a,tuple(list(a)),tuple(range(2))])
print(len(s),a in s)
d={tuple([True,False]):'key'}
print(d[tuple([1,0])])
''',('1 2\n','0 1\n','\n'))

    def test_runtime_tuple_sorting_extrema_and_stability(self):
        self.compare('''rows=[tuple(range(k)) for k in (2,0,3,1,2)]
first=rows[0]
second=rows[4]
rows.sort()
print(rows,rows[2] is first,rows[3] is second)
print(min(rows),max(rows),min(first,second) is first)
def keep(row):return row
rows.sort(key=keep,reverse=True)
print(rows,sorted(rows))
''')

    def test_user_functions_are_not_hashed_or_confused_with_builtin_constructors(self):
        self.compare('''def twice(value):return value*2
print(twice(3))
a=tuple(range(2))
def keep(value):return value
print(keep(a),keep(a) is a)
''')
        self.compare('''def tuple(value):return len(value)+1
print(tuple((2,3)))
''')

    def test_exact_unpacking_is_checked_when_consumed_after_all_input(self):
        self.compare('''rows=[tuple(map(int,input().split()))for _ in range(3)]
print('all read')
for a,b in rows:
 print(a+b)
''',('1 2\n3 4\n5 6\n','1\n3 4\n5 6\n','1 2 3\n3 4\n5 6\n','1\n3 4\nbad\n'))


if __name__=='__main__':unittest.main()
