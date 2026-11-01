"""Exact builtin sequences expose full unpack lengths; lazy producers do not."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_native_iterator_reductions as support


CASES=(('list_literal', 'a,b=[1,2,3]\n', ''),
 ('tuple_literal', 'a,b=(1,2,3)\n', ''),
 ('named_list', 'values=list(map(int,input().split()))\na,b=values\n', '1 2 3 4\n'),
 ('named_tuple', 'values=tuple(map(int,input().split()))\na,b=values\n', '1 2 3 4\n'),
 ('list_chars', 'a,b=["a","b","c"]\n', ''),
 ('text_split', 'a,b=input().split()\n', 'one two three four\n'),
 ('bytes_split', 'import sys\na,b=sys.stdin.buffer.readline().split()\n', 'one two three four\n'),
 ('lazy_map', 'a,b=map(int,input().split())\n', '1 2 3 invalid\n'),
 ('lazy_generator', 'a,b=(int(x)for x in input().split())\n', '1 2 3 invalid\n'),
 ('tuple_loop',
  'rows=[tuple(map(int,input().split()))]\nfor a,b in rows:\n print(a,b)\n',
  '1 2 3\n'),
 ('range_source', 'a,b=range(4)\n', ''),
 ('enumerate_source', 'a,b=enumerate([1,2,3,4])\n', ''),
 ('zip_source', 'a,b=zip([1,2,3],[4,5,6])\n', ''),
 ('reversed_source', 'a,b=reversed([1,2,3,4])\n', ''),
 ('short_list', 'values=list(map(int,input().split()))\na,b=values\n', '1\n'),
 ('empty_list', 'values=list(map(int,input().split()))\na,b=values\n', '\n'),
 ('exact_list', 'values=list(map(int,input().split()))\na,b=values\nprint(a,b)\n', '1 2\n'),
 ('class_list',
  'class Marker:pass\nvalues=list(map(int,input().split()))\na,b=values\n',
  '1 2 3\n'),
 ('class_loop',
  'class Marker:pass\nvalues=[list(map(int,input().split()))]\nfor a,b in values:\n print(a,b)\n',
  '1 2 3\n'))


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ExactUnpackLengthTests(unittest.TestCase):
    compile=support.NativeIteratorReductionTests.compile

    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="pytors-unpack-length-")
        cls.counter=0

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def test_eager_lengths_and_lazy_error_order(self):
        for name,source,data in CASES:
            expected=subprocess.run([sys.executable,"-I","-c",source],input=data,text=True,capture_output=True,timeout=10)
            for mode in ("i64","i128","bigint"):
                for optimized in (False,True):
                    with self.subTest(case=name,integer=mode,optimized=optimized):
                        compiled=self.compile(source,mode,release=optimized)
                        actual=subprocess.run([str(compiled[1])],input=data,text=True,capture_output=True,timeout=10)
                        self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                        ending=lambda value:value.rstrip().splitlines()[-1:]if value else[]
                        self.assertEqual(ending(actual.stderr),ending(expected.stderr))
                        frames=lambda value:re.findall(r'File "[^\"]+", line (\d+), in ([^\n]+)',value)
                        self.assertEqual(frames(actual.stderr),frames(expected.stderr))


if __name__=="__main__":unittest.main()
