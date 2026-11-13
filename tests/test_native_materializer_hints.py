"""Only canonical hint-consuming materializers observe provider length hints."""
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

CASES={'list': 'source = set([0,1])\n'
         'stream = iter(source)\n'
         'print(next(stream))\n'
         'source.remove(0)\n'
         'source.add(7)\n'
         'print(next(stream),next(stream))\n'
         'print(list(stream))\n',
 'list_wrapped': 'source = set([0,1])\n'
                 'stream = iter(source)\n'
                 'print(next(stream))\n'
                 'source.remove(0)\n'
                 'source.add(7)\n'
                 'print(next(stream),next(stream))\n'
                 'class Source:\n'
                 '    def __iter__(self):\n'
                 "        print('iter called')\n"
                 '        return stream\n'
                 '    def __len__(self):\n'
                 "        print('owner hint')\n"
                 '        return 3\n'
                 'print(list(Source()))\n',
 'sorted': 'source = set([0,1])\n'
           'stream = iter(source)\n'
           'print(next(stream))\n'
           'source.remove(0)\n'
           'source.add(7)\n'
           'print(next(stream),next(stream))\n'
           'print(sorted(stream))\n',
 'sorted_wrapped': 'source = set([0,1])\n'
                   'stream = iter(source)\n'
                   'print(next(stream))\n'
                   'source.remove(0)\n'
                   'source.add(7)\n'
                   'print(next(stream),next(stream))\n'
                   'class Source:\n'
                   '    def __iter__(self):\n'
                   "        print('iter called')\n"
                   '        return stream\n'
                   '    def __len__(self):\n'
                   "        print('owner hint')\n"
                   '        return 3\n'
                   'print(sorted(Source()))\n',
 'tuple': 'source = set([0,1])\n'
          'stream = iter(source)\n'
          'print(next(stream))\n'
          'source.remove(0)\n'
          'source.add(7)\n'
          'print(next(stream),next(stream))\n'
          'print(tuple(stream))\n',
 'tuple_wrapped': 'source = set([0,1])\n'
                  'stream = iter(source)\n'
                  'print(next(stream))\n'
                  'source.remove(0)\n'
                  'source.add(7)\n'
                  'print(next(stream),next(stream))\n'
                  'class Source:\n'
                  '    def __iter__(self):\n'
                  "        print('iter called')\n"
                  '        return stream\n'
                  '    def __len__(self):\n'
                  "        print('owner hint')\n"
                  '        return 3\n'
                  'print(tuple(Source()))\n',
 'bytearray': 'source = set([0,1])\n'
              'stream = iter(source)\n'
              'print(next(stream))\n'
              'source.remove(0)\n'
              'source.add(7)\n'
              'print(next(stream),next(stream))\n'
              'print(bytearray(stream))\n',
 'bytearray_wrapped': 'source = set([0,1])\n'
                      'stream = iter(source)\n'
                      'print(next(stream))\n'
                      'source.remove(0)\n'
                      'source.add(7)\n'
                      'print(next(stream),next(stream))\n'
                      'class Source:\n'
                      '    def __iter__(self):\n'
                      "        print('iter called')\n"
                      '        return stream\n'
                      '    def __len__(self):\n'
                      "        print('owner hint')\n"
                      '        return 3\n'
                      'print(bytearray(Source()))\n',
 'sum': 'source = set([0,1])\n'
        'stream = iter(source)\n'
        'print(next(stream))\n'
        'source.remove(0)\n'
        'source.add(7)\n'
        'print(next(stream),next(stream))\n'
        'print(sum(stream))\n',
 'min': 'source = set([0,1])\n'
        'stream = iter(source)\n'
        'print(next(stream))\n'
        'source.remove(0)\n'
        'source.add(7)\n'
        'print(next(stream),next(stream))\n'
        'print(min(stream))\n',
 'any': 'source = set([0,1])\n'
        'stream = iter(source)\n'
        'print(next(stream))\n'
        'source.remove(0)\n'
        'source.add(7)\n'
        'print(next(stream),next(stream))\n'
        'print(any(stream))\n',
 'all': 'source = set([0,1])\n'
        'stream = iter(source)\n'
        'print(next(stream))\n'
        'source.remove(0)\n'
        'source.add(7)\n'
        'print(next(stream),next(stream))\n'
        'print(all(stream))\n',
 'comprehension': 'source = set([0,1])\n'
                  'stream = iter(source)\n'
                  'print(next(stream))\n'
                  'source.remove(0)\n'
                  'source.add(7)\n'
                  'print(next(stream),next(stream))\n'
                  'print([value for value in stream])\n',
 'set_update': 'source = set([0,1])\n'
               'stream = iter(source)\n'
               'print(next(stream))\n'
               'source.remove(0)\n'
               'source.add(7)\n'
               'print(next(stream),next(stream))\n'
               'target = set()\n'
               'target.update(stream)\n'
               'print(sorted(target))\n',
 'list_wrapped_no_owner_length': 'source = set([0,1])\n'
                                 'stream = iter(source)\n'
                                 'print(next(stream))\n'
                                 'source.remove(0)\n'
                                 'source.add(7)\n'
                                 'print(next(stream),next(stream))\n'
                                 'class Source:\n'
                                 '    def __iter__(self):\n'
                                 "        print('iter called')\n"
                                 '        return stream\n'
                                 'print(list(Source()))\n',
 'sorted_wrapped_typeerror_owner_length': 'source = set([0,1])\n'
                                          'stream = iter(source)\n'
                                          'print(next(stream))\n'
                                          'source.remove(0)\n'
                                          'source.add(7)\n'
                                          'print(next(stream),next(stream))\n'
                                          'class Source:\n'
                                          '    def __iter__(self):\n'
                                          "        print('iter called')\n"
                                          '        return stream\n'
                                          '    def __len__(self):\n'
                                          "        print('owner hint')\n"
                                          "        raise TypeError('hint refused')\n"
                                          'print(sorted(Source()))\n',
 'list_wrapped_negative_owner_length': 'source = set([0,1])\n'
                                       'stream = iter(source)\n'
                                       'print(next(stream))\n'
                                       'source.remove(0)\n'
                                       'source.add(7)\n'
                                       'print(next(stream),next(stream))\n'
                                       'class Source:\n'
                                       '    def __iter__(self):\n'
                                       "        print('iter called')\n"
                                       '        return stream\n'
                                       '    def __len__(self):\n'
                                       "        print('owner hint')\n"
                                       '        return -1\n'
                                       'print(list(Source()))\n',
 'list_map_absent': 'print(list(map(abs,[-3,1,-2])))\n',
 'sorted_filter_absent': 'print(sorted(filter(None,[0,3,1,0,2])))\n',
 'list_repeat_partial_hint': 'from itertools import repeat\n'
                             'stream=repeat(7,4)\n'
                             'print(next(stream))\n'
                             'print(list(stream))\n',
 'list_repeat_huge_hint': 'from itertools import repeat\n'
                          'print(list(repeat(7,9223372036854775807)))\n',
 'list_forward_range_huge_hint': 'stream=iter(range(-9223372036854775807,9223372036854775807))\n'
                                 'print(list(stream))\n',
 'sorted_reverse_range_huge_hint': 'stream=reversed(range(-9223372036854775807,9223372036854775807))\n'
                                   'print(sorted(stream))\n',
 'list_live_set_size_mismatch': 'source=set([0,1])\n'
                                'stream=iter(source)\n'
                                'print(next(stream))\n'
                                'source.add(7)\n'
                                'print(list(stream))\n',
 'sorted_zero_budget_unread_key': 'source=set([0,1])\n'
                                  'stream=iter(source)\n'
                                  'print(next(stream))\n'
                                  'source.remove(0)\n'
                                  'source.add(7)\n'
                                  'print(next(stream))\n'
                                  'print(sorted(stream))\n',
 'list_partial_bytes_cursor': 'stream=iter(b"abc")\nprint(next(stream))\nprint(list(stream))\n',
 'list_live_list_cursor': 'source=[1,2]\n'
                          'stream=iter(source)\n'
                          'print(next(stream))\n'
                          'source.append(3)\n'
                          'print(list(stream))\n',
 'sorted_partial_tuple_cursor': 'stream=iter((4,2,3))\n'
                                'print(next(stream))\n'
                                'print(sorted(stream))\n',
 'original_root_negative_materializer': 'values=set([0,1])\n'
                                        'stream=iter(values)\n'
                                        'print(next(stream))\n'
                                        'values.remove(0)\n'
                                        'values.add(7)\n'
                                        'print(next(stream))\n'
                                        'print(next(stream))\n'
                                        'print(list(stream))\n',
 'list_direct_range_huge_hint': 'print(list(range(-9223372036854775807,9223372036854775807)))\n',
 'sorted_direct_range_huge_hint': 'print(sorted(range(-9223372036854775807,9223372036854775807)))\n',
 'list_direct_range_selected_abi': 'print(list(range(9,-6,-3)))\n',
 'sorted_direct_range_selected_abi': 'print(sorted(range(9,-6,-3)))\n',
 'aliased_range_list_huge_hint': 'progression=range\n'
                                 'collect=list\n'
                                 'print(collect(progression(-9223372036854775807,9223372036854775807)))\n',
 'source_returned_range_materializer': 'def produce():\n'
                                       "    print('producer')\n"
                                       '    return range(5,-2,-2)\n'
                                       'print(list(produce()))\n',
 'shadowed_range_source_function': 'def range(count):return [count,count+1]\n'
                                   'print(list(range(4)))\n',
 'shadowed_list_consumer': 'def list(source):return sum(source)\nprint(list(range(4)))\n',
 'list_direct_reverse_range_huge_hint': 'print(list(reversed(range(-9223372036854775807,9223372036854775807))))\n',
 'sorted_direct_reverse_range_huge_hint': 'print(sorted(reversed(range(-9223372036854775807,9223372036854775807))))\n',
 'list_direct_range_argument_effects': 'def mark(label,value):\n'
                                       '    print(label)\n'
                                       '    return value\n'
                                       "print(list(range(mark('start',1),mark('stop',8),mark('step',3))))\n",
 'sorted_zero_step_before_later_argument': 'def mark(label,value):\n'
                                           '    print(label)\n'
                                           '    return value\n'
                                           "print(sorted(range(mark('start',0),mark('stop',3),mark('step',0)),reverse=mark('reverse',True)))\n"}
BOUNDARY_CASES={'bytes': 'source = set([0,1])\n'
          'stream = iter(source)\n'
          'print(next(stream))\n'
          'source.remove(0)\n'
          'source.add(7)\n'
          'print(next(stream),next(stream))\n'
          'print(bytes(stream))\n',
 'bytes_wrapped': 'source = set([0,1])\n'
                  'stream = iter(source)\n'
                  'print(next(stream))\n'
                  'source.remove(0)\n'
                  'source.add(7)\n'
                  'print(next(stream),next(stream))\n'
                  'class Source:\n'
                  '    def __iter__(self):\n'
                  "        print('iter called')\n"
                  '        return stream\n'
                  '    def __len__(self):\n'
                  "        print('owner hint')\n"
                  '        return 3\n'
                  'print(bytes(Source()))\n'}

def runtime_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))


class MaterializerHintBoundaryTests(unittest.TestCase):
    def test_iterable_bytes_keeps_explicit_conversion_protocol_boundary(self):
        for name,source in BOUNDARY_CASES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer,filename='materializer_hints.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(item.code=='E006' and 'bytes' in item.message and 'iterable' in item.message
                                        for item in result.diagnostics),result.diagnostics)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MaterializerHintExecutionTests(unittest.TestCase):
    def compare(self,name):
        source=CASES[name];filename='materializer_hints.py'
        reference=subprocess.run([sys.executable,'-S','-c',support.REFERENCE,source,filename],
            text=True,capture_output=True,timeout=10,env={**os.environ,'PYTHONHASHSEED':'0'})
        error=json.loads(reference.stderr)if reference.returncode else None
        with tempfile.TemporaryDirectory(prefix='pytors-materializer-hints-')as directory:
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=filename))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                rust=Path(directory)/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],
                        text=True,capture_output=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    with self.subTest(integer=integer,optimized=optimized):
                        actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,
                            env={**os.environ,'PATH':'/no-python-runtime','PYTHONHASHSEED':'0'},
                            preexec_fn=runtime_limits if sys.platform.startswith('linux')else None)
                        self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                        if error is None:self.assertEqual(actual.stderr,'')
                        else:
                            self.assertTrue(actual.stderr.endswith(error['message']+'\n'),actual.stderr)
                            self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),
                                             [tuple(frame)for frame in error['frames']])


def _case(name):
    def test(self):self.compare(name)
    return test
for _name in CASES:setattr(MaterializerHintExecutionTests,'test_'+_name,_case(_name))

if __name__=='__main__':unittest.main()
