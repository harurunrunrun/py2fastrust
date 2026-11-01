"""Every class-list allocation publishes its solved element ABI to common facts."""
import ast
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,shape
from py2fastrust.native_constraints import value
from py2fastrust.native_types import ListType,NullableType,union_type


CASES={'alias_rebinding_keeps_original_allocation': 'class Box:\n'
                                              ' def __init__(self,text):\n'
                                              '  original=[None,text]\n'
                                              '  self.saved=original\n'
                                              '  original=[7]\n'
                                              '  self.current=original\n'
                                              '  self.saved.append(False)\n'
                                              'box=Box("word")\n'
                                              'print(box.saved,box.current,box.saved is box.current)\n',
 'concat_and_alias_families': 'class Box:\n'
                              ' def __init__(self,text):\n'
                              '  self.left=[None]\n'
                              '  self.right=[text]\n'
                              '  self.combined=self.left+self.right\n'
                              '  alias=self.combined\n'
                              '  alias.append(False)\n'
                              'box=Box("word")\n'
                              'print(box.left,box.right,box.combined)\n',
 'function_parameter_reaches_element_schema': 'class Box:\n'
                                              ' def __init__(self,value):self.values=[None,value]\n'
                                              'def build(value):return Box(value)\n'
                                              'print(build("word").values)\n',
 'nested_source_allocation_families': 'class Box:\n'
                                      ' def __init__(self,text):\n'
                                      '  self.rows=[[None,text],[text,None]]\n'
                                      '  alias=self.rows[0]\n'
                                      '  alias.append(7)\n'
                                      '  self.copy=self.rows.copy()\n'
                                      '  self.copy[1].append(False)\n'
                                      'box=Box("word")\n'
                                      'print(box.rows,box.copy,box.rows[0] is box.copy[0])\n',
 'original_directional_fixture': 'class Box:\n'
                                 ' def __init__(self,text):\n'
                                 '  self.text=text\n'
                                 '  self.payload=[None,text]\n'
                                 'box=Box("word")\n'
                                 'print(box.text[-1],box.payload)\n',
 'python_none_is_resolved_not_unknown': 'class Box:\n'
                                        ' def __init__(self):self.values=[None]\n'
                                        'box=Box()\n'
                                        'print(box.values)\n',
 'shallow_copy_keeps_both_allocation_sites': 'class Box:\n'
                                             ' def __init__(self,text):\n'
                                             '  self.original=[None,text]\n'
                                             '  self.copy=self.original.copy()\n'
                                             '  self.copy.append(False)\n'
                                             'box=Box("word")\n'
                                             'print(box.original,box.copy,box.original is box.copy)\n'}


class ClassAllocationPublicationTests(unittest.TestCase):
    def model(self,name,mode):
        source=CASES[name];unit=build_program(source,"allocations.py").main
        before=ast.dump(unit.tree,include_attributes=True)
        model=Model(unit.tree,unit.filename,mode,unit.native_imports,unit=unit).run()
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        expected={unit.ordinal(node)for node in ast.walk(unit.tree)if isinstance(node,ast.List)
                  or isinstance(node,ast.BinOp)and isinstance(node.op,ast.Add)
                  or isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr=="copy"}
        allocations=[allocation for allocation in model.value_constraints.allocations.values()
                     if allocation.category=="list"and allocation.site[0][0]=="class"]
        self.assertEqual({allocation.site[1]for allocation in allocations},expected)
        self.assertEqual(set(model.class_allocation_members),set(allocations))
        for allocation in allocations:
            member=model.class_allocation_members[allocation]
            self.assertIsNotNone(shape(member))
            self.assertEqual(model.value_constraints.kind(value(allocation)),ListType(shape(member)))
        return unit,model,allocations

    def test_original_directional_fixture_has_resolved_common_metadata(self):
        for mode in ("i64","i128","bigint"):
            _,model,allocations=self.model("original_directional_fixture",mode)
            self.assertEqual(len(allocations),1)
            self.assertEqual(model.value_constraints.kind(value(allocations[0])),ListType(NullableType("str")))

    def test_concat_alias_and_copy_retain_each_source_allocation(self):
        for mode in ("i64","i128","bigint"):
            for name,count in (("concat_and_alias_families",3),("shallow_copy_keeps_both_allocation_sites",2)):
                _,model,allocations=self.model(name,mode)
                self.assertEqual(len(allocations),count)
                for allocation in allocations:
                    self.assertEqual(model.value_constraints.kind(value(allocation)),ListType(union_type("none","bool","str")))

    def test_nested_allocations_publish_inner_and_outer_families(self):
        for mode in ("i64","i128","bigint"):
            _,model,allocations=self.model("nested_source_allocation_families",mode)
            self.assertEqual(len(allocations),4)
            kinds=[model.value_constraints.kind(value(allocation))for allocation in allocations]
            inner=ListType(union_type("none","int_bool","str"))
            self.assertEqual(kinds.count(inner),2)
            self.assertEqual(kinds.count(ListType(inner)),2)

    def test_rebinding_does_not_replace_original_allocation_registration(self):
        for mode in ("i64","i128","bigint"):
            _,model,allocations=self.model("alias_rebinding_keeps_original_allocation",mode)
            self.assertEqual(len(allocations),2)
            self.assertEqual({model.value_constraints.kind(value(allocation))for allocation in allocations},
                             {ListType(union_type("none","bool","str")),ListType("int")})

    def test_forwarded_parameter_and_python_none_are_real_kinds(self):
        for mode in ("i64","i128","bigint"):
            _,model,allocations=self.model("function_parameter_reaches_element_schema",mode)
            self.assertEqual(model.value_constraints.kind(value(allocations[0])),ListType(NullableType("str")))
            _,model,allocations=self.model("python_none_is_resolved_not_unknown",mode)
            self.assertEqual(model.value_constraints.kind(value(allocations[0])),ListType("none"))


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ClassAllocationExecutionTests(unittest.TestCase):
    def test_cp_first_programs_preserve_runtime_values_and_aliases(self):
        for name,source in CASES.items():
            expected=subprocess.run([sys.executable,"-I","-S","-c",source],text=True,capture_output=True,timeout=10)
            self.assertEqual(expected.returncode,0,expected.stderr)
            with tempfile.TemporaryDirectory(prefix="pytors-class-allocation-")as directory:
                for mode in ("i64","i128","bigint"):
                    with patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM backend")):
                        result=transpile(source,TranspileOptions(integer=mode,filename="allocations.py"))
                    self.assertTrue(result.success,result.diagnostics)
                    rust=Path(directory,mode+".rs");rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        binary=rust.with_suffix(".opt"if optimized else".debug")
                        build=subprocess.run(["rustc","--edition=2021","--crate-name","allocations",*(["-O"]if optimized else[]),str(rust),"-o",str(binary)],text=True,capture_output=True,timeout=120)
                        self.assertEqual(build.returncode,0,build.stderr)
                        actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,env={**os.environ,"PATH":"/no-python-runtime"})
                        with self.subTest(name=name,mode=mode,optimized=optimized):
                            self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected.stdout,""))


if __name__=="__main__":unittest.main()
