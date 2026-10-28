"""Nested class-path lists keep their Python handles across native operations."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ClassNestedStorageTests(unittest.TestCase):
    def compare(self,source,inputs=("",)):
        expected=[subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=10)for data in inputs]
        with tempfile.TemporaryDirectory(prefix="pytors-nested-class-")as directory:
            for mode in ("i64","i128","bigint"):
                with patch("py2fastrust.codegen.generate",side_effect=AssertionError("general execution backend entered")):
                    result=transpile(source,TranspileOptions(integer=mode,filename="nested.py"))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,"native")
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ("enum Value","enum Op","struct Runtime","fn step(","struct PegParser"):
                    self.assertNotIn(marker,result.rust_source)
                path=Path(directory)/(mode+".rs");path.write_text(result.rust_source)
                for release in (False,True):
                    binary=path.with_name(mode+("_release"if release else"_debug"))
                    built=subprocess.run(["rustc","--edition=2021",*(["-O"]if release else[]),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(integer=mode,release=release,data=data):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,
                                                  env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                            self.assertEqual(actual.stdout,reference.stdout)
                            self.assertEqual(actual.returncode,reference.returncode,actual.stderr+reference.stderr)
                            if actual.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],reference.stderr.splitlines()[-1].split(":")[0])
                            else:self.assertEqual(actual.stderr,"")

    def test_nested_fields_arguments_and_returns_preserve_inner_aliases(self):
        self.compare('''class Box:
 def __init__(self,rows):self.rows=rows
 def first(self):return self.rows[0]
 def add(self,index,value):self.rows[index].append(value)
rows=[[1],[2]]
box=Box(rows)
first=box.first()
box.add(0,3)
rows[1][0]=4
print(rows,first,box.rows is rows,box.first() is first)
''')

    def test_repeat_fresh_rows_shallow_copy_self_extend_and_inplace_repeat(self):
        self.compare('''class Scope:pass
inner=[]
repeated=[inner]*2
separate=[[],[]]
repeated[0].append(7)
separate[0].append(9)
print(repeated,separate,repeated[0] is repeated[1],separate[0] is separate[1])
shallow=repeated.copy()
repeated.extend(repeated)
repeated+=repeated
repeated[1].append(8)
alias=repeated
repeated*=2
print(repeated,shallow,alias is repeated,shallow[0] is repeated[-1])
repeated*=0
print(alias,shallow,inner)
''')

    def test_empty_repetition_does_not_iterate_the_repetition_count(self):
        self.compare('''class Scope:pass
empty=[]
copy=empty*(1<<60)
alias=empty
empty*=1<<60
print(copy,empty,copy is empty,alias is empty)
''')

    def test_nested_tuples_instances_equality_and_search_keep_default_identity(self):
        self.compare('''class Item:
 def __init__(self,value):self.value=value
first=Item(3)
second=Item(3)
items=[first,second,first]
same=[first,second,first]
print(items==same,items.count(first),items.index(second),first in items,first==second)
first.value=7
print(items[0].value,items[2].value)
pairs=[(first,[1]),(second,[2])]
copy=pairs.copy()
print(pairs==copy,pairs[0][1] is copy[0][1],pairs.count((first,[1])),pairs.index((second,[2])))
copy[0][1].append(9)
print(pairs[0][1],copy[0][1],pairs[0][0] is first)
''')

    def test_nested_builtin_lexicographic_sort_and_comparison(self):
        self.compare('''class Scope:pass
rows=[[2,0],[1,3],[1],[]]
rows.sort()
print(rows,rows[0]<rows[1],rows[1]<=rows[1],[1] in rows,rows.count([1]))
rows.sort(reverse=True)
print(rows)
pairs=[([2],3),([1],4),([1],2)]
pairs.sort()
print(pairs,pairs[0]<pairs[1],pairs[1][0]==[1])
''')

    def test_iteration_observes_inner_and_outer_mutations(self):
        self.compare('''class Scope:pass
rows=[[1],[2]]
for row in rows:
 row.append(len(row))
 if len(rows)<3:rows.append([3])
print(rows,row)
for row in rows:
 for value in row:
  if len(row)<3:row.append(value+10)
print(rows)
''')

    def test_nested_receiver_index_errors_precede_argument_effects(self):
        self.compare('''class Box:
 def __init__(self):self.rows=[[1],[2]]
def mark(value):
 print("argument")
 return value
box=Box()
box.rows[int(input())].append(mark(7))
print(box.rows)
''',inputs=("0\n","-1\n","2\n","-3\n"))

    def test_captured_inner_receiver_survives_field_replacement_in_argument(self):
        self.compare('''class Box:
 def __init__(self):self.rows=[[1],[2]]
 def replace(self):
  self.rows=[[9],[8]]
  return 7
box=Box()
old=box.rows
inner=old[0]
box.rows[0].append(box.replace())
print(old,box.rows,inner,old[0] is inner)
''')

    def test_acyclic_instance_lists_copy_extend_and_pop_keep_handles(self):
        self.compare('''class Item:
 def __init__(self,value):self.value=value
class Bag:
 def __init__(self,items):self.rows=[items]
one=Item(1)
two=Item(2)
items=[one,two]
bag=Bag(items)
copy=bag.rows.copy()
extra=bag.rows+copy
extra.extend(extra)
print(extra[0] is items,copy[0] is items,extra[0][0] is one)
removed=items.pop()
print(removed is two,items[0] is one,len(extra[3]),bag.rows==copy)
''')

    def test_cycles_and_unproved_protocols_have_specific_diagnostics(self):
        cases=(
            ('class Scope:pass\nvalues=[]\nvalues.append(values)\n',("recursive","cycle-aware")),
            ('class Item:\n def __init__(self):self.children=[]\nitem=Item()\nitem.children.append(item)\n',("reference cycle","collector")),
            ('class Item:\n def __eq__(self,other):return True\nitems=[Item()]\nprint(items==items)\n',("__eq__","special-method")),
            ('class Scope:pass\nvalues=[[float("nan")]]\nprint(values.count(values[0]))\n',("floating","identity")),
        )
        for mode in ("i64","i128","bigint"):
            for source,tokens in cases:
                with self.subTest(integer=mode,source=source):
                    result=transpile(source,TranspileOptions(integer=mode,filename="unsupported-nested.py"))
                    self.assertFalse(result.success)
                    self.assertIsNone(result.rust_source)
                    self.assertEqual(result.diagnostics[0].code,"E006")
                    # BigInt has no float conversion/storage adapter yet.
                    if mode=="bigint"and 'float("nan")'in source:continue
                    for token in tokens:self.assertIn(token,result.diagnostics[0].message)


if __name__=="__main__":unittest.main()
