"""Stable typed floating sorts retain Python less-than, aliases and effects."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile

CASES={'scalar_unordered': ("values=[float('nan'),3.0,2.0,float('nan'),1.0,-0.0,0.0,float('-inf'),float('inf')]\n"
                      'print(sorted(values))\n'
                      'values.sort(reverse=True)\n'
                      'print(values)\n',
                      ('',)),
 'tuple_shared_nan': ("shared=float('nan')\n"
                      "other=float('nan')\n"
                      "values=[(shared,3),(shared,1),(other,0),(shared,2),(float('nan'),-1)]\n"
                      'print([item[1]for item in sorted(values)])\n'
                      'print([item[1]for item in sorted(values,reverse=True)])\n',
                      ('',)),
 'nested_list_shared_nan': ("shared=float('nan')\n"
                            "other=float('nan')\n"
                            'values=[[shared,3],[shared,1],[other,0],[shared,2]]\n'
                            'print([item[1]for item in sorted(values)])\n'
                            'values.sort(reverse=True)\n'
                            'print([item[1]for item in values])\n',
                            ('',)),
 'mixed_numeric_exact': ("values=[9007199254740993,9007199254740992.0,True,1.0,False,-0.0,1.5,float('-inf'),float('inf'),-9007199254740993,-9007199254740992.0]\n"
                         'print(sorted(values))\n'
                         'print(sorted(values,reverse=True))\n',
                         ('',)),
 'keyed_callback_effects': ("values=[(2.0,'first'),(-0.0,'zero'),(2.0,'last'),(float('nan'),'nan'),(1.0,'one')]\n"
                            'def key(value):\n'
                            " print(len(values),value[1],end='|')\n"
                            ' return value[0]\n'
                            'values.sort(key=key,reverse=True)\n'
                            'print()\n'
                            'print([value[1]for value in values])\n',
                            ('',)),
 'sorted_alias': ("order=sorted\nvalues=[2.0,1.0,float('nan'),-1.0]\nprint(order(values))\n",
                  ('',)),
 'comparison_key_float_result': ('from functools import cmp_to_key\n'
                                 "shared=float('nan')\n"
                                 'print((shared,1)==(shared,1))\n'
                                 'values=[3.0,-1.0,2.0,2.0]\n'
                                 'print(sorted(values,key=cmp_to_key(lambda a,b:a-b)))\n',
                                 ('',)),
 'empty_float_sort_key_cold': ('def key(value):\n'
                               " print('must not run')\n"
                               ' return value+0.5\n'
                               'values=[]\n'
                               'values.sort(key=key)\n'
                               'print(values,sorted([],key=7))\n',
                               ('',)),
 'float_incompatible_type_error': ("print('before')\nvalues=[1.5,None]\nprint(sorted(values))\n",
                                   ('',)),
 'float_sort_input': ("shared=float('nan')\n"
                      "other=float('nan')\n"
                      'values=[]\n'
                      'for token in input().split():\n'
                      " if token=='a':value=shared\n"
                      " elif token=='b':value=other\n"
                      ' else:value=float(token)\n'
                      ' values.append((value,len(values)))\n'
                      'print([entry[1]for entry in sorted(values)])\n'
                      'print([entry[1]for entry in sorted(values,reverse=True)])\n',
                      ('\n',
                       'b\n',
                       '-3.5 1.5\n',
                       '2 1 1.5\n',
                       'nan 1 a 1 -3.5\n',
                       '0.0 -inf nan a 0.0 2 inf 1.5\n',
                       '0.0 0.0 -inf -1 -3.5 -3.5 1 nan inf 1.5 2 -3.5 -0.0 -3.5 0.0 1\n',
                       '-1 -inf b inf nan 2 -0.0 nan 1 inf 0.0 inf inf nan 2 b -3.5 nan b -0.0 1.5 '
                       'nan inf -0.0 inf nan 1 -1 nan nan 0.0\n',
                       '-inf -1 nan -3.5 nan a nan 0.0 1 1.5 0.0 -0.0 0.0 2 nan -0.0 2 -0.0 2 -0.0 '
                       '1.5 -3.5 1 1 nan -0.0 1 b -inf 1.5 inf -inf\n',
                       '1 -3.5 1 1.5 -0.0 -1 -3.5 2 2 1 1 2 inf -3.5 inf a -inf -inf 0.0 -0.0 -3.5 '
                       '0.0 inf 0.0 nan 1.5 -1 1.5 -0.0 -0.0 nan a b\n',
                       '0.0 nan inf 1 0.0 b b -inf -3.5 1 nan 1.5 -3.5 -inf nan 1.5 2 -inf -1 -inf '
                       '-1 1 b inf a a -1 -0.0 b 1 -0.0 nan a inf nan -1 a b 1 1 -1 inf 1 -inf -1 '
                       '1.5 2 b 0.0 -3.5 -0.0 -1 -0.0 -inf a -inf -1 inf 1.5 inf inf a -inf\n',
                       '2 1.5 -1 -1 nan nan nan 0.0 nan 2 -1 -3.5 -inf b 0.0 a inf a 2 -1 -3.5 -1 '
                       'a -1 -1 0.0 1.5 inf a nan 2 a -0.0 -0.0 0.0 -1 -1 -1 0.0 inf 2 2 0.0 -0.0 '
                       'nan -1 1 1.5 -inf 1.5 inf 1 0.0 2 nan 1 0.0 0.0 b nan -3.5 inf inf 2\n',
                       '-inf nan 1 0.0 -inf a 2 a 2 b 1 -3.5 1 b 2 -0.0 -3.5 -0.0 a -inf -3.5 b 1 '
                       'b -3.5 1.5 -1 b -1 inf -1 -1 nan 0.0 b b 1 1 b a 0.0 -inf -1 -0.0 inf b 1 '
                       '-0.0 -inf 0.0 -1 2 1 1.5 1 nan nan -1 a -3.5 b b b -1 inf\n',
                       'b 1.5 0.0 nan b -3.5 0.0 -0.0 b 1.5 2 0.0 1.5 1.5 0.0 -1 b a -3.5 -1 b 1 b '
                       '1 b 0.0 b 1 1 -0.0 2 -0.0 inf inf -3.5 1 nan 2 -0.0 2 inf nan 1.5 -3.5 1.5 '
                       '-0.0 1 -inf -inf -0.0 inf -inf 1 -1 inf -1 -3.5 inf -inf 2 inf -inf -0.0 '
                       '0.0 inf inf 0.0 -3.5 b b 1.5 nan b -0.0 1 -inf inf 0.0 -3.5 b 2 b a -inf '
                       '-1 -0.0 -1 b -3.5 inf 2 1.5 -0.0 0.0 a nan a 2 nan 0.0\n',
                       '-0.0 1.5 0.0 -1 0.0 1.5 2 1 nan a 1 nan b -3.5 -0.0 1 a -inf 2 0.0 nan b '
                       'inf nan a b -inf 1.5 1.5 1 inf 0.0 -3.5 -3.5 inf 1 0.0 a -inf -0.0 -inf -1 '
                       '1.5 inf 2 0.0 nan 2 -1 -0.0 -3.5 inf 0.0 1.5 b 0.0 nan -1 0.0 nan -inf 1 b '
                       '-0.0 b a -inf a nan b -1 1.5 0.0 -3.5 nan inf -3.5 1 -1 -inf -1 1.5 -1 b 1 '
                       '1.5 b -3.5 -1 0.0 -3.5 nan b 1.5 -3.5 inf a nan 2 inf 0.0 -0.0 b inf 1.5 1 '
                       '-0.0 1.5 2 -0.0 -0.0 1.5 a -3.5 1 b b 1.5 -1 nan -1 a -inf nan 2 -0.0 '
                       '-3.5\n',
                       '-inf inf a b -1 1 nan 1 inf -0.0 -3.5 nan -0.0 1 0.0 0.0 nan nan 2 -0.0 -1 '
                       'a -1 1.5 1 1 2 1 -1 -1 1 1.5 a 1.5 1 -3.5 -1 1.5 0.0 1 1.5 -1 2 nan 2 -3.5 '
                       '1.5 1.5 1 a b 1 -inf -1 nan inf 2 1 -inf 0.0 0.0 b b 1.5 inf 1.5 -0.0 0.0 '
                       '0.0 0.0 b 0.0 -1 1 a 0.0 -1 b -0.0 1.5 -0.0 1.5 -0.0 inf 0.0 a a b 0.0 1 '
                       'inf -inf nan -0.0 1.5 2 1 -inf 1 b -inf nan 0.0 -3.5 0.0 -1 1 -0.0 b -0.0 '
                       'inf -0.0 2 a -0.0 1.5 inf a inf 0.0 inf -0.0 -3.5 nan -inf 1 -1 -1\n',
                       '1 b 2 a -1 -0.0 -1 0.0 -0.0 1.5 a nan -3.5 nan -0.0 a 1.5 0.0 -1 1 inf '
                       '-inf 2 nan 2 -1 b -0.0 1 nan 1 -0.0 2 0.0 -inf 0.0 b a 1.5 inf b -3.5 inf '
                       '1 -inf inf 1 1 nan inf nan -0.0 1.5 b nan b -1 -3.5 0.0 -0.0 -0.0 1 a -1 b '
                       '0.0 1.5 0.0 -1 -0.0 inf 1 2 -3.5 1 inf -3.5 inf b 2 inf -inf nan -3.5 -inf '
                       '1.5 -3.5 -0.0 2 1.5 0.0 -inf -1 -0.0 1 -3.5 nan 2 b nan -0.0 2 a -0.0 b b '
                       'inf inf -inf -1 2 -inf -1 1.5 -3.5 0.0 2 -0.0 -0.0 -3.5 -1 nan -3.5 a -inf '
                       '-1 -1 1.5 inf\n',
                       'b -3.5 -3.5 2 -inf -inf 2 a b -inf -3.5 inf -3.5 2 -0.0 inf inf a 0.0 a '
                       'inf 1 2 -inf 0.0 0.0 a -inf 0.0 nan a -3.5 inf inf 2 nan 2 -0.0 -3.5 -inf '
                       'a -3.5 1 1 1.5 1 -0.0 -3.5 1 2 1 inf inf -inf 1.5 -3.5 0.0 -3.5 b -inf '
                       '-3.5 nan -3.5 -0.0 nan 0.0 -3.5 nan inf nan 1 -0.0 2 1.5 nan -0.0 nan a '
                       'inf 0.0 nan 0.0 -1 inf 1 nan 2 -0.0 a 1 2 0.0 1.5 -inf -1 inf b b a 1 a '
                       '-0.0 inf -3.5 -inf a -1 nan nan -1 a nan -3.5 inf -1 -inf -1 2 2 1 2 nan '
                       '0.0 inf b 1 -0.0 0.0 1 2 b nan inf inf 0.0 -3.5 b 1 inf 0.0 0.0 2 0.0 -1 '
                       '0.0 -0.0 2 -inf 1.5 nan 1.5 -0.0 -3.5 0.0 -inf 2 inf a inf 2 2 nan -1 b '
                       'nan -0.0 a 1.5 -0.0 -1 -0.0 -3.5 -3.5 1 nan -3.5 1.5 -0.0 1 0.0 0.0 1.5 a '
                       'nan -3.5 2 -inf a -1 2 2 -inf 2 b 0.0 nan -0.0 -1 0.0 -0.0\n',
                       'nan 1.5 a 2 inf nan 0.0 nan 0.0 a -3.5 -3.5 -0.0 2 -0.0 0.0 1 2 1.5 -3.5 '
                       '1.5 -inf -1 a a -3.5 2 2 a -3.5 b b -inf -inf b a 0.0 b 0.0 a nan inf 1 '
                       '-3.5 b 1 -inf -3.5 -1 2 -inf b 1.5 1.5 2 nan 2 1.5 1 -inf inf 1.5 -1 inf 2 '
                       '-0.0 1 inf -1 -0.0 b a 1.5 -inf -inf b b nan -3.5 1 -3.5 nan a 2 nan -1 '
                       '-inf 1.5 b -1 b nan 0.0 -0.0 -inf a inf -1 b -0.0 a nan inf inf 1 2 1.5 '
                       '1.5 -0.0 -3.5 -inf -3.5 a 1 -0.0 b nan 2 0.0 2 1 b inf 1 -inf nan 1.5 -inf '
                       'nan 2 b nan 0.0 inf 1.5 1 -inf 1 1.5 inf -3.5 -0.0 b -1 b 1.5 1 a a 0.0 '
                       'inf -inf -3.5 2 inf 1 1.5 b -1 b nan -3.5 -0.0 inf -3.5 1 -1 inf 0.0 -3.5 '
                       'b 1.5 -inf nan 2 1.5 -inf 1 -3.5 0.0 a -1 nan 1.5 -3.5 1.5 -3.5 1.5 inf a '
                       '-1 nan -0.0 1.5 a -inf 1 inf -3.5 0.0 -0.0 nan inf 1.5 -inf -0.0 inf -0.0 '
                       'nan -3.5 nan 0.0 2 -3.5 nan b -1 b a b 1 -3.5 -inf a a -inf -0.0 2 -0.0 1 '
                       'nan b -inf 0.0 1 b -inf a 1.5 inf 2 b nan 2 b a 2 inf -0.0 -inf nan -1 b 1 '
                       '-inf inf nan\n')),
 'integer_sort_control': ('values=[4,1,3,1]\n'
                          'print(sorted(values))\n'
                          'values.sort(reverse=True)\n'
                          'print(values)\n',
                          ('',)),
 'ordinary_float_control': ('number=float(input())\nprint(number+1.25,number<2.0)\n', ('1.5\n',)),
 'shadowed_sort_provider': ('def sorted(values):return values\nprint(sorted([2.0,1.0]))\n', ('',)),
 'unused_float_sort': ('def unused(values):return sorted(values)\nprint(1.5+2.25)\n', ('',)),
 'unchanged_root_complex_abs_sort_key': ('values = [1j, 3+4j, -2j, -3-4j]\n'
                                         'print(sorted(values, key=abs))\n'
                                         'print(sorted(values, key=abs, reverse=True))\n',
                                         ('',)),
 'finite_float_set_sort': ('values={-3.0,1.5,2.0,-0.0,True}\n'
                           'print(sorted(values),sorted(values,reverse=True))\n',
                           ('',)),
 'nan_dictionary_sort': ("one=float('nan')\n"
                         "other=float('nan')\n"
                         'values={one:3,other:1,2.0:2}\n'
                         'print([values[key]for key in sorted(values,key=lambda '
                         'key:values[key])])\n',
                         ('',)),
 'integer_set_nan_callback': ("shared=float('nan')\n"
                              'print((shared,)==(shared,))\n'
                              "print(sorted({0,8,16,24,32},key=lambda item:float('nan')))\n",
                              ('',)),
 'canonical_float_key': ('print(sorted([3,1,2],key=float))\n', ('',)),
 'source_float_key': ('def key(value):return -float(value)\nprint(sorted([3,1,2],key=key))\n',
                      ('',)),
 'float_none_key_order': ('values=[(1.5,1),(1.5,0)]\nprint(sorted(values,key=None))\n', ('',)),
 'canonical_key_aliases': ('from builtins import sorted as ordered,float as convert\n'
                           'print(ordered([3,1,2],key=convert))\n',
                           ('',)),
 'list_key_alias': ('convert=float\n'
                    'values=[3,1,2]\n'
                    'values.sort(key=convert,reverse=True)\n'
                    'print(values)\n',
                    ('',)),
 'shadowed_float_key_control': ('def float(value):return -value\n'
                                'print(sorted([3,1,2],key=float))\n',
                                ('',)),
 'unused_literal_float_sort_control': ('def unused():return sorted([2.0,1.0])\nprint(1)\n', ('',)),
 'function_and_entry_sort_modes': ('def order(values,reverse=False):return '
                                   'sorted(values,reverse=reverse)\n'
                                   "shared=float('nan')\n"
                                   'values=[(shared,3),(shared,1),(shared,2)]\n'
                                   'print(order(values))\n'
                                   'print(order(values,True))\n'
                                   'print(sorted(values))\n',
                                   ('',)),
 'closure_nan_key_identity': ('def make():\n'
                              " shared=float('nan')\n"
                              ' def order(values):return sorted([(shared,value)for value in '
                              'values])\n'
                              ' return order\n'
                              'order=make()\n'
                              'print([pair[1]for pair in order([3,1,2])])\n',
                              ('',)),
 'finite_key_alternatives': ('def key(value):return -value\n'
                             "values=[2.0,1.0,float('nan'),-1.0]\n"
                             'for flag in (False,True):\n'
                             ' selected=key if flag else None\n'
                             ' print(sorted(values,key=selected))\n',
                             ('',)),
 'function_error_frames': ('def order(values):\n'
                           " print('entered')\n"
                           ' return sorted(values)\n'
                           "print('before')\n"
                           'print(order([1.5,None]))\n',
                           ('',))}

BOUNDARIES={'nan_set_sort_boundary': ("one=float('nan')\n"
                           "other=float('nan')\n"
                           'values={(one,1),(other,2),(1.0,0)}\n'
                           'print([pair[1]for pair in sorted(values)])\n',
                           'NaN'),
 'nan_set_tied_callback_boundary': ("one=float('nan')\n"
                                    "other=float('nan')\n"
                                    'values={(one,1),(other,2)}\n'
                                    'print([pair[1]for pair in sorted(values,key=lambda '
                                    'pair:0.0)])\n',
                                    'NaN'),
 'nominal_float_tuple_boundary': ('from typing import NamedTuple\n'
                                  'class Pair(NamedTuple):\n'
                                  ' first:float\n'
                                  ' second:int\n'
                                  "shared=float('nan')\n"
                                  'values=[Pair(shared,2),Pair(shared,1)]\n'
                                  'print([value.second for value in sorted(values)])\n',
                                  'nominal')}

class FloatSortProofTests(unittest.TestCase):
    def test_unproved_source_set_and_nominal_protocols_are_positioned(self):
        for name,(source,reason)in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename='original.py',license='none'))
                    self.assertFalse(result.success)
                    error=result.diagnostics[0]
                    self.assertEqual(error.code,'E006')
                    self.assertEqual(error.filename,'original.py')
                    self.assertGreater(error.line,0)
                    self.assertIn(reason,error.message)
                    self.assertIn('sorted',error.message)

    def test_scalar_float_sort_does_not_acquire_container_identity(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['scalar_unordered'][0],TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('native_cmp_sort_indices',result.rust_source)
            self.assertNotIn('NativeIdentityFloat',result.rust_source)
            self.assertNotIn('total_cmp',result.rust_source)

    def test_dead_sorts_emit_no_sorting_kernel(self):
        for name in ('unused_float_sort','unused_literal_float_sort_control'):
            result=transpile(CASES[name][0],TranspileOptions(license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('native_cmp_sort_indices',result.rust_source)

    def test_nonobserver_and_provider_shadow_controls_keep_ordinary_emission(self):
        for name in ('integer_sort_control','ordinary_float_control','shadowed_sort_provider','shadowed_float_key_control','unused_literal_float_sort_control'):
            for mode in ('i64','i128','bigint'):
                normal=transpile(CASES[name][0],TranspileOptions(integer=mode,filename='case.py',license='none'))
                with patch('py2fastrust.native_float_sorting.requires_frames',return_value=False):
                    original_route=transpile(CASES[name][0],TranspileOptions(integer=mode,filename='case.py',license='none'))
                self.assertTrue(normal.success,normal.diagnostics)
                self.assertEqual(normal.rust_source,original_route.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FloatSortExecutionTests(unittest.TestCase):
    def check(self,name):
        source,inputs=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-float-sort-')as directory:
            root=Path(directory);program=root/'case.py';program.write_text(source)
            expected=[subprocess.run([sys.executable,'-I','-B',str(program)],input=data,text=True,capture_output=True,timeout=20)for data in inputs]
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename=str(program),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):self.assertNotIn(marker,result.rust_source)
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+str(optimized));built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180);self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(name=name,integer=mode,optimized=optimized,stdin=data):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=20)
                            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                            if reference.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1:],reference.stderr.splitlines()[-1:])
                                frames=lambda value:re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',value)
                                self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                            else:self.assertEqual(actual.stderr,'')

    def test_scalar_unordered(self):
        self.check('scalar_unordered')

    def test_tuple_shared_nan(self):
        self.check('tuple_shared_nan')

    def test_nested_list_shared_nan(self):
        self.check('nested_list_shared_nan')

    def test_mixed_numeric_exact(self):
        self.check('mixed_numeric_exact')

    def test_keyed_callback_effects(self):
        self.check('keyed_callback_effects')

    def test_sorted_alias(self):
        self.check('sorted_alias')

    def test_comparison_key_float_result(self):
        self.check('comparison_key_float_result')

    def test_empty_float_sort_key_cold(self):
        self.check('empty_float_sort_key_cold')

    def test_float_incompatible_type_error(self):
        self.check('float_incompatible_type_error')

    def test_float_sort_input(self):
        self.check('float_sort_input')

    def test_integer_sort_control(self):
        self.check('integer_sort_control')

    def test_ordinary_float_control(self):
        self.check('ordinary_float_control')

    def test_shadowed_sort_provider(self):
        self.check('shadowed_sort_provider')

    def test_unused_float_sort(self):
        self.check('unused_float_sort')

    def test_unchanged_root_complex_abs_sort_key(self):
        self.check('unchanged_root_complex_abs_sort_key')

    def test_finite_float_set_sort(self):
        self.check('finite_float_set_sort')

    def test_nan_dictionary_sort(self):
        self.check('nan_dictionary_sort')

    def test_integer_set_nan_callback(self):
        self.check('integer_set_nan_callback')

    def test_canonical_float_key(self):
        self.check('canonical_float_key')

    def test_source_float_key(self):
        self.check('source_float_key')

    def test_float_none_key_order(self):
        self.check('float_none_key_order')

    def test_canonical_key_aliases(self):
        self.check('canonical_key_aliases')

    def test_list_key_alias(self):
        self.check('list_key_alias')

    def test_shadowed_float_key_control(self):
        self.check('shadowed_float_key_control')

    def test_unused_literal_float_sort_control(self):
        self.check('unused_literal_float_sort_control')

    def test_function_and_entry_sort_modes(self):
        self.check('function_and_entry_sort_modes')

    def test_closure_nan_key_identity(self):
        self.check('closure_nan_key_identity')

    def test_finite_key_alternatives(self):
        self.check('finite_key_alternatives')

    def test_function_error_frames(self):
        self.check('function_error_frames')

if __name__=='__main__':unittest.main()
