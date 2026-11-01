"""Shared enumerate cursors preserve source order and Python index timing."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'callable_alias_identity': 'make=enumerate\n'
                            'enumerate=lambda values:[8]\n'
                            'stream=make([1,2],3)\n'
                            'print(list(stream),enumerate([1]))\n',
 'classinfo_does_not_pull': 'def bad(v):return 1//0\n'
                            'stream=enumerate(map(bad,[1]))\n'
                            'print(isinstance(stream,enumerate),isinstance(stream,map))\n',
 'concrete_empty_source_stays_exhausted': 'rows=[]\n'
                                          'stream=enumerate(rows)\n'
                                          'print(next(stream,99))\n'
                                          'rows.append(8)\n'
                                          'print(list(stream))\n',
 'constructor_capture_order': 'def mark(label,v):\n'
                              ' print(label)\n'
                              ' return v\n'
                              'stream=enumerate(mark("source",[3,4]),start=mark("start",2))\n'
                              'print("created",list(stream))\n',
 'cross_source_consumption': 'source=iter([3,4,5,6])\n'
                             'stream=enumerate(source,7)\n'
                             'print(next(stream),next(source),list(stream))\n',
 'duplicate_start': 'print(enumerate([1],2,start=3))\n',
 'empty_callback_bottom': 'def stop(v):return next(iter(()))\n'
                          'stream=enumerate(map(stop,[1,2]),4)\n'
                          'print(list(stream),list(stream))\n',
 'empty_extrema_default': 'print(max(enumerate([]),key=lambda pair:pair[1],default=None))\n',
 'extra_positional': 'print(enumerate([1],2,3))\n',
 'extrema_key_consumer': 'values=[4,7,7,2]\n'
                         'print(max(enumerate(values),key=lambda pair:pair[1]))\n'
                         'print(min(enumerate(values),key=lambda pair:pair[1]))\n',
 'finite_source_alternatives': 'def collect(source):return list(enumerate(source,2))\n'
                               'print(collect([1,2]),collect((3,4)),collect(range(2)),collect(b"az"),collect("cd"))\n',
 'finite_start_alternatives': 'def collect(start):return list(enumerate([4,5],start))\n'
                              'print(collect(2),collect(True))\n',
 'index_validation_before_source': 'print(list(enumerate(3,1.5)))\n',
 'invalid_start': 'print(list(enumerate([1],1.5)))\n',
 'iterator_truth_and_tuple_fields': 'stream=enumerate([7,8],4)\n'
                                    'print(bool(stream),next(stream)[1],sum(v for i,v in '
                                    'stream),bool(stream))\n',
 'loop_and_comprehension': 'stream=enumerate([5,6,7],2)\n'
                           'for i,v in stream:\n'
                           ' print(i,v)\n'
                           ' if i==2:break\n'
                           'print([i+v for i,v in stream])\n',
 'missing_iterable': 'print(enumerate())\n',
 'next_default_does_not_advance': 'def visit(v):\n'
                                  ' if v==1:return next(iter(()))\n'
                                  ' return v\n'
                                  'stream=enumerate(map(visit,[1,2,3]),5)\n'
                                  'print(next(stream,99),next(stream),list(stream))\n',
 'noniterable_source': 'print(list(enumerate(3)))\n',
 'recursive_callback': 'def read(v):\n'
                       ' if v:return read(v-1)+1\n'
                       ' return 0\n'
                       'print(list(enumerate(map(read,[1,2,3]),4)))\n',
 'returned_iterator': 'def make(values,start=0):return enumerate(values,start)\n'
                      'stream=make([7,8],True)\n'
                      'print(next(stream),list(stream),list(make([4])))\n',
 'sorted_key_consumer': 'values=[4,7,7,2]\n'
                        'print(sorted(enumerate(values),key=lambda pair:-pair[1]))\n',
 'source_error_frames': 'def visit(v):return 1//v\n'
                        'print(list(enumerate(map(visit,[1,0]),3)))\n',
 'source_mutation': 'rows=[1]\n'
                    'stream=enumerate(rows,3)\n'
                    'rows.append(2)\n'
                    'print(next(stream))\n'
                    'rows.append(3)\n'
                    'print(list(stream))\n',
 'source_reentrant_next': 'def visit(v):\n'
                          ' print("call",v)\n'
                          ' if v==1:print("inside",next(stream))\n'
                          ' return v\n'
                          'stream=enumerate(map(visit,[1,2,3]),10)\n'
                          'print(list(stream))\n',
 'source_transient_stop_resumes': 'def visit(v):\n'
                                  ' if v==2:return next(iter(()))\n'
                                  ' return v\n'
                                  'source=map(visit,[1,2,3])\n'
                                  'stream=enumerate(source,4)\n'
                                  'print(list(stream),list(stream),list(source))\n',
 'start_keywords': 'print(list(enumerate([4,5],start=2)),list(enumerate(iterable=[6],start=3)))\n',
 'stored_aliases': 'stream=enumerate([4,5,6],3)\n'
                   'alias=stream\n'
                   'print(iter(stream) is '
                   'stream,next(alias),next(stream),list(alias),list(stream))\n',
 'unicode_source': 'print(list(enumerate("猫🐈é",3)))\n',
 'unknown_keyword': 'print(enumerate([1],bad=2))\n',
 'zip_sources': 'print(list(zip(enumerate([3,4],2),[8,9],strict=True)))\n'}


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class EnumerateTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_storage_aliases_and_source_shapes(self):
        for name in ('stored_aliases', 'start_keywords', 'returned_iterator', 'finite_source_alternatives', 'finite_start_alternatives', 'unicode_source', 'callable_alias_identity'):
            with self.subTest(name=name):self.check(name)

    def test_progress_resumability_and_reentrant_calls(self):
        for name in ('source_transient_stop_resumes', 'source_reentrant_next', 'next_default_does_not_advance', 'concrete_empty_source_stays_exhausted', 'source_mutation', 'cross_source_consumption', 'empty_callback_bottom', 'recursive_callback'):
            with self.subTest(name=name):self.check(name)

    def test_generic_consumers_and_classinfo(self):
        for name in ('loop_and_comprehension', 'zip_sources', 'sorted_key_consumer', 'extrema_key_consumer', 'empty_extrema_default', 'classinfo_does_not_pull', 'iterator_truth_and_tuple_fields'):
            with self.subTest(name=name):self.check(name)

    def test_construction_errors_and_argument_order(self):
        for name in ('constructor_capture_order', 'source_error_frames', 'noniterable_source', 'invalid_start', 'index_validation_before_source', 'missing_iterable', 'extra_positional', 'unknown_keyword', 'duplicate_start'):
            with self.subTest(name=name):self.check(name)

    def test_index_steps_follow_the_selected_integer_policy(self):
        source='stream=enumerate([4,5,6],9223372036854775807)\nprint(list(stream))\n'
        with tempfile.TemporaryDirectory(prefix='pytors-enumerate-width-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
                    result=transpile(source,TranspileOptions(integer=mode,license='none',filename='iterator_case.py'))
                self.assertTrue(result.success,result.diagnostics)
                rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
                expected=('[(9223372036854775807, 4), (-9223372036854775808, 5), (-9223372036854775807, 6)]\n'if mode=='i64'else'[(9223372036854775807, 4), (9223372036854775808, 5), (9223372036854775809, 6)]\n')
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021','--crate-name','enumerate_width',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    with self.subTest(mode=mode,optimized=optimized):self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected,''))
