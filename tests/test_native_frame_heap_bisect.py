"""Canonical heap/bisection member calls use shared typed frame storage."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions

SOURCES={'heap_integer_class_storage': 'import heapq\n'
                               'class Queue:\n'
                               ' def __init__(self):self.values=[5,1,3]\n'
                               ' def run(self):\n'
                               '  heapq.heapify(self.values)\n'
                               '  heapq.heappush(self.values,2)\n'
                               '  return '
                               'heapq.heappop(self.values),heapq.heappushpop(self.values,4),heapq.heapreplace(self.values,8),self.values\n'
                               'print(Queue().run())\n',
 'heap_max_integer': 'import heapq\n'
                     'class Queue:\n'
                     ' def run(self,values):\n'
                     '  heapq.heapify_max(values)\n'
                     '  heapq.heappush_max(values,4)\n'
                     '  return '
                     'heapq.heappop_max(values),heapq.heappushpop_max(values,2),heapq.heapreplace_max(values,1),values\n'
                     'print(Queue().run([3,8,5]))\n',
 'heap_saved_callable_before_argument_rebind': 'from heapq import heappush,heappop\n'
                                               'operation=heappush\n'
                                               'values=[2]\n'
                                               'def item():\n'
                                               ' global operation\n'
                                               ' operation=heappop\n'
                                               ' print("item")\n'
                                               ' return 3\n'
                                               'class Queue:\n'
                                               ' def run(self):return operation(values,item())\n'
                                               'print(Queue().run(),values)\n'
                                               'print(operation(values),values)\n',
 'heap_item_mutates_captured_heap': 'from heapq import heappushpop\n'
                                    'values=[3]\n'
                                    'def change():\n'
                                    ' values.append(1)\n'
                                    ' return 2\n'
                                    'class Queue:\n'
                                    ' def run(self):return heappushpop(values,change())\n'
                                    'print(Queue().run(),values)\n',
 'heap_runtime_tuple_identity': 'from heapq import heappush,heappop\n'
                                'def pack(*items):return items\n'
                                'class Queue:\n'
                                ' def __init__(self):self.values=[]\n'
                                ' def add(self,item):heappush(self.values,item)\n'
                                ' def pop(self):return heappop(self.values)\n'
                                'queue=Queue()\n'
                                'first=pack(1,2)\n'
                                'second=pack(2,3)\n'
                                'queue.add(second)\n'
                                'queue.add(first)\n'
                                'print(queue.pop()is first,queue.pop()is second)\n',
 'heap_missing_argument_after_effect': 'import heapq\n'
                                       'def mark():\n'
                                       ' print("arg")\n'
                                       ' return []\n'
                                       'class Queue:\n'
                                       ' def run(self):heapq.heappush(mark())\n'
                                       'Queue().run()\n',
 'heap_unexpected_keyword_after_effect': 'import heapq\n'
                                         'def mark(x):\n'
                                         ' print("arg",x)\n'
                                         ' return x\n'
                                         'class Queue:\n'
                                         ' def '
                                         'run(self):heapq.heappush(mark([]),mark(3),bad=mark(4))\n'
                                         'Queue().run()\n',
 'heap_invalid_heap_none': 'import heapq\n'
                           'class Queue:\n'
                           ' def run(self,values):return heapq.heapify(values)\n'
                           'Queue().run(None)\n',
 'bisect_integer_class_storage': 'import bisect\n'
                                 'class Search:\n'
                                 ' def run(self,values):\n'
                                 '  '
                                 'result=bisect.bisect_left(values,3),bisect.bisect_right(values,3),bisect.bisect(values,4,lo=1,hi=None,key=None)\n'
                                 '  bisect.insort_left(values,3)\n'
                                 '  bisect.insort_right(values,4)\n'
                                 '  return result,values\n'
                                 'values=[1,3,3,5]\n'
                                 'print(Search().run(values),values)\n',
 'bisect_bounds_argument_effects': 'from bisect import bisect_left\n'
                                   'values=[1,3,5]\n'
                                   'def mark(label,value):\n'
                                   ' print(label)\n'
                                   ' return value\n'
                                   'class Search:\n'
                                   ' def run(self):return '
                                   'bisect_left(values,mark("item",4),hi=mark("hi",3),lo=mark("lo",1),key=None)\n'
                                   'print(Search().run())\n',
 'bisect_keyword_receiver_item': 'from bisect import bisect_left\n'
                                 'values=[1,3,5]\n'
                                 'def mark(label,value):\n'
                                 ' print(label)\n'
                                 ' return value\n'
                                 'class Search:\n'
                                 ' def run(self):return '
                                 'bisect_left(x=mark("item",3),a=mark("source",values),hi=None)\n'
                                 'print(Search().run())\n',
 'bisect_float_upper_bound_error': 'from bisect import bisect_left\n'
                                   'class Search:\n'
                                   ' def run(self,values,hi):return bisect_left(values,2,hi=hi)\n'
                                   'search=Search()\n'
                                   'print(search.run([1,3],None))\n'
                                   'search.run([1,3],1.5)\n',
 'bisect_nonindexable_owner_error_after_prefix': 'from bisect import bisect_left\n'
                                                 'class Search:\n'
                                                 ' def run(self,values):return '
                                                 'bisect_left(values,2)\n'
                                                 's=Search()\n'
                                                 'print(s.run([1,3]))\n'
                                                 's.run(7)\n',
 'bisect_generic_echo_incompatible_after_prefix': 'from bisect import bisect_left\n'
                                                  'def echo(value):return value\n'
                                                  'class Search:\n'
                                                  ' def run(self,values,item):return '
                                                  'bisect_left(echo(values),echo(item))\n'
                                                  's=Search()\n'
                                                  'print(s.run([1,3,5],3))\n'
                                                  's.run([1,3,5],[2])\n',
 'heap_pure_float_ordinary': 'from heapq import heapify,heappush,heappop\n'
                             'heap=[3.25,1.5]\n'
                             'heapify(heap)\n'
                             'heappush(heap,2.25)\n'
                             'print(heappop(heap),heap)\n'}

class NativeFrameHeapProofTests(unittest.TestCase):
    def test_ordinary_heaps_and_bisection_keep_their_direct_vector_backend(self):
        for source in('from heapq import heappush,heappop\nh=[]\nheappush(h,3)\nprint(heappop(h))\n',
                     'from bisect import bisect_left\nprint(bisect_left([1,3],2))\n'):
            with patch('py2fastrust.native_linked_frames.generate_linked',side_effect=AssertionError('ordinary vector path was redirected')):
                result=transpile(source)
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('native_frame_',result.rust_source)

    def test_custom_protocols_and_streams_remain_positioned_diagnostics(self):
        for source,detail in(
            ('import heapq\nclass Q:\n def run(self):return heapq.nlargest(2,[1,2])\nprint(Q().run())\n','stream/key'),
            ('from bisect import bisect_left\nclass S:\n def run(self):return bisect_left([1],1,key=lambda x:x)\nprint(S().run())\n','key'),
            ('from bisect import bisect_left\nclass S:\n def run(self):return bisect_left((1,3),2)\nprint(S().run())\n','sequence'),
            ('from bisect import bisect_left\nclass Index:\n def __index__(self):return 0\nclass S:\n def run(self):return bisect_left([1],1,Index())\nprint(S().run())\n','__index__')):
            for mode in('i64','i128','bigint'):
                with self.subTest(mode=mode,detail=detail):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    diagnostic=result.diagnostics[0]
                    self.assertEqual(diagnostic.code,'E006')
                    self.assertGreater(diagnostic.line,0)
                    self.assertIn(detail,str(diagnostic))

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeFrameHeapExecutionTests(unittest.TestCase):
    def compare(self,names):
        with tempfile.TemporaryDirectory(prefix='pytors-frame-heaps-')as directory:
            for name in names:
                source=SOURCES[name]
                expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=10)
                for mode in('i64','i128','bigint'):
                    with self.subTest(case=name,mode=mode):
                        with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                            result=transpile(source,TranspileOptions(integer=mode,filename='case.py',license='none'))
                        self.assertTrue(result.success,result.diagnostics)
                        self.assertEqual(result.backend,'native')
                        self.assertLess(len(result.rust_source.encode()),512*1024)
                        self.assertIsNone(re.search(r'\benum\s+(?:Value|Op)\b|\bstruct\s+(?:Runtime|PegParser)\b|\bfn\s+step\b',result.rust_source))
                        path=Path(directory)/(name+'_'+mode+'.rs');path.write_text(result.rust_source)
                        for release in(False,True):
                            binary=path.with_suffix('.opt'if release else'.debug')
                            build=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime','PYTHONPATH':'/no-python-runtime'})
                            self.assertEqual((actual.stdout,actual.returncode),(expected.stdout,expected.returncode),actual.stderr)
                            final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else''
                            self.assertEqual(final(actual.stderr),final(expected.stderr))
                            frames=lambda text:re.findall(r'File "[^"]+", line (\d+), in ([^\n]+)',text)
                            self.assertEqual(frames(actual.stderr),frames(expected.stderr))

    def test_heap_min_max_layout_and_captured_effects(self):
        self.compare(('heap_integer_class_storage','heap_max_integer','heap_saved_callable_before_argument_rebind','heap_item_mutates_captured_heap','heap_runtime_tuple_identity'))

    def test_heap_binding_errors_follow_argument_effects(self):
        self.compare(('heap_missing_argument_after_effect','heap_unexpected_keyword_after_effect','heap_invalid_heap_none'))

    def test_bisection_bounds_keywords_and_union_runtime_errors(self):
        self.compare(('bisect_integer_class_storage','bisect_bounds_argument_effects','bisect_keyword_receiver_item','bisect_float_upper_bound_error','bisect_nonindexable_owner_error_after_prefix','bisect_generic_echo_incompatible_after_prefix'))

    def test_pure_float_heap_does_not_require_integer_float_interoperation(self):
        self.compare(('heap_pure_float_ordinary',))

if __name__=='__main__':unittest.main()
