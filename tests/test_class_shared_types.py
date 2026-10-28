"""Shared canonical value types consumed by ordinary functions and methods."""
import ast
import shutil
import unittest
from unittest.mock import patch

from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model, shape, InstanceType
from py2fastrust.native_types import (ListType, TupleType, MaybeType, NullableType,
                                     UnionType, render_type, rust_type, union_type)
from tests import test_native_classes as support


class ClassCanonicalMetadataTests(unittest.TestCase):
    def test_functions_and_methods_share_typed_expressions(self):
        from py2fastrust.native import _Expression
        from py2fastrust.native_classes import Expression
        self.assertIs(Expression,_Expression)

    def test_shared_renderer_recurses_through_storage_overrides(self):
        kind=MaybeType(NullableType(TupleType(("none",ListType("int")))))
        self.assertEqual(rust_type(kind),"Option<Option<((),Vec<NativeInt>)>>")
        seen=[]
        def leaf(value,recurse):
            seen.append(value)
            if isinstance(value,ListType):return "Shared<"+recurse(value.element)+">"
        self.assertEqual(render_type(kind,leaf),"Option<Option<((),Shared<NativeInt>)>>")
        self.assertIn("int",seen)
        self.assertIn(ListType("int"),seen)

    def test_nested_projections_are_deterministic_and_restore_context(self):
        from py2fastrust.native_unions import project
        kind=NullableType(union_type("int","str"))
        pairs=[]
        def pair(a,x,b,y):
            pairs.append((a,x,b,y))
            return f"({x})==({y})"
        def render():
            return project(kind,"left",lambda a,x:project(kind,"right",lambda b,y:pair(a,x,b,y)))
        before=render()
        for a,x,b,y in pairs:
            if a!="none"and b!="none":self.assertNotEqual(x,y)
        with self.assertRaises(ValueError):
            project(kind,"value",lambda kind,code:(_ for _ in ()).throw(ValueError()))
        self.assertEqual(render(),before)

    def test_allocation_members_use_directional_common_constraints(self):
        from py2fastrust.native_constraints import value
        source='''class Box:
 def __init__(self,text):
  self.text=text
  self.payload=[None,text]
box=Box("word")
print(box.text[-1],box.payload)
'''
        unit=build_program(source,"directional.py").main
        model=Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit).run()
        owner=model.classes["Box"]
        self.assertEqual(shape(owner.fields["text"].cell),"str")
        self.assertEqual(shape(owner.methods["__init__"].arguments["text"]),"str")
        self.assertEqual(shape(owner.fields["payload"].cell),ListType(NullableType("str")))
        allocation_node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.List))
        allocations=[allocation for allocation in model.value_constraints.allocations.values()
                     if allocation.site[1]==unit.ordinal(allocation_node)]
        self.assertEqual(len(allocations),1)
        self.assertEqual(model.value_constraints.kind(value(allocations[0])),ListType(NullableType("str")))

    def test_class_constraints_publish_actual_canonical_kinds(self):
        source='''class Box:
 def __init__(self):
  self.values=[1,False]
  self.item=None
 def choose(self,flag):
  if flag:return (1,"x")
  return None
 def replace(self):
  self.item="set"
x=Box()
x.replace()
print(x.choose(True),x.values,x.item)
'''
        unit=build_program(source,"canonical.py").main
        model=Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit).run()
        owner=model.classes["Box"]
        self.assertEqual(shape(owner.fields["values"].cell),ListType("int_bool"))
        self.assertEqual(shape(owner.fields["item"].cell),NullableType("str"))
        self.assertEqual(shape(owner.methods["choose"].result),NullableType(TupleType(("int","str"))))
        self.assertEqual(shape(owner.methods["choose"].arguments["self"]),InstanceType("Box"))


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ClassSharedTypeExecutionTests(unittest.TestCase):
    compile=support.NativeClassTests.compile
    compare=support.NativeClassTests.compare

    def paired(self,body,calls):
        ordinary="def choose(value):\n"+"\n".join(" "+line for line in body.splitlines())+"\n"+calls.replace("CALL","choose")
        methods="class Box:\n def choose(self,value):\n"+"\n".join("  "+line for line in body.splitlines())+"\nbox=Box()\n"+calls.replace("CALL","box.choose")
        self.compare(ordinary)
        self.compare(methods)

    def test_nullable_method_and_function_results(self):
        self.paired("if value:return value*2", "print(CALL(0),CALL(3))\n")

    def test_finite_immutable_results_and_truth(self):
        self.paired("if value:return 9\nreturn 'zero'", "a=CALL(1)\nb=CALL(0)\nprint(a,b,bool(a),bool(b),a==9,b=='zero',a is None,b is None)\n")

    def test_none_and_empty_tuple_remain_distinct(self):
        self.paired("if value:return ()\nreturn None", "a=CALL(1)\nb=CALL(0)\nprint(a,b,bool(a),bool(b),a is None,b is None,a==b)\n")

    def test_joined_tuple_payload_and_nullable_default(self):
        self.compare('''class Box:
 def choose(self,flag):
  if flag:return (1,())
  return ("a",None)
 def echo(self,value=None):
  return value
box=Box()
print(box.choose(True),box.choose(False))
print(box.echo(),box.echo("x"),box.echo(4))
''')

    def test_fields_keep_none_separate_from_missing(self):
        self.compare('''class Box:
 def __init__(self,flag):
  if flag:self.value=None
 def set(self,value):
  self.value=value
 def read(self):
  return self.value
box=Box(1)
print(box.read(),box.value is None)
box.set("set")
print(box.read(),box.value is None)
box.set(9)
print(box.read(),bool(box.value))
missing=Box(0)
print("before missing")
print(missing.read())
''')

    def test_list_element_unions_keep_handles_shared(self):
        self.compare('''class Bag:
 def __init__(self,values):
  self.values=values
 def expose(self):
  return self.values
 def add(self,value):
  self.values.append(value)
xs=[1]
bag=Bag(xs)
alias=bag.expose()
bag.add(None)
bag.add("text")
alias[0]=False
print(xs,bag.values,alias,xs is alias)
print(xs[1] is None,xs[2]=="text",bool(xs[0]))
print(alias.pop(),xs)
''')

    def test_tuple_list_payload_representation_is_kind_aware(self):
        self.compare('''class Bag:
 def __init__(self):
  self.values=[None,(),(1,),"x",7,False]
 def expose(self):
  return self.values
bag=Bag()
print(bag.values)
for value in bag.expose():
 print(value,value is None,bool(value))
''')

    def test_expression_joins_preserve_short_circuit_effects(self):
        self.compare('''class Box:
 def mark(self,value):
  print(value)
  return value
 def choose(self,flag):
  return self.mark(7) if flag else self.mark("no")
 def either(self,flag):
  return flag and self.choose(flag)
box=Box()
print(box.choose(0),box.choose(1),box.either(False),box.either(True))
''')

    def test_nullable_list_payload_equality_and_membership(self):
        self.compare('''class Box:
 def __init__(self):
  self.values=[1,None,"x",()]
 def copy(self):
  return self.values.copy()
box=Box()
copy=box.copy()
print(copy==box.values,copy is box.values)
print(None in copy,"x" in copy,False in copy,() in copy)
copy[0]=3
print(copy==box.values,copy!=box.values,box.values,copy)
''')

    def test_independent_random_inputs_have_identical_side_effects(self):
        import random
        random_source=random.Random(1973)
        inputs=[random_source.randrange(-30,31)for _ in range(60)]
        source='''class Choice:
 def select(self,n):
  if n%4==0:return None
  if n%4==1:return n+3
  if n%4==2:return str(n)
  return (n,())
choice=Choice()
xs=[]
for i in range(int(input())):
 value=choice.select(int(input()))
 xs.append(value)
 print(value,value is None,bool(value),value==0,value=="0")
print(xs)
'''
        self.compare(source,data=str(len(inputs))+"\n"+"\n".join(map(str,inputs))+"\n")

    def test_two_finite_operands_do_not_capture_the_other_payload(self):
        self.paired("if value:return value+1\nreturn None", "a=CALL(1)\nb=CALL(2)\nc=CALL(0)\nprint(a==b,a==c,b!=a,a==a,c==c)\n")
        self.compare('''class Box:
 def __init__(self):
  self.a=[1,None,"x"]
  self.b=[2,None,"x"]
box=Box()
print(box.a==box.b,box.a!=box.b,box.a==box.a)
''')

    def test_unicode_cached_text_survives_canonical_field_and_list_unions(self):
        from tests.test_native_cached_text import NativeCachedTextTests
        NativeCachedTextTests.compare(self,'''class Box:
 def __init__(self,text):
  self.text=text
  self.payload=[None,text]
 def replace(self,text):
  self.text=text
  self.payload.append(text)
 def inspect(self):
  return self.text[-1],len(self.text),self.payload
box=Box(input())
old=box.text
box.replace("é🙂")
print(old,box.inspect(),box.payload[0] is None,box.payload[1]==old)
''',("あ🙂é\n",),policies=("unicode",))

    def test_float_identity_sensitive_finite_containers_remain_unproved(self):
        from py2fastrust import transpile,TranspileOptions
        source='''class Box:
 def __init__(self,value):
  self.values=[None,value]
n=float("nan")
box=Box(n)
print(n in box.values)
'''
        for mode in ("i64","i128","bigint"):
            with self.subTest(mode=mode),patch("py2fastrust.codegen.generate",side_effect=AssertionError("fallback")):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")

    def test_uncertain_mutable_handle_join_is_explicit(self):
        # Allocation-flow solver integration is required before nullable handles.
        from py2fastrust import transpile
        source='''class Box:
 def choose(self,flag):
  if flag:return [1]
  return None
print(Box().choose(True))
'''
        with patch("py2fastrust.codegen.generate",side_effect=AssertionError("fallback")):
            result=transpile(source)
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
