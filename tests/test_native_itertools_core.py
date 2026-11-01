"""Canonical itertools calls emit concrete lazy states, with shared aliases."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'canonical_iterator_classes': 'from itertools import repeat,chain,islice,pairwise\n'
                               'streams=(repeat(1,2),chain([2]),islice([3],1),pairwise([4,5]))\n'
                               'print(isinstance(streams[0],repeat),isinstance(streams[1],chain),isinstance(streams[2],islice),isinstance(streams[3],pairwise))\n'
                               'print(isinstance(streams[0],pairwise),isinstance([1],repeat),isinstance(streams[0],(pairwise,repeat)))\n',
 'chain_append_during_iteration': 'from itertools import chain\n'
                                  'rows=[1]\n'
                                  'for v in chain(rows,[9]):\n'
                                  ' print(v)\n'
                                  ' if v==1:rows.append(2)\n'
                                  'print(rows)\n',
 'chain_callback_stop_skips_source': 'from itertools import chain\n'
                                     'def call(v):\n'
                                     ' if v==2:return next(iter(()))\n'
                                     ' return v\n'
                                     'source=map(call,[1,2,3])\n'
                                     'stream=chain(source,[9])\n'
                                     'print(list(stream),list(source))\n',
 'chain_empty': 'from itertools import chain\n'
                'stream=chain()\n'
                'print(list(stream),next(stream,99))\n',
 'chain_invalid_is_lazy': 'from itertools import chain\n'
                          'stream=chain([1],3,[9])\n'
                          'print("created",next(stream))\n'
                          'print(next(stream))\n',
 'chain_mixed_values': 'from itertools import chain\n'
                       'print(list(chain([1,2],"ab",(True,),b"AZ")))\n',
 'chain_mutations': 'from itertools import chain\n'
                    'a=[1]\n'
                    'b=[3]\n'
                    'stream=chain(a,b)\n'
                    'a.append(2)\n'
                    'print(next(stream))\n'
                    'b.append(4)\n'
                    'print(list(stream))\n',
 'chain_order_resume': 'from itertools import chain\n'
                       'stream=chain([1,2],(),range(3,5),(5,6))\n'
                       'print(next(stream),next(stream),list(stream),list(stream))\n',
 'chain_reentrant_callback': 'from itertools import chain\n'
                             'def visit(v):\n'
                             ' print("call",v)\n'
                             ' if v==1:print("inside",next(stream,99))\n'
                             ' return v\n'
                             'stream=chain(map(visit,[1,2,3]),[8,9])\n'
                             'print(list(stream))\n',
 'class_alias_keeps_identity': 'from itertools import repeat,pairwise\n'
                               'constructor=repeat\n'
                               'repeat=3\n'
                               'stream=constructor(1,2)\n'
                               'print(isinstance(stream,constructor),isinstance(stream,pairwise),list(stream))\n',
 'class_queries_do_not_consume': 'from itertools import chain,pairwise\n'
                                 'def mark(v):\n'
                                 ' print("call",v)\n'
                                 ' return v\n'
                                 'stream=chain(map(mark,[1,2]),[3])\n'
                                 'print(isinstance(stream,chain),isinstance(stream,pairwise))\n'
                                 'print(list(stream))\n',
 'class_tuple_short_circuit': 'from itertools import repeat,chain\n'
                              'stream=repeat(1,2)\n'
                              'print(isinstance(stream,(repeat,3)))\n'
                              'print(isinstance(stream,(chain,3)))\n',
 'composition': 'from itertools import chain,islice,pairwise,repeat\n'
                'stream=chain(repeat(3,2),range(4,8))\n'
                'print(list(pairwise(islice(stream,1,None))),list(stream))\n',
 'constructor_rebound_canonical_identity': 'import itertools\n'
                                           'make=itertools.repeat\n'
                                           'itertools.repeat=lambda a,b:[a+b]\n'
                                           'print(list(make(2,3)),itertools.repeat(2,3))\n',
 'consumer_strict_zip': 'from itertools import repeat,pairwise\n'
                        'print(list(zip(repeat(1,2),pairwise([3,4,5]),strict=True)))\n',
 'empty_callback_bottom': 'from itertools import islice,pairwise\n'
                          'def die(v):return next(iter(()))\n'
                          'print(list(islice(map(die,[0]),None)),list(pairwise(map(die,[1]))))\n',
 'finite_stop_alternatives': 'from itertools import islice\n'
                             'def values(stop):return list(islice(range(5),1,stop))\n'
                             'print(values(3),values(None))\n',
 'islice_basic': 'from itertools import islice\n'
                 'source=iter(list(range(12)))\n'
                 'stream=islice(source,2,9,3)\n'
                 'print(next(stream),list(stream),list(source))\n',
 'islice_capture_order': 'from itertools import islice\n'
                         'def mark(name,value):\n'
                         ' print(name)\n'
                         ' return value\n'
                         'stream=islice(mark("source",[1,2,3]),mark("start",1),mark("stop",3))\n'
                         'print("created",list(stream))\n',
 'islice_empty_advances': 'from itertools import islice\n'
                          'source=iter(list(range(10)))\n'
                          'print(list(islice(source,5,2)),list(source))\n',
 'islice_fused_callback_stop': 'from itertools import islice\n'
                               'def call(v):\n'
                               ' if v==2:return next(iter(()))\n'
                               ' return v\n'
                               'source=map(call,[1,2,3])\n'
                               'stream=islice(source,None)\n'
                               'print(list(stream),list(stream),list(source))\n',
 'islice_invalid_start': 'from itertools import islice\nprint(list(islice([1],-1,3)))\n',
 'islice_invalid_step': 'from itertools import islice\nprint(list(islice([1],0,3,0)))\n',
 'islice_invalid_stop': 'from itertools import islice\nprint(list(islice([1],2.5)))\n',
 'islice_reentrant_callback': 'from itertools import islice\n'
                              'def visit(v):\n'
                              ' print("call",v)\n'
                              ' if v==1:print("inside",next(stream,99))\n'
                              ' return v\n'
                              'stream=islice(map(visit,[1,2,3,4,5,6,7,8]),1,7,2)\n'
                              'print(list(stream))\n',
 'islice_stop_none': 'from itertools import islice\n'
                     'print(list(islice(range(8),None)),list(islice(range(8),2,None,2)))\n',
 'iterator_type_error_names': 'from itertools import repeat\n'
                              'stream=repeat(1,2)\n'
                              'print(int(stream))\n',
 'nonstop_exception_frames': 'from itertools import pairwise,islice\n'
                             'def div(v):return 12//v\n'
                             'print(list(pairwise(islice(map(div,[1,2,0,4]),None))))\n',
 'ordinary_loops_and_comprehensions': 'from itertools import chain,islice,pairwise,repeat\n'
                                      'print([a+b for a,b in '
                                      'pairwise(chain([1],repeat(2,3)))])\n'
                                      'for index,value in '
                                      'enumerate(islice(range(10),1,7,2),5):print(index,value)\n',
 'pairwise_basic': 'from itertools import pairwise\n'
                   'stream=pairwise([2,4,7,11])\n'
                   'print(next(stream),list(stream),list(stream))\n',
 'pairwise_empty_singleton': 'from itertools import pairwise\n'
                             'print(list(pairwise(())),list(pairwise([1])),next(pairwise([]),99))\n',
 'pairwise_fused_callback_stop': 'from itertools import pairwise\n'
                                 'def call(v):\n'
                                 ' if v==2:return next(iter(()))\n'
                                 ' return v\n'
                                 'source=map(call,[1,2,3,4])\n'
                                 'stream=pairwise(source)\n'
                                 'print(list(stream),list(stream),list(source))\n',
 'pairwise_mutable_payloads': 'from itertools import pairwise\n'
                              'a=[1]\n'
                              'b=[2]\n'
                              'c=[3]\n'
                              'pairs=list(pairwise([a,b,c]))\n'
                              'pairs[0][1].append(8)\n'
                              'print(a,b,c,pairs,pairs[0][1] is pairs[1][0])\n',
 'pairwise_reentrant_callback': 'from itertools import pairwise\n'
                                'def visit(v):\n'
                                ' print("call",v)\n'
                                ' if v==1:print("inside",next(stream,99))\n'
                                ' return v\n'
                                'stream=pairwise(map(visit,[1,2,3,4,5,6]))\n'
                                'print(list(stream))\n',
 'repeat_argument_effects': 'from itertools import repeat\n'
                            'def mark(x):\n'
                            ' print(x)\n'
                            ' return x\n'
                            'print(repeat(mark(1),mark(2),mark(3)))\n',
 'repeat_finite': 'from itertools import repeat\n'
                  'stream=repeat(7,3)\n'
                  'print(next(stream),list(stream),list(stream))\n',
 'repeat_infinite_alias': 'from itertools import repeat\n'
                          'make=repeat\n'
                          'stream=make(9)\n'
                          'other=stream\n'
                          'print(next(stream),next(other),iter(stream) is stream)\n',
 'repeat_invalid_count': 'from itertools import repeat\nprint(list(repeat(1,1.5)))\n',
 'repeat_keyword': 'import itertools as it\n'
                   'print(list(it.repeat(object=3,times=2)),list(it.repeat(4,times=-2)),list(it.repeat(8,False)))\n',
 'repeat_mutable_shared': 'from itertools import repeat\n'
                          'row=[1]\n'
                          'rows=list(repeat(row,3))\n'
                          'rows[1].append(5)\n'
                          'print(row,rows,rows[0] is rows[2])\n',
 'shared_cursor_consumers': 'from itertools import chain,repeat,pairwise,islice\n'
                            'source=iter([1,2,3,4])\n'
                            'print(list(zip(islice(source,2),chain(source,repeat(9,2)))))\n',
 'unicode_sources': 'from itertools import chain,islice,pairwise\n'
                    'print(list(pairwise(chain("猫🐈","😀a"))),list(islice("😀猫éa",1,None,2)))\n'}


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ItertoolsCoreTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_repeat(self):
        for name in ('repeat_finite', 'repeat_infinite_alias', 'repeat_mutable_shared', 'repeat_keyword', 'repeat_invalid_count', 'repeat_argument_effects'):
            with self.subTest(name=name):self.check(name)

    def test_chain(self):
        for name in ('chain_order_resume', 'chain_mixed_values', 'chain_mutations', 'chain_invalid_is_lazy', 'chain_callback_stop_skips_source', 'chain_empty'):
            with self.subTest(name=name):self.check(name)

    def test_islice(self):
        for name in ('islice_basic', 'islice_stop_none', 'islice_empty_advances', 'islice_capture_order', 'islice_invalid_start', 'islice_invalid_stop', 'islice_invalid_step', 'islice_fused_callback_stop'):
            with self.subTest(name=name):self.check(name)

    def test_pairwise(self):
        for name in ('pairwise_basic', 'pairwise_empty_singleton', 'pairwise_mutable_payloads', 'pairwise_fused_callback_stop'):
            with self.subTest(name=name):self.check(name)

    def test_composition_identity_and_unicode(self):
        for name in ('composition', 'ordinary_loops_and_comprehensions', 'consumer_strict_zip', 'finite_stop_alternatives', 'empty_callback_bottom', 'unicode_sources', 'shared_cursor_consumers', 'nonstop_exception_frames', 'constructor_rebound_canonical_identity', 'iterator_type_error_names'):
            with self.subTest(name=name):self.check(name)

    def test_reentrant_and_mutating_sources(self):
        for name in ('islice_reentrant_callback', 'pairwise_reentrant_callback', 'chain_reentrant_callback', 'chain_append_during_iteration'):
            with self.subTest(name=name):self.check(name)

    def test_classinfo_queries(self):
        for name in ('canonical_iterator_classes', 'class_queries_do_not_consume', 'class_tuple_short_circuit', 'class_alias_keeps_identity'):
            with self.subTest(name=name):self.check(name)

    def test_fixed_width_normalization_precedes_structural_count(self):
        source='from itertools import repeat\nprint(list(repeat(1,2**100)))\n'
        with tempfile.TemporaryDirectory(prefix='pytors-repeat-count-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
                    result=transpile(source,TranspileOptions(integer=mode,license='none',filename='iterator_case.py'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021','--crate-name','repeat_count',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    with self.subTest(mode=mode,optimized=optimized):
                        if mode=='i64':self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,'[]\n',''))
                        else:
                            self.assertEqual((actual.returncode,actual.stdout),(1,''))
                            self.assertEqual(actual.stderr.splitlines()[-1],'OverflowError: Python int too large to convert to C ssize_t')
