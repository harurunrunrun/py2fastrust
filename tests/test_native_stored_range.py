"""Stored range alternatives and list materialization share typed pull state."""
import ast
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model
import test_native_iterator_reductions as execution

SOURCES = {'list_or_range_return': 'class Source:\n'
                         ' def choose(self,flag):\n'
                         '  if flag:return [1,2]\n'
                         '  return range(3,6)\n'
                         'source=Source()\n'
                         'print(list(source.choose(True)),list(source.choose(False)))\n',
 'map_filter_zip_same_function_site': 'def choose(flag):\n'
                                      ' if flag:return [1,2,3]\n'
                                      ' return range(4,7)\n'
                                      'class Consume:\n'
                                      ' def run(self,source):\n'
                                      '  return list(map(lambda x:x+1,source)),list(filter(lambda '
                                      'x:x%2,source)),list(zip(source,[8,9]))\n'
                                      'consume=Consume()\n'
                                      'print(consume.run(choose(True)))\n'
                                      'print(consume.run(choose(False)))\n',
 'nullable_range_return': 'class Source:\n'
                          ' def choose(self,flag):\n'
                          '  if flag:return range(4,-1,-2)\n'
                          '  return None\n'
                          'source=Source()\n'
                          'value=source.choose(True)\n'
                          'print(list(value))\n'
                          'value=source.choose(False)\n'
                          'print(value is None)\n',
 'object_field_range_list_rebinding': 'class Source:\n'
                                      ' def __init__(self):self.values=range(3)\n'
                                      ' def set(self,values):self.values=values\n'
                                      ' def read(self):return list(self.values)\n'
                                      'source=Source()\n'
                                      'print(source.read())\n'
                                      'source.set([7,8])\n'
                                      'print(source.read())\n'
                                      'source.set(range(5,1,-2))\n'
                                      'print(source.read())\n',
 'captured_range_owner_survives_binding_change': 'values=range(3)\n'
                                                 'class Source:\n'
                                                 ' def read(self):\n'
                                                 '  saved=values\n'
                                                 '  return list(saved)\n'
                                                 'print(Source().read())\n'
                                                 'values=[8,9]\n'
                                                 'print(Source().read())\n',
 'closure_keeps_range_values': 'def make(source):\n'
                               ' def read():return list(source)\n'
                               ' return read\n'
                               'class Source:\n'
                               ' def run(self):\n'
                               '  first=make(range(3))\n'
                               '  second=make([7,8])\n'
                               '  return first(),second(),first()\n'
                               'print(Source().run())\n',
 'nested_list_range_payloads': 'class Source:\n'
                               ' def run(self,values):return [list(item)for item in values]\n'
                               'source=Source()\n'
                               'print(source.run([range(3),[7,8],range(5,0,-2)]))\n',
 'starred_range_or_list_source': 'class Source:\n'
                                 ' def choose(self,flag):return range(3)if flag else[7,8]\n'
                                 'def collect(*values):return values\n'
                                 'source=Source()\n'
                                 'print(collect(*source.choose(True)),collect(*source.choose(False)))\n',
 'repeated_range_cursors_are_independent': 'class Source:\n'
                                           ' def choose(self,flag):return range(3)if flag '
                                           'else[7,8]\n'
                                           'source=Source().choose(True)\n'
                                           'a=iter(source)\n'
                                           'b=iter(source)\n'
                                           'print(next(a),next(a),next(b),list(a),list(b),list(source))\n',
 'range_or_list_lazy_map_captures_owner': 'values=range(3)\n'
                                          'def increment(x):return x+1\n'
                                          'class Source:\n'
                                          ' def read(self):return map(increment,values)\n'
                                          'first=Source().read()\n'
                                          'values=[7,8]\n'
                                          'second=Source().read()\n'
                                          'print(list(first),list(second))\n',
 'empty_and_negative_step_ranges': 'class Source:\n'
                                   ' def choose(self,n):\n'
                                   '  if n:return range(n,-3,-2)\n'
                                   '  return [7]\n'
                                   'source=Source()\n'
                                   'print(list(source.choose(0)),list(source.choose(5)),list(source.choose(-5)))\n',
 'zero_step_error_after_argument_capture': 'class Source:\n'
                                           ' def choose(self,flag):\n'
                                           '  if flag:return [1]\n'
                                           '  return range(1,3,0)\n'
                                           'source=Source()\n'
                                           'print(list(source.choose(True)))\n'
                                           'source.choose(False)\n',
 'list_text_bytes_and_list_same_site': 'class Buffer:\n'
                                       ' def convert(self,source):return list(source)\n'
                                       'buffer=Buffer()\n'
                                       'print(buffer.convert("abc"),buffer.convert(b"AZ"),buffer.convert([3,4]))\n',
 'list_none_runtime_error': 'class Buffer:\n'
                            ' def convert(self,source):return list(source)\n'
                            'buffer=Buffer()\n'
                            'print(buffer.convert("ab"))\n'
                            'buffer.convert(None)\n',
 'list_integer_runtime_error': 'class Buffer:\n'
                               ' def convert(self,source):return list(source)\n'
                               'buffer=Buffer()\n'
                               'print(buffer.convert([3]))\n'
                               'buffer.convert(4)\n',
 'list_map_effects_are_lazy_until_materialization': 'values=[1,2]\n'
                                                    'def item(x):\n'
                                                    ' print("item",x)\n'
                                                    ' return x+3\n'
                                                    'class Buffer:\n'
                                                    ' def convert(self,source):return '
                                                    'list(source)\n'
                                                    'cursor=map(item,values)\n'
                                                    'print("before")\n'
                                                    'print(Buffer().convert(cursor))\n',
 'list_copies_only_outer_container': 'class Buffer:\n'
                                     ' def convert(self,source):return list(source)\n'
                                     'row=[3]\n'
                                     'source=[row]\n'
                                     'out=Buffer().convert(source)\n'
                                     'out[0].append(4)\n'
                                     'print(source,out,out is source,out[0]is row)\n',
 'list_mixed_saved_iterator_and_list': 'class Source:\n'
                                       ' def choose(self,flag):\n'
                                       '  if flag:return map(lambda x:x+1,[1,2])\n'
                                       '  return [7,8]\n'
                                       'source=Source()\n'
                                       'print(list(source.choose(True)),list(source.choose(False)))\n',
 'list_mixed_raw_sources_widen_elements': 'class Source:\n'
                                          ' def convert(self,source):return list(source)\n'
                                          'source=Source()\n'
                                          'print(source.convert(range(3)),source.convert("ab"),source.convert(b"AZ"),source.convert([3,4]),source.convert((5,True,"x")))\n',
 'unchanged_itertools_finite_source_alternatives': 'from itertools import pairwise,chain\n'
                                                   'def choose(flag):\n'
                                                   ' if flag:return [1,2]\n'
                                                   ' return range(3,6)\n'
                                                   'def values(source):return '
                                                   'list(pairwise(source))\n'
                                                   'print(values(choose(True)),values(choose(False)),list(chain(choose(True),choose(False))))\n',
 'list_builtin_type_dict': 'class Buffer:\n'
                           ' def convert(self,source):return list(source)\n'
                           'Buffer().convert(dict)\n',
 'list_builtin_type_set': 'class Buffer:\n'
                          ' def convert(self,source):return list(source)\n'
                          'Buffer().convert(set)\n',
 'list_builtin_type_tuple': 'class Buffer:\n'
                            ' def convert(self,source):return list(source)\n'
                            'Buffer().convert(tuple)\n',
 'list_builtin_type_filter': 'class Buffer:\n'
                             ' def convert(self,source):return list(source)\n'
                             'Buffer().convert(filter)\n',
 'list_builtin_type_map': 'class Buffer:\n'
                          ' def convert(self,source):return list(source)\n'
                          'Buffer().convert(map)\n',
 'mapping_empty_owner': 'class Buffer:\n'
                        ' def convert(self,source):return list(source)\n'
                        'values={}\n'
                        'print(values)\n'
                        'Buffer().convert(dict)\n',
 'variadic_empty_owner': 'class Buffer:\n'
                         ' def convert(self,source):return list(source)\n'
                         'def pack(*items):return items\n'
                         'print(pack())\n'
                         'Buffer().convert(dict)\n',
 'iterator_empty_owner': 'class Buffer:\n'
                         ' def convert(self,source):return list(source)\n'
                         'cursor=iter([])\n'
                         'print(list(cursor))\n'
                         'Buffer().convert(dict)\n',
 'all_empty_owners_composed': 'class Buffer:\n'
                              ' def convert(self,source):return list(source)\n'
                              'def pack(*items):return items\n'
                              'values={}\n'
                              'cursor=iter([])\n'
                              'print(values,pack(),list(cursor))\n'
                              'Buffer().convert(dict)\n'}

class StoredRangeProofTests(unittest.TestCase):
    def test_original_range_and_materialization_nodes_are_preserved(self):
        source=SOURCES["list_or_range_return"]
        unit=build_program(source,"original.py").main
        before=ast.dump(unit.tree,include_attributes=True)
        Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit).run()
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)

    def test_remaining_range_object_protocols_stay_positioned_boundaries(self):
        sources=("class Source:\n def run(self):\n  value=range(3)\n  return value is value\nprint(Source().run())\n","class Source:\n def run(self):return len(range(3))\nprint(Source().run())\n","class Source:\n def run(self):return range(3)\nprint(Source().run())\n")
        for source in sources:
            for integer in ("i64","i128","bigint"):
                with self.subTest(integer=integer),patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM entered")):
                    result=transpile(source,TranspileOptions(integer=integer,filename="boundary.py"))
                self.assertFalse(result.success)
                error=result.diagnostics[0]
                self.assertEqual(error.code,"E006");self.assertEqual(error.filename,"boundary.py")
                self.assertGreater(error.line,0);self.assertIn("range",error.message)

    def test_returned_suspension_requires_the_existing_generator_adapter(self):
        source="class Source:\n def choose(self,flag):\n  if flag:return (x+1 for x in [1,2])\n  return [7,8]\nsource=Source()\nprint(list(source.choose(True)),list(source.choose(False)))\n"
        for integer in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=integer,filename="boundary.py"))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")
            self.assertIn("suspension",result.diagnostics[0].message)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class StoredRangeExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=execution.NativeIteratorReductionTests();cls.harness.setUpClass()
    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()
    def compare(self,source):
        expected=subprocess.run([sys.executable,"-I","-c",source],capture_output=True,text=True,timeout=10)
        frame=lambda text:re.findall(r'File "[^\"]+", line (\d+), in ([^\n]+)',text)
        final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else""
        for integer in ("i64","i128","bigint"):
            for optimize in (False,True):
                with self.subTest(integer=integer,optimize=optimize),patch("py2fastrust.codegen.generate",side_effect=AssertionError("general backend entered")):
                    generated=self.harness.compile(source,integer,release=optimize)
                    self.assertNotIn("enum Value",generated[2]);self.assertLess(len(generated[2].encode()),512*1024)
                    actual=subprocess.run([str(generated[1])],capture_output=True,text=True,timeout=10)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    self.assertEqual(final(actual.stderr),final(expected.stderr));self.assertEqual(frame(actual.stderr),frame(expected.stderr))


def case(source):
    def run(self):self.compare(source)
    return run
for name,source in SOURCES.items():setattr(StoredRangeExecutionTests,"test_"+name,case(source))

if __name__=="__main__":unittest.main()
