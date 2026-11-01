"""Deferred annotation imports preserve binding presence and cast keeps identity."""
import shutil
import unittest
import test_native_union_ordering as helpers
from py2fastrust import transpile


class TypingAliasProtocolTests(unittest.TestCase):
    def test_runtime_typing_alias_operations_are_explicit(self):
        for source in ('from typing import Tuple\nprint(Tuple)\n','import typing\nprint(typing.Tuple[int,int])\n','from typing import List\nprint(bool(List))\n'):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('metadata-object protocol',str(result.diagnostics[0]))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TypingAliasExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_tuple_annotation(self):
        self.exercise('from typing import Tuple\ndef pair(x:Tuple[int,int])->Tuple[int,int]:return x\nprint(pair((3,4)))\n',("",))

    def test_list_annotation(self):
        self.exercise('from typing import List\ndef total(x:List[int])->int:return sum(x)\nprint(total([1,2,3]))\n',("",))

    def test_alias_annotation(self):
        self.exercise('from typing import Tuple as Pair\ndef pair(x:Pair[int,int]):return x\nprint(pair((2,5)))\n',("",))

    def test_nested_annotations(self):
        self.exercise('from typing import List,Tuple,Optional,Callable\ndef f(x:List[Tuple[int,int]],y:Optional[int]=None)->Tuple[int,int]:return x[0]\nprint(f([(3,8)]))\n',("",))

    def test_module_annotations(self):
        self.exercise('import typing\ndef f(x:typing.Tuple[int,int])->typing.List[int]:return [x[0],x[1]]\nprint(f((4,6)))\n',("",))

    def test_local_import(self):
        self.exercise('def f():\n from typing import Tuple\n def g(x:Tuple[int,int]):return x\n return g((4,9))\nprint(f())\n',("",))

    def test_annotation_side_effects(self):
        self.exercise('from typing import Tuple\ndef note():\n print("annotation")\n return Tuple[int,int]\ndef f(x:note()):return x\nprint(f(7))\n',("",))

    def test_annotation_future(self):
        self.exercise('from __future__ import annotations\nfrom typing import List,Tuple\ndef f(x:List[Tuple[int,int]]):return x\nprint(f([(1,2)]))\n',("",))

    def test_annotation_globals_presence(self):
        self.exercise('from typing import Tuple\nprint("Tuple" in globals())\n',("",))

    def test_annotation_delete_presence(self):
        self.exercise('from typing import Tuple\nprint("Tuple" in globals())\ndel Tuple\nprint("Tuple" in globals())\n',("",))

    def test_cast_scalar(self):
        self.exercise('from typing import cast\nprint(cast(int,7),cast(str,"text"))\n',("",))

    def test_cast_does_not_convert(self):
        self.exercise('from typing import cast\nprint(cast(int,"text"),cast(42,7))\n',("",))

    def test_cast_alias(self):
        self.exercise('from typing import cast as same\nx=[1]\ny=same(list,x)\ny.append(2)\nprint(x,y,x is y)\n',("",))

    def test_cast_module(self):
        self.exercise('import typing\nx=[3]\ny=typing.cast(list,x)\ny.append(4)\nprint(x,y,x is y)\n',("",))

    def test_cast_keywords(self):
        self.exercise('from typing import cast\nx=[2]\ny=cast(val=x,typ=list)\ny.append(3)\nprint(x,y,x is y)\n',("",))

    def test_cast_effects(self):
        self.exercise('from typing import cast\ndef mark(tag,value):\n print(tag,end="|")\n return value\nx=[1]\nprint(cast(mark("type",7),mark("value",x)))\n',("",))

    def test_cast_class(self):
        self.exercise('from typing import cast\nclass A:\n def __init__(self):self.x=3\na=A()\nb=cast(A,a)\nb.x=8\nprint(a.x,a is b)\n',("",))

    def test_cast_no_args(self):
        self.exercise('from typing import cast\nprint(cast())\n',("",))

    def test_cast_one_arg(self):
        self.exercise('from typing import cast\nprint(cast(7))\n',("",))

    def test_cast_excess(self):
        self.exercise('from typing import cast\nprint(cast(1,2,3))\n',("",))

    def test_cast_unknown_keyword(self):
        self.exercise('from typing import cast\nprint(cast(typ=1,val=2,bad=3))\n',("",))

    def test_cast_duplicate(self):
        self.exercise('from typing import cast\nprint(cast(1,2,val=3))\n',("",))

    def test_cast_keyword_priority(self):
        self.exercise('from typing import cast\nprint(cast(1,2,3,bad=4))\n',("",))

    def test_cast_error_effects(self):
        self.exercise('from typing import cast\ndef mark(x):\n print(x,end="|")\n return x\nprint(cast(mark(1),mark(2),mark(3),bad=mark(4)))\n',("",))
