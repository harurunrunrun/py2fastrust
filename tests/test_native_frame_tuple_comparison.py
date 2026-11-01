"""Captured runtime tuples share native ordering, membership and sort protocols."""
from pathlib import Path
import os,re,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions

CASES = [('ordered_runtime_pairs_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'b=tuple(map(int,input().split()))\n'
  'print(a<b,a<=b,a>b,a>=b,a==b,a!=b)\n',
  '\n\n'),
 ('ordered_runtime_pairs_1',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'b=tuple(map(int,input().split()))\n'
  'print(a<b,a<=b,a>b,a>=b,a==b,a!=b)\n',
  '1 2\n1 2 3\n'),
 ('ordered_runtime_pairs_2',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'b=tuple(map(int,input().split()))\n'
  'print(a<b,a<=b,a>b,a>=b,a==b,a!=b)\n',
  '1 3\n1 2\n'),
 ('ordered_runtime_pairs_3',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'b=tuple(map(int,input().split()))\n'
  'print(a<b,a<=b,a>b,a>=b,a==b,a!=b)\n',
  '-1 4\n0\n'),
 ('ordered_runtime_fixed_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'print(a<(1,2),a<=(1,2),(1,2)<a,(1,2)<=a,a>(1,2),a>=(1,2))\n',
  '\n'),
 ('ordered_runtime_fixed_1',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'print(a<(1,2),a<=(1,2),(1,2)<a,(1,2)<=a,a>(1,2),a>=(1,2))\n',
  '1 2\n'),
 ('ordered_runtime_fixed_2',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'print(a<(1,2),a<=(1,2),(1,2)<a,(1,2)<=a,a>(1,2),a>=(1,2))\n',
  '1 2 3\n'),
 ('ordered_runtime_fixed_3',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(map(int,input().split()))\n'
  'print(a<(1,2),a<=(1,2),(1,2)<a,(1,2)<=a,a>(1,2),a>=(1,2))\n',
  '0\n'),
 ('empty_runtime_shapes_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([])\n'
  'b=tuple([1,2])\n'
  'print(a<b,a<=b,b>a,b>=a,a<a,a<=a,a>(1,),()>=b)\n',
  ''),
 ('text_runtime_pairs_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(input().split())\n'
  'b=tuple(input().split())\n'
  'print(a<b,a<=b,a>b,a>=b,a==b)\n',
  '\n\n'),
 ('text_runtime_pairs_1',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(input().split())\n'
  'b=tuple(input().split())\n'
  'print(a<b,a<=b,a>b,a>=b,a==b)\n',
  'a z\na zz\n'),
 ('text_runtime_pairs_2',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple(input().split())\n'
  'b=tuple(input().split())\n'
  'print(a<b,a<=b,a>b,a>=b,a==b)\n',
  'ab cd\nz\n'),
 ('bytes_runtime_pairs_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([b"a",b"bc"])\n'
  'b=tuple([b"a",b"d"])\n'
  'print(a<b,b>a,a<=a,b>=b)\n',
  ''),
 ('nested_runtime_pairs_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([tuple([1,2]),tuple([3])])\n'
  'b=tuple([tuple([1,2]),tuple([4])])\n'
  'print(a<b,b>a,a<=a,a in tuple([a,b]))\n',
  ''),
 ('membership_preserves_nested_values_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,2,3])\n'
  'print(2 in a,5 not in a,True in a,None in a)\n'
  'print((1,2) in tuple([(1,2),(3,4)]))\n',
  ''),
 ('empty_membership_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([])\n'
  'print(1 in a,1 not in a)\n',
  ''),
 ('extrema_retains_identity_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,2])\n'
  'b=tuple([1,2])\n'
  'rows=Rows([a,b])\n'
  'print(rows.first() is a,min(a,b) is a,max(a,b) is a)\n',
  ''),
 ('extrema_runtime_candidates_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'values=[tuple(range(n)) for n in (3,0,1,2)]\n'
  'print(min(values),max(values),min(values,key=None),max(values,key=None))\n',
  ''),
 ('nested_fixed_runtime_order_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([(1,2),(2,3)])\n'
  'b=tuple([(1,2),(2,4)])\n'
  'print(a<b,b>a,a<=a,a==a)\n',
  ''),
 ('none_order_is_skipped_when_equal_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([None])\n'
  'print(a<a,a<=a,a>=a,a>a,None in a)\n',
  ''),
 ('mixed_type_order_error_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,"x"])\n'
  'b=tuple([1,3])\n'
  'print("before")\n'
  'print(a<b)\n',
  ''),
 ('mismatch_order_error_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,2])\n'
  'print("before")\n'
  'print(a<3)\n',
  ''),
 ('mixed_match_skips_bad_order_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,"x"])\n'
  'b=tuple([2,3])\n'
  'print(a<b,b>a,a==b)\n',
  ''),
 ('short_circuit_chained_rhs_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'events=[]\n'
  'def rhs():events.append(1);return tuple([9])\n'
  'a=tuple([2]);b=tuple([1])\n'
  'print(a<b<rhs(),events)\n',
  ''),
 ('captured_function_comparison_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'def less(a,b):return a<b\n'
  'x=tuple([1,2]);y=tuple([1,3])\n'
  'print(less(x,y),list(map(less,[x,y],[y,x])))\n',
  ''),
 ('membership_runtime_tuples_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,2]);b=tuple([3,4])\n'
  'values=tuple([a,b])\n'
  'print(a in values,tuple([1,2]) in values,tuple([8]) not in values)\n',
  ''),
 ('membership_of_runtime_in_fixed_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,2])\n'
  'print(a in ((1,2),(3,4)))\n',
  ''),
 ('membership_of_runtime_in_list_0',
  'class Rows:\n'
  ' def __init__(self,values):self.values=values\n'
  ' def first(self):return min(self.values)\n'
  'a=tuple([1,2]);b=tuple([3,4])\n'
  'print(a in [b,a],tuple([8]) not in [a,b])\n',
  ''),
 ('original_extrema_stability_0',
  'rows=[tuple(range(k)) for k in (2,0,3,1,2)]\n'
  'first=rows[0]\n'
  'second=rows[4]\n'
  'rows.sort()\n'
  'print(rows,rows[2] is first,rows[3] is second)\n'
  'print(min(rows),max(rows),min(first,second) is first)\n'
  'def keep(row):return row\n'
  'rows.sort(key=keep,reverse=True)\n'
  'print(rows,sorted(rows))\n',
  ''),
 ('runtime_and_fixed_sort',
  'class Scope:pass\n'
  'rows=[tuple([2]),(1,),tuple([3,4]),()]\n'
  'print(sorted(rows))\n'
  'rows.sort(reverse=True)\n'
  'print(rows)\n',
  ''),
 ('empty_runtime_sort', 'class Scope:pass\na=tuple([])\nrows=[(1,),a,()]\nprint(sorted(rows))\n', ''),
 ('runtime_tuple_key_side_effects',
  'class Scope:pass\n'
  'events=[]\n'
  'def key(value):\n'
  ' events.append(value)\n'
  ' return tuple([value%3,-value])\n'
  'values=[4,1,2,3,7,6]\n'
  'print(sorted(values,key=key),events)\n',
  ''),
 ('sort_bad_element_reports_error',
  'class Scope:pass\nrows=[tuple([1,"x"]),tuple([1,3])]\nprint("before")\nrows.sort()\nprint("wrong")\n',
  ''),
 ('tuple_comparison_callable_errors',
  'class Scope:pass\n'
  'def bad(a,b):\n'
  ' print("inside")\n'
  ' return a<b\n'
  'print(bad(tuple(["x"]),tuple([1])))\n',
  ''),
 ('empty_tuple_membership',
  'class Scope:pass\na=tuple([])\nprint(a in tuple([a]),a in ((),(1,)),a in [(),a])\n',
  ''),
 ('reverse_sort_stable_identity',
  'class Scope:pass\n'
  'a=tuple([1,2]);b=tuple([1,2]);c=tuple([2])\n'
  'rows=[a,c,b]\n'
  'rows.sort(reverse=True)\n'
  'print(rows,rows[1]is a,rows[2]is b)\n',
  ''),
 ('nested_fixed_runtime_sort',
  'class Scope:pass\na=(tuple([1,2]),3)\nb=(tuple([1,3]),2)\nrows=[b,a]\nrows.sort()\nprint(rows)\n',
  ''),
 ('tuple_membership_after_effects',
  'class Scope:pass\n'
  'events=[]\n'
  'def member():events.append(1);return 2\n'
  'def owner():events.append(2);return tuple([1,2,3])\n'
  'print(member()in owner(),events)\n',
  '')]
def canonical_error(stderr):
    return [line for line in stderr.splitlines()if line.startswith(('Traceback (most recent call last):','  File ','During handling of the above exception, another exception occurred:'))or re.match(r'^[A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Iteration)(?::|$)',line)]


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrameTupleComparisonExecutionTests(unittest.TestCase):
    def exercise(self,source,stdin):
        with tempfile.TemporaryDirectory(prefix='pytors-frame-tuple-')as directory:
            root=Path(directory);main=root/'main.py';main.write_text(source)
            expected=subprocess.run([sys.executable,'-S',str(main)],input=stdin,capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with self.subTest(integer=mode):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy emitter entered')):
                        result=transpile(source,TranspileOptions(filename=str(main),integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','struct PegParser','UNICODE LICENSE V3'):
                        self.assertNotIn(marker,result.rust_source)
                    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        with self.subTest(optimized=optimized):
                            binary=root/(mode+('_release'if optimized else'_debug'))
                            build=subprocess.run(['rustc','--edition=2021','--crate-name','native_frame_tuple_comparison_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],input=stdin,capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                            self.assertEqual(actual.stdout,expected.stdout)
                            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                            self.assertEqual(canonical_error(actual.stderr),canonical_error(expected.stderr))


def _execution(source,stdin):
    def test(self):self.exercise(source,stdin)
    return test


for _name,_source,_stdin in CASES:
    setattr(FrameTupleComparisonExecutionTests,'test_'+_name,_execution(_source,_stdin))
