"""Finite sequence alternatives retain aliases, binding effects and Python errors."""
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

SOURCES = {'repeat_count_union': 'class Repeat:\n'
                       ' def run(self,values,count):return values*count\n'
                       'repeat=Repeat()\n'
                       'print(repeat.run([3],2),repeat.run([4],True),repeat.run([5],-2))\n'
                       'repeat.run([6],[7])\n',
 'reverse_repeat_and_tuple_count': 'class Repeat:\n'
                                   ' def run(self,count,values):return count*values\n'
                                   'repeat=Repeat()\n'
                                   'print(repeat.run(2,[3,4]),repeat.run(0,[5]))\n'
                                   'repeat.run((1,),[7])\n',
 'nullable_repeat_error': 'class Repeat:\n'
                          ' def run(self,values,count=None):return values*count\n'
                          'repeat=Repeat()\n'
                          'print(repeat.run([2],3))\n'
                          'repeat.run([4])\n',
 'repeat_preserves_inner_identity': 'class Repeat:\n'
                                    ' def run(self,values,count):return values*count\n'
                                    'repeat=Repeat()\n'
                                    'row=[1]\n'
                                    'source=[row]\n'
                                    'out=repeat.run(source,3)\n'
                                    'out[1].append(8)\n'
                                    'print(row,source,out,out is source,out[0]is out[2])\n',
 'concatenation_different_element_types': 'class Join:\n'
                                          ' def run(self,a,b):return a+b\n'
                                          'join=Join()\n'
                                          'print(join.run([1],[2]),join.run([3],["x"]))\n',
 'concatenation_preserves_inner_aliases': 'class Join:\n'
                                          ' def run(self,a,b):return a+b\n'
                                          'join=Join()\n'
                                          'row=[1]\n'
                                          'left=[row]\n'
                                          'right=[row]\n'
                                          'out=join.run(left,right)\n'
                                          'out[1].append(7)\n'
                                          'print(left,right,out,out is left,out[0]is out[1])\n',
 'list_scalar_add_error_after_effects': 'class Join:\n'
                                        ' def run(self,a,b):return a+b\n'
                                        'def mark(x):\n'
                                        ' print("arg",x)\n'
                                        ' return x\n'
                                        'join=Join()\n'
                                        'print(join.run([1],[2]))\n'
                                        'join.run(mark([3]),mark(4))\n',
 'normal_list_wrong_binary': 'class Operate:\n'
                             ' def run(self,a,b):return a-b\n'
                             'Operate().run([1],2)\n',
 'nullable_getter_default': 'class Reader:\n'
                            ' def read(self,values=None,index=0):\n'
                            '  if values is None:return 0\n'
                            '  return values[index]\n'
                            'reader=Reader()\n'
                            'print(reader.read(),reader.read([3,4],1),reader.read([5],-1))\n',
 'nullable_getter_runtime_error': 'class Reader:\n'
                                  ' def read(self,values=None,index=0):return values[index]\n'
                                  'reader=Reader()\n'
                                  'print(reader.read([3]))\n'
                                  'reader.read()\n',
 'list_scalar_getter_error': 'class Reader:\n'
                             ' def read(self,values,index=0):return values[index]\n'
                             'reader=Reader()\n'
                             'print(reader.read([3,4],1))\n'
                             'reader.read(8)\n',
 'list_union_index_type_error': 'class Reader:\n'
                                ' def read(self,values,index):return values[index]\n'
                                'reader=Reader()\n'
                                'print(reader.read([3,4],True))\n'
                                'reader.read([5],"x")\n',
 'list_index_none_error': 'class Reader:\n'
                          ' def read(self,values,index=None):return values[index]\n'
                          'reader=Reader()\n'
                          'print(reader.read([3,4],1))\n'
                          'reader.read([5])\n',
 'owner_error_precedes_index_type_error': 'class Reader:\n'
                                          ' def read(self,values,index):return values[index]\n'
                                          'reader=Reader()\n'
                                          'print(reader.read([3],0))\n'
                                          'reader.read(None,"x")\n',
 'getitem_evaluation_order_and_alias': 'class Reader:\n'
                                       ' def read(self,values,index):return values[index]\n'
                                       'row=[3,4]\n'
                                       'values=[row]\n'
                                       'def owner():\n'
                                       ' print("owner")\n'
                                       ' return values\n'
                                       'def index():\n'
                                       ' print("index")\n'
                                       ' row.append(5)\n'
                                       ' return 0\n'
                                       'out=Reader().read(owner(),index())\n'
                                       'out.append(6)\n'
                                       'print(out,row,out is row)\n',
 'fixed_tuple_dynamic_getter': 'class Reader:\n'
                               ' def read(self,values,index):return values[index]\n'
                               'reader=Reader()\n'
                               'print(reader.read((3,"x",True),0),reader.read((3,"x",True),-2),reader.read((3,"x",True),2))\n',
 'fixed_tuple_index_error': 'class Reader:\n'
                            ' def read(self,values,index):return values[index]\n'
                            'reader=Reader()\n'
                            'print(reader.read((3,4),1))\n'
                            'reader.read((3,4),2)\n',
 'list_string_bytes_owner_union': 'class Reader:\n'
                                  ' def read(self,values,index):return values[index]\n'
                                  'reader=Reader()\n'
                                  'print(reader.read([3,4],1),reader.read("ab",0),reader.read(b"AB",-1))\n',
 'rebind_only_own_local_after_type_test': 'def values(size):\n'
                                          ' if isinstance(size,int):size=[7]*size\n'
                                          ' return len(size),size[0]\n'
                                          'print(values(3),values([2,4]))\n',
 'nullable_local_after_default_test': 'class Reader:\n'
                                      ' def read(self,values=None):\n'
                                      '  if values is None:values=[7,8]\n'
                                      '  return len(values),values[1]\n'
                                      'reader=Reader()\n'
                                      'print(reader.read(),reader.read([3,4]))\n',
 'nullable_guard_and_chained_ordering': 'class Bounds:\n'
                                        ' def run(self,left,right=None):\n'
                                        '  if right is None:return left\n'
                                        '  assert 0<=left<=right\n'
                                        '  return right-left\n'
                                        'bounds=Bounds()\n'
                                        'print(bounds.run(2),bounds.run(1,4))\n',
 'nullable_ordering_error': 'class Compare:\n'
                            ' def run(self,a,b=None):return a<=b\n'
                            'compare=Compare()\n'
                            'print(compare.run(1,2))\n'
                            'compare.run(3)\n',
 'none_left_ordering_error': 'class Compare:\n'
                             ' def run(self,a,b):return a>b\n'
                             'compare=Compare()\n'
                             'print(compare.run(3,2))\n'
                             'compare.run(None,4)\n',
 'string_none_ordering_error': 'class Compare:\n'
                               ' def run(self,a,b):return a<b\n'
                               'compare=Compare()\n'
                               'print(compare.run("a","b"))\n'
                               'compare.run("a",None)\n',
 'comparison_operand_effects_and_short_circuit': 'class Compare:\n'
                                                 ' def run(self,a,b):return a<b<mark(9)\n'
                                                 'def mark(value):\n'
                                                 ' print("arg",value)\n'
                                                 ' return value\n'
                                                 'compare=Compare()\n'
                                                 'print(compare.run(mark(3),mark(2)))\n'
                                                 'compare.run(mark(1),mark(None))\n',
 'different_scalar_list_ordering_error': 'class Compare:\n'
                                         ' def run(self,a,b):return a>=b\n'
                                         'compare=Compare()\n'
                                         'print(compare.run(3,2))\n'
                                         'compare.run(3,[4])\n',
 'inplace_repeat_union_preserves_alias': 'class Operate:\n'
                                         ' def run(self,a,b):\n'
                                         '  saved=a\n'
                                         '  a*=b\n'
                                         '  return a,saved\n'
                                         'op=Operate()\n'
                                         'values=[1]\n'
                                         'print(op.run(values,2),values)\n'
                                         'print(op.run(3,2))\n',
 'inplace_add_union_preserves_alias': 'class Operate:\n'
                                      ' def run(self,a,b):\n'
                                      '  saved=a\n'
                                      '  a+=b\n'
                                      '  return a,saved\n'
                                      'op=Operate()\n'
                                      'values=[1]\n'
                                      'print(op.run(values,[2]),values)\n'
                                      'print(op.run(3,2))\n',
 'inplace_repeat_mixed_count_error': 'class Operate:\n'
                                     ' def run(self,a,b):\n'
                                     '  a*=b\n'
                                     '  return a\n'
                                     'op=Operate()\n'
                                     'values=[1]\n'
                                     'print(op.run(values,2),values)\n'
                                     'op.run(values,None)\n',
 'inplace_add_noniterable_error': 'class Operate:\n'
                                  ' def run(self,a,b):\n'
                                  '  a+=b\n'
                                  '  return a\n'
                                  'op=Operate()\n'
                                  'values=[1]\n'
                                  'print(op.run(values,[2]),values)\n'
                                  'op.run(values,None)\n',
 'inplace_self_extension': 'class Operate:\n'
                           ' def run(self,a,b):\n'
                           '  a+=b\n'
                           '  return a\n'
                           'op=Operate()\n'
                           'values=[1,2]\n'
                           'print(op.run(values,values),values)\n'
                           'print(op.run(3,4))\n',
 'inplace_reverse_repeat_makes_new_list': 'class Operate:\n'
                                          ' def run(self,a,b):\n'
                                          '  a*=b\n'
                                          '  return a\n'
                                          'op=Operate()\n'
                                          'values=[1]\n'
                                          'out=op.run(2,values)\n'
                                          'print(out,values,out is values)\n',
 'inplace_list_append_argument_effect': 'class Operate:\n'
                                        ' def run(self,a,b):\n'
                                        '  saved=a\n'
                                        '  a+=b\n'
                                        '  return a,saved\n'
                                        'def change(values):\n'
                                        ' values.append(2)\n'
                                        ' return values\n'
                                        'values=[1]\n'
                                        'print(Operate().run(values,change(values)),values)\n',
 'heterogeneous_tuple_literal_indices': 'class Reader:\n'
                                        ' def read(self,values):return '
                                        'values[0],values[-1],values[True]\n'
                                        'print(Reader().read((3,"x",True)))\n',
 'string_wrong_index_message': 'class Reader:\n'
                               ' def read(self,values,index):return values[index]\n'
                               'reader=Reader()\n'
                               'print(reader.read("ab",0))\n'
                               'reader.read("cd","x")\n',
 'bytes_wrong_index_message': 'class Reader:\n'
                              ' def read(self,values,index):return values[index]\n'
                              'reader=Reader()\n'
                              'print(reader.read(b"AB",0))\n'
                              'reader.read(b"CD",None)\n',
 'bytes_index_error': 'class Reader:\n'
                      ' def read(self,values,index):return values[index]\n'
                      'reader=Reader()\n'
                      'print(reader.read(b"AB",0))\n'
                      'reader.read(b"CD",3)\n',
 'repeat_child_layout_refines_after_alias_write': 'class Repeat:\n'
                                                  ' def run(self,values,count):return '
                                                  'values*count\n'
                                                  'repeat=Repeat()\n'
                                                  'row=[1]\n'
                                                  'out=repeat.run([row],2)\n'
                                                  'row.append("x")\n'
                                                  'print(out,row,out[0]is row)\n',
 'concat_child_layout_refines_after_alias_write': 'class Join:\n'
                                                  ' def run(self,a,b):return a+b\n'
                                                  'left=[1]\n'
                                                  'right=[2]\n'
                                                  'a=[left]\n'
                                                  'b=[right]\n'
                                                  'out=Join().run(a,b)\n'
                                                  'right.append("x")\n'
                                                  'print(out,a,b,out[1]is right)\n',
 'inplace_repeat_bool_and_float_count': 'class Operate:\n'
                                        ' def run(self,a,b):\n'
                                        '  a*=b\n'
                                        '  return a\n'
                                        'values=[1,2]\n'
                                        'op=Operate()\n'
                                        'print(op.run(values,False),values)\n'
                                        'op.run(values,1.5)\n',
 'generic_union_sources': 'class Repeat:\n'
                          ' def run(self,values,count):return values*count\n'
                          'repeat=Repeat()\n'
                          'print(repeat.run([1,2],2),repeat.run(["a","b"],2))\n',
 'fixed_tuple_empty_index_error': 'class Reader:\n'
                                  ' def read(self,values):return values[0]\n'
                                  'Reader().read(())\n',
 'mixed_owner_index_error_before_later_call': 'class Reader:\n'
                                              ' def read(self,values,index):return values[index]\n'
                                              'def later():\n'
                                              ' print("later")\n'
                                              ' return 0\n'
                                              'reader=Reader()\n'
                                              'print(reader.read([3],0))\n'
                                              'print(reader.read(None,"bad"),later())\n',
 'global_after_none_test_and_call': 'values=[3]\n'
                                    'def change():\n'
                                    ' global values\n'
                                    ' values=None\n'
                                    'class Reader:\n'
                                    ' def run(self):\n'
                                    '  if values is not None:\n'
                                    '   change()\n'
                                    '   return values[0]\n'
                                    'print(Reader().run())\n',
 'captured_after_none_test_and_call': 'def outer():\n'
                                      ' values=[3]\n'
                                      ' def change():\n'
                                      '  nonlocal values\n'
                                      '  values=None\n'
                                      ' def read():\n'
                                      '  if values is not None:\n'
                                      '   change()\n'
                                      '   return values[0]\n'
                                      ' return read()\n'
                                      'print(outer())\n',
 'captured_owner_survives_global_rebinding': 'values=[3]\n'
                                             'def change():\n'
                                             ' global values\n'
                                             ' values=None\n'
                                             'class Reader:\n'
                                             ' def run(self):\n'
                                             '  saved=values\n'
                                             '  change()\n'
                                             '  return saved[0]\n'
                                             'print(Reader().run(),values)\n',
 'captured_owner_survives_nonlocal_rebinding': 'def outer():\n'
                                               ' values=[3]\n'
                                               ' def change():\n'
                                               '  nonlocal values\n'
                                               '  values=None\n'
                                               ' def read():\n'
                                               '  saved=values\n'
                                               '  change()\n'
                                               '  return saved[0],values\n'
                                               ' return read()\n'
                                               'print(outer())\n'}

class UnionSequenceProofTests(unittest.TestCase):
    def test_original_syntax_and_scope_metadata_are_not_rewritten(self):
        source=SOURCES["repeat_count_union"]
        unit=build_program(source,"original.py").main
        before=ast.dump(unit.tree,include_attributes=True)
        model=Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit);model.run()
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)

    def test_unsupported_write_and_iterator_protocols_name_the_boundary(self):
        sources=(("class Operate:\n def run(self,values,b):\n  values[0]*=b\n  return values\nop=Operate()\nrow=[2]\nprint(op.run([row],2),row)\nprint(op.run([3],4))\n","per-alternative indexed write storage"),("class Operate:\n def run(self,a,b):\n  a+=b\n  return a\nprint(Operate().run([1],(2,3)))\n","list inplace extension"),("class Index:\n def __index__(self):return 0\nclass Reader:\n def read(self,a,b):return a[b]\nprint(Reader().read([3],Index()))\n","__index__"))
        for source,detail in sources:
            for integer in ("i64","i128","bigint"):
                with self.subTest(detail=detail,integer=integer),patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM entered")):
                    result=transpile(source,TranspileOptions(integer=integer,filename="boundary.py"))
                self.assertFalse(result.success)
                error=result.diagnostics[0]
                self.assertEqual(error.code,"E006");self.assertEqual(error.filename,"boundary.py")
                self.assertGreater(error.line,0);self.assertIn(detail,error.message)

    def test_recursive_mutable_storage_remains_explicit(self):
        source="class Holder:pass\nitems=[]\nitems.append(items)\n"
        for integer in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success);self.assertIn("recursive",result.diagnostics[0].message)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class UnionSequenceExecutionTests(unittest.TestCase):
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
for name,source in SOURCES.items():setattr(UnionSequenceExecutionTests,"test_"+name,case(source))

if __name__=="__main__":unittest.main()
