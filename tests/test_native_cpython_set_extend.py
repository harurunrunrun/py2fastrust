"""Canonical list.extend uses original typed CP-set cursor length hints."""
import json
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
import test_native_annotations_assertions as support

CASES={'direct_frozen_literal': 'values = [99]\nvalues.extend({0,8,16,24,32})\nprint(values)\n',
 'stored_set_value': 'source = set([4,1,9,2])\n'
                     'values = [99]\n'
                     'values.extend(source)\n'
                     'print(values, sorted(source))\n',
 'partial_cursor_alias': 'source = set([0,1,7])\n'
                         'cursor = iter(source)\n'
                         'alias = cursor\n'
                         'print(next(alias))\n'
                         'values = [99]\n'
                         'values.extend(cursor)\n'
                         'print(values, next(alias,-1))\n',
 'exhausted_cursor_releases_source': 'source = set([0,1])\n'
                                     'cursor = iter(source)\n'
                                     'print(next(cursor), next(cursor), next(cursor,-1))\n'
                                     'source.add(7)\n'
                                     'values = [99]\n'
                                     'values.extend(cursor)\n'
                                     'print(values, next(cursor,-1))\n',
 'live_size_change_hint_zero': 'source = set([0,1])\n'
                               'cursor = iter(source)\n'
                               'print(next(cursor))\n'
                               'source.add(7)\n'
                               'values = [99]\n'
                               "print('before extension')\n"
                               'values.extend(cursor)\n',
 'zero_budget_unread_key': 'source = set([0,1])\n'
                           'cursor = iter(source)\n'
                           'print(next(cursor))\n'
                           'source.remove(0)\n'
                           'source.add(7)\n'
                           'print(next(cursor))\n'
                           'values = [99]\n'
                           'values.extend(cursor)\n'
                           'print(values, next(cursor,-1))\n',
 'negative_budget_before_pull': 'source = set([0,1])\n'
                                'cursor = iter(source)\n'
                                'print(next(cursor))\n'
                                'source.remove(0)\n'
                                'source.add(7)\n'
                                'print(next(cursor), next(cursor))\n'
                                'values = [99]\n'
                                "print('before negative hint')\n"
                                'values.extend(cursor)\n',
 'empty_set_value': 'source = set()\nvalues = [99]\nvalues.extend(source)\nprint(values)\n',
 'bool_int_original_representative': 'source = set([True,1,2])\n'
                                     'values = [99]\n'
                                     'values.extend(source)\n'
                                     'print(values)\n',
 'custom_owner_hint_after_cursor_creation': 'source = set([0,1])\n'
                                            'cursor = iter(source)\n'
                                            'class Source:\n'
                                            '    def __iter__(self):\n'
                                            "        print('iterator')\n"
                                            '        return cursor\n'
                                            '    def __len__(self):\n'
                                            "        print('owner hint')\n"
                                            '        source.remove(0)\n'
                                            '        source.add(7)\n'
                                            '        return 2\n'
                                            'values = [99]\n'
                                            'values.extend(Source())\n'
                                            'print(values)\n',
 'receiver_before_source_effect': 'values = [99]\n'
                                  'def target():\n'
                                  "    print('target')\n"
                                  '    return values\n'
                                  'def source():\n'
                                  "    print('source')\n"
                                  '    return set([0,1,7])\n'
                                  'target().extend(source())\n'
                                  'print(values)\n',
 'dynamic_text_set': 'source = set(input().split())\n'
                     "values = ['first']\n"
                     'values.extend(source)\n'
                     'print(values)\n',
 'finite_source_values': 'def select(flag):\n'
                         '    if flag:\n'
                         '        return set([0,1,7])\n'
                         '    return [4,5]\n'
                         'values = [99]\n'
                         'values.extend(select(int(input())))\n'
                         'print(values)\n'}
INPUTS={'dynamic_text_set': ['red! blue! green! red!\n'], 'finite_source_values': ['0\n', '1\n']}
BOUNDARY_CASES={'union_source_cursor': 'def select(flag):\n'
                        '    if flag:\n'
                        '        return iter(set([0,1,7]))\n'
                        '    return iter([4,5])\n'
                        'values = [99]\n'
                        'values.extend(select(int(input())))\n'
                        'print(values)\n',
 'existing_list_cursor_union': 'def select(flag):\n'
                               '    if flag:\n'
                               '        return iter([0,1,7])\n'
                               '    return iter([4,5])\n'
                               'values = [99]\n'
                               'values.extend(select(int(input())))\n'
                               'print(values)\n'}

class CPSetExtendBoundaryTests(unittest.TestCase):
    def test_existing_cursor_union_keeps_its_positioned_provider_boundary(self):
        for name,source in BOUNDARY_CASES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer,filename='set_extend.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(item.code=='E006' and item.line==6 and 'typed pull-state adapter' in item.message
                                        for item in result.diagnostics),result.diagnostics)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class CPSetExtendExecutionTests(unittest.TestCase):
    def compare(self,name):
        source=CASES[name];filename='set_extend.py'
        seeds=('0','1','42','4294967295')
        expected=[]
        for data in INPUTS.get(name,('',)):
            for seed in seeds:
                environment={**os.environ,'PYTHONHASHSEED':seed}
                reference=subprocess.run([sys.executable,'-S','-c',support.REFERENCE,source,filename],
                    input=data,text=True,capture_output=True,timeout=10,env=environment)
                expected.append((data,seed,reference.returncode,reference.stdout,
                                 json.loads(reference.stderr)if reference.returncode else None))
        with tempfile.TemporaryDirectory(prefix='pytors-set-extend-')as directory:
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=filename))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                self.assertNotIn('ClassMappingCursor::new',result.rust_source)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                rust=Path(directory)/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],
                        text=True,capture_output=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,seed,returncode,stdout,error in expected:
                        with self.subTest(integer=integer,optimized=optimized,input=data,seed=seed):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=10,
                                env={**os.environ,'PATH':'/no-python-runtime','PYTHONHASHSEED':seed})
                            self.assertEqual((actual.returncode,actual.stdout),(returncode,stdout),actual.stderr)
                            if error is None:self.assertEqual(actual.stderr,'')
                            else:
                                self.assertTrue(actual.stderr.endswith(error['message']+'\n'),actual.stderr)
                                self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),
                                                 [tuple(frame)for frame in error['frames']])


def _case(name):
    def test(self):self.compare(name)
    return test
for _name in CASES:setattr(CPSetExtendExecutionTests,'test_'+_name,_case(_name))

if __name__=='__main__':unittest.main()
