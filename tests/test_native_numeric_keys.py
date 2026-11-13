"""Closed real numeric hash keys retain source objects, equality and errors."""
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile

CASES={'dict_numeric_representatives': 'mapping={}\n'
                                 "mapping[True]='bool'\n"
                                 "mapping[1.0]='float'\n"
                                 "mapping[1]='int'\n"
                                 "mapping[-0.0]='negative zero'\n"
                                 "mapping[False]='bool zero'\n"
                                 "mapping[0.0]='positive zero'\n"
                                 'print(list(mapping.items()))\n'
                                 'print(mapping[1.0],mapping[True],mapping[0],mapping[-0.0])\n',
 'dict_exact_precision': 'number=9007199254740993\n'
                         "mapping={number:'integer',9007199254740992.0:'float',1.5:'fraction'}\n"
                         'print(len(mapping),mapping[number],mapping[9007199254740992],mapping[1.5])\n'
                         'print(9007199254740993.0 in mapping,9007199254740994.0 in mapping)\n'
                         'print(list(mapping.items()))\n',
 'dict_fraction_inf_out_of_width': "large=float('1.2676506002282294e30')\n"
                                   "positive=float('inf')\n"
                                   "negative=float('-inf')\n"
                                   "mapping={large:'large',0:'zero',1.25:'fraction',positive:'positive',negative:'negative'}\n"
                                   'print(mapping[large],mapping[0],mapping[1.25],mapping[positive],mapping[negative])\n'
                                   'print(1 in mapping,-1 in mapping,0.25 in mapping)\n'
                                   'print(list(mapping.items()))\n',
 'dict_nan_aliases': "first=float('nan')\n"
                     "second=float('nan')\n"
                     "mapping={first:'first',second:'second'}\n"
                     "print(len(mapping),mapping[first],mapping[second],float('nan') in mapping)\n"
                     "mapping[float(first)]='replacement'\n"
                     'copy=mapping.copy()\n'
                     'print(len(mapping),copy[first],copy[second])\n'
                     'del mapping[first]\n'
                     'print(first in mapping,second in mapping,first in copy)\n'
                     'print(list(copy.values()))\n',
 'dict_tuple_nan_numeric': "shared=float('nan')\n"
                           "other=float('nan')\n"
                           'first=(True,(shared,1.5))\n'
                           'second=(1.0,(shared,1.5))\n'
                           'third=(1,(other,1.5))\n'
                           "mapping={first:'old',second:'replacement',third:'other'}\n"
                           'print(len(mapping),mapping[first],mapping[second],mapping[third])\n'
                           'print(list(mapping.values()))\n'
                           "print((1,(float('nan'),1.5)) in mapping)\n",
 'dict_cross_numeric_queries': "integers={0:'zero',1:'one',9007199254740993:'large'}\n"
                               "print(integers[0.0],integers[1.0],integers.get(9007199254740992.0,'absent'))\n"
                               "print(float('1.2676506002282294e30') in integers,float('inf') in "
                               "integers,float('nan') in integers)\n"
                               "floats={0.0:'zero',1.0:'one',9007199254740992.0:'large'}\n"
                               'print(floats[0],floats[True],9007199254740993 in floats)\n',
 'dict_finite_numeric_joins': 'def choose(flag):\n'
                              ' if flag:return 1.0\n'
                              ' return 1\n'
                              'mapping={}\n'
                              'for flag in (False,True):mapping[choose(flag)]=flag\n'
                              'print(len(mapping),list(mapping.items()),mapping[True])\n',
 'dict_partial_unhashable_update': "mapping={1.0:'old'}\n"
                                   "print('before',list(mapping.items()))\n"
                                   "mapping.update([(2.5,'added'),([], 'unreachable')])\n",
 'dict_query_effects': "mapping={1.0:'value'}\n"
                       'def owner():\n'
                       " print('owner')\n"
                       ' return mapping\n'
                       'def key():\n'
                       " print('key')\n"
                       ' return []\n'
                       "print('before')\n"
                       'print(owner()[key()])\n',
 'set_mixed_tuple_keys': 'items=set([(1,1.5),(1.0,1.5),(True,1.5),(2.0,-0.0),(2,0)])\n'
                         'print(list(items))\n'
                         'print((1,1.5) in items,(2.0,False) in items)\n',
 'set_float_literals': 'items={0.0,1.5,2.0,-1.5,True,2}\n'
                       'print(list(items))\n'
                       "for value in {0.0,1.5,2.0,-1.5,True,2}:print(value,end='|')\n"
                       'print()\n',
 'set_nan_contents_only': "first=float('nan')\n"
                          "second=float('nan')\n"
                          'items=set([first,first,second])\n'
                          "print(len(items),first in items,second in items,float('nan') in items)\n"
                          'items.remove(first)\n'
                          'print(len(items),first in items,second in items)\n',
 'set_partial_unhashable': "items=set([0.5])\nprint('before',len(items))\nitems.update([2.5,[]])\n",
 'float_dict_comprehension': 'mapping={float(index):index*3 for index in range(5)}\n'
                             'print(list(mapping.items()),mapping[True],mapping[4])\n',
 'numeric_set_literal_history': 'items=set([0.0,1.5,-1.5,2.0,True])\n'
                                'print(list(items))\n'
                                'items.remove(1.5)\n'
                                'items.add(7.25)\n'
                                'print(list(items))\n'
                                'copy=items.copy()\n'
                                'items.clear()\n'
                                'items.update([2.0,1.5,-1.5])\n'
                                'print(list(items),list(copy))\n',
 'captured_numeric_mapping_methods': "mapping={1.0:'original'}\n"
                                     'read=mapping.get\n'
                                     'ensure=mapping.setdefault\n'
                                     'remove=mapping.pop\n'
                                     'update=mapping.update\n'
                                     "print(read(True),ensure(1,'new'),ensure(2.5,'added'))\n"
                                     "update([(False,'zero'),(0.0,'replacement')])\n"
                                     'print(remove(2.5),list(mapping.items()))\n',
 'numeric_counter_defaultdict': 'from collections import Counter,defaultdict\n'
                                'values=Counter([1.0,True,1,2.5,2.5])\n'
                                'print(list(values.items()),values[1],values[2.5])\n'
                                'counts=defaultdict(int)\n'
                                'counts[1.5]+=2\n'
                                'counts[True]+=3\n'
                                'counts[1.0]+=4\n'
                                'print(list(counts.items()),counts[1])\n',
 'tuple_runtime_key_queries': "value=float('nan')\n"
                              'key=tuple([value,1.5])\n'
                              "mapping={key:'stored'}\n"
                              "print(mapping[(value,1.5)],(float('nan'),1.5) in mapping)\n"
                              "print(mapping.get(tuple([value,1.5]),'absent'))\n",
 'nested_union_tuple_keys': 'def key(flag):\n'
                            ' if flag:return ((1.0,2.5),3.0)\n'
                            ' return ((True,2.5),3)\n'
                            "mapping={key(False):'first',key(True):'last'}\n"
                            'print(len(mapping),list(mapping.items()),mapping[((1,2.5),3)])\n',
 'float_query_shadowed_dict': 'def dict(value):return value+1.0\nprint(dict(1.5))\n',
 'int_dictionary_float_values_control': 'mapping={1:2.5,2:1.5}\n'
                                        'print(list(mapping.items()),mapping[1]+mapping[2])\n',
 'tuple_numeric_literal_control': 'mapping={(1,2):3,(4,5):6}\n'
                                  'print(mapping[(1,2)],list(mapping.items()))\n',
 'dict_generator_partial_mutation': "mapping={1.0:'old'}\n"
                                    'def pairs():\n'
                                    " yield(2.5,'added')\n"
                                    " print('after first',list(mapping.items()))\n"
                                    " yield([],'unreachable')\n"
                                    'mapping.update(pairs())\n',
 'set_generator_partial_mutation': "shared=float('nan')\n"
                                   'items=set([shared])\n'
                                   'def values():\n'
                                   ' yield 2.5\n'
                                   " print('after first',len(items),shared in items,2.5 in items)\n"
                                   ' yield []\n'
                                   'items.update(values())\n',
 'nan_set_merge_and_copy': "shared=float('nan')\n"
                           "other=float('nan')\n"
                           'left=set([shared,1.0])\n'
                           'right=set([shared,other,True])\n'
                           'left.update(right)\n'
                           'copy=left.copy()\n'
                           'right.clear()\n'
                           'left.remove(shared)\n'
                           'print(len(left),shared in left,other in left,1 in left)\n'
                           'print(len(copy),shared in copy,other in copy,True in copy)\n',
 'seeded_numeric_text_tuple_keys': "items=set([(1,'key'),(1.0,'key'),(2.0,'other'),(3.5,'more')])\n"
                                   'print(list(items))\n'
                                   "items.remove((True,'key'))\n"
                                   "items.add((4.5,'extra'))\n"
                                   'print(list(items))\n',
 'numeric_tuple_arity_13': 'first=(1,2,3,4,5,6,7,8,9,10,11,12,13)\n'
                           'second=(1.0,2,3.0,4,5.0,6,7.0,8,9.0,10,11.0,12,13.0)\n'
                           "mapping={first:'first',second:'last'}\n"
                           'print(len(mapping),mapping[first],mapping[second])\n',
 'key_producer_shadow_control': 'def float(value):return value+1\n'
                                'mapping={float(1):2}\n'
                                'print(list(mapping.items()))\n',
 'integral_only_set_control': 'items={0,8,16,24}\nprint(list(items),0 in items)\n'}

BOUNDARIES={'set_finite_history': ("values=[0.0,-0.0,1.5,-1.5,2.0,True,9007199254740993,9007199254740992.0,float('inf'),float('-inf')]\n"
                        'items=set(values)\n'
                        'print(list(items))\n'
                        'items.remove(1.5)\n'
                        'items.add(7.25)\n'
                        'print(list(items))\n'
                        'copy=items.copy()\n'
                        'items.clear()\n'
                        'items.update([2.0,1.5,-1.5])\n'
                        'print(list(items),list(copy))\n',
                        'NaN'),
 'set_nan_order_observed': ("first=float('nan')\n"
                            "second=float('nan')\n"
                            'items=set([first,second,1.5])\n'
                            'for value in items:\n'
                            " if value==value:print('number')\n"
                            " elif value is first:print('first')\n"
                            " else:print('second')\n",
                            'NaN'),
 'caught_dict_partial_mutation': ("mapping={1.0:'old'}\n"
                                  'try:\n'
                                  " mapping.update([(2.5,'added'),([],'unreachable')])\n"
                                  'except TypeError:\n'
                                  " print('caught',list(mapping.items()))\n",
                                  'exception-handler'),
 'caught_set_partial_mutation': ('items=set([0.5])\n'
                                 'try:\n'
                                 ' items.update([2.5,[]])\n'
                                 'except TypeError:\n'
                                 " print('caught',len(items),0.5 in items,2.5 in items)\n",
                                 'exception-handler'),
 'mutable_later_nan_guard': ('items={0.5,1.5}\n'
                             'print(list(items))\n'
                             "items.add(float('nan'))\n"
                             'print(list(items))\n',
                             'NaN'),
 'set_nan_pop_guard': ("value=float('nan')\nitems=set([value,1.5])\nprint(items.pop())\n", 'NaN'),
 'set_nan_nested_display_guard': ("value=float('nan')\n"
                                  'items=set([value,1.5])\n'
                                  "print({'nested':[items]})\n",
                                  'NaN'),
 'numeric_mapping_equality_boundary': ('first={1.0:2}\nsecond={1:2}\nprint(first==second)\n', None),
 'numeric_set_subset_boundary': ('first={1.0}\nsecond={1,2}\nprint(first<second)\n', None)}

CONTROLS={'float_query_shadowed_dict': 'def dict(value):return value+1.0\nprint(dict(1.5))\n',
 'int_dictionary_float_values_control': 'mapping={1:2.5,2:1.5}\n'
                                        'print(list(mapping.items()),mapping[1]+mapping[2])\n',
 'tuple_numeric_literal_control': 'mapping={(1,2):3,(4,5):6}\n'
                                  'print(mapping[(1,2)],list(mapping.items()))\n',
 'key_producer_shadow_control': 'def float(value):return value+1\n'
                                'mapping={float(1):2}\n'
                                'print(list(mapping.items()))\n',
 'integral_only_set_control': 'items={0,8,16,24}\nprint(list(items),0 in items)\n'}

class NumericKeyProofTests(unittest.TestCase):
    def test_unproved_protocols_retain_positioned_diagnostics(self):
        for name,(source,reason)in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none'))
                    self.assertFalse(result.success,result.diagnostics)
                    self.assertTrue(any(d.code=='E006'and d.line>0 and(reason is None or reason in d.message)for d in result.diagnostics),result.diagnostics)

    def test_ordinary_non_key_float_programs_have_no_numeric_key_carrier(self):
        for name,source in CONTROLS.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none'))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertNotIn('NativeNumericKey',result.rust_source)
                    self.assertNotIn('native_cp_hash_float',result.rust_source)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NumericKeyExecutionTests(unittest.TestCase):
    def check(self,name):
        source=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-numeric-keys-')as directory:
            root=Path(directory);program=root/'case.py';program.write_text(source)
            expected={}
            for seed in ('0','1','314159','4294967295'):
                expected[seed]=subprocess.run([sys.executable,'-B','-S',str(program)],text=True,capture_output=True,env={**os.environ,'PYTHONHASHSEED':seed},timeout=20)
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename=str(program),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):self.assertNotIn(marker,result.rust_source)
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+str(optimized))
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for seed,reference in expected.items():
                        with self.subTest(name=name,integer=mode,optimized=optimized,seed=seed):
                            actual=subprocess.run([str(binary)],text=True,capture_output=True,env={**os.environ,'PYTHONHASHSEED':seed,'PATH':'/no-python-runtime'},timeout=20)
                            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                            if reference.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1:],reference.stderr.splitlines()[-1:])
                                frames=lambda value:re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',value)
                                self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                            else:self.assertEqual(actual.stderr,'')

    def test_integer_parser_normalization_never_wraps_float_keys_or_queries(self):
        source="""integer=int(input())
floating=float(input())
mapping={integer:'integer',floating:'floating'}
only={integer:'only'}
print(len(mapping),mapping[integer],mapping[floating],integer==floating,floating in only)
"""
        pairs=[(1<<64,str(float(1<<64))),(-(1<<64),str(-float(1<<64))),(1<<128,str(float(1<<128))),(-(1<<128),str(-float(1<<128))),((1<<53)+1,str(float(1<<53))),((1<<127)-1,str(float(1<<127))),(-(1<<127),str(-float(1<<127))),(int(sys.float_info.max),str(sys.float_info.max)),(0,'-0.0'),(314159,'inf')]
        with tempfile.TemporaryDirectory(prefix='pytors-numeric-width-')as directory:
            root=Path(directory);program=root/'case.py';program.write_text(source)
            for mode,width in (('i64',64),('i128',128),('bigint',0)):
                converted=transpile(source,TranspileOptions(integer=mode,filename=str(program),license='none'))
                self.assertTrue(converted.success,converted.diagnostics)
                rust=root/(mode+'.rs');rust.write_text(converted.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+str(optimized));built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180);self.assertEqual(built.returncode,0,built.stderr)
                    for integer,floating in pairs:
                        normalized=integer if width==0 else((integer+(1<<(width-1)))%(1<<width))-(1<<(width-1))
                        # The source and float input are unchanged. The CP
                        # reference receives the selected-width integer value.
                        reference=subprocess.run([sys.executable,'-B','-S',str(program)],input=str(normalized)+'\n'+floating+'\n',text=True,capture_output=True,timeout=20)
                        actual=subprocess.run([str(binary)],input=str(integer)+'\n'+floating+'\n',text=True,capture_output=True,env={**os.environ,'PATH':'/no-python-runtime'},timeout=20)
                        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(reference.returncode,reference.stdout,reference.stderr),(mode,integer,floating))

    def test_dict_numeric_representatives(self):
        self.check('dict_numeric_representatives')

    def test_dict_exact_precision(self):
        self.check('dict_exact_precision')

    def test_dict_fraction_inf_out_of_width(self):
        self.check('dict_fraction_inf_out_of_width')

    def test_dict_nan_aliases(self):
        self.check('dict_nan_aliases')

    def test_dict_tuple_nan_numeric(self):
        self.check('dict_tuple_nan_numeric')

    def test_dict_cross_numeric_queries(self):
        self.check('dict_cross_numeric_queries')

    def test_dict_finite_numeric_joins(self):
        self.check('dict_finite_numeric_joins')

    def test_dict_partial_unhashable_update(self):
        self.check('dict_partial_unhashable_update')

    def test_dict_query_effects(self):
        self.check('dict_query_effects')

    def test_set_mixed_tuple_keys(self):
        self.check('set_mixed_tuple_keys')

    def test_set_float_literals(self):
        self.check('set_float_literals')

    def test_set_nan_contents_only(self):
        self.check('set_nan_contents_only')

    def test_set_partial_unhashable(self):
        self.check('set_partial_unhashable')

    def test_float_dict_comprehension(self):
        self.check('float_dict_comprehension')

    def test_numeric_set_literal_history(self):
        self.check('numeric_set_literal_history')

    def test_captured_numeric_mapping_methods(self):
        self.check('captured_numeric_mapping_methods')

    def test_numeric_counter_defaultdict(self):
        self.check('numeric_counter_defaultdict')

    def test_tuple_runtime_key_queries(self):
        self.check('tuple_runtime_key_queries')

    def test_nested_union_tuple_keys(self):
        self.check('nested_union_tuple_keys')

    def test_float_query_shadowed_dict(self):
        self.check('float_query_shadowed_dict')

    def test_int_dictionary_float_values_control(self):
        self.check('int_dictionary_float_values_control')

    def test_tuple_numeric_literal_control(self):
        self.check('tuple_numeric_literal_control')

    def test_dict_generator_partial_mutation(self):
        self.check('dict_generator_partial_mutation')

    def test_set_generator_partial_mutation(self):
        self.check('set_generator_partial_mutation')

    def test_nan_set_merge_and_copy(self):
        self.check('nan_set_merge_and_copy')

    def test_seeded_numeric_text_tuple_keys(self):
        self.check('seeded_numeric_text_tuple_keys')

    def test_numeric_tuple_arity_13(self):
        self.check('numeric_tuple_arity_13')

    def test_key_producer_shadow_control(self):
        self.check('key_producer_shadow_control')

    def test_integral_only_set_control(self):
        self.check('integral_only_set_control')

if __name__=='__main__':unittest.main()
