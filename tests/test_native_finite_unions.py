"""Shared finite shapes across native joins, returns, and value operations."""
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_types import (TupleType,MaybeType,NullableType,UnionType,
    union_type,join_types,rust_type,alternatives)
from py2fastrust.typeflow import TypeSet


class FiniteTypeTests(unittest.TestCase):
    def test_canonical_join_and_missing_binding_are_distinct(self):
        nullable=join_types("none","int")
        self.assertEqual(nullable,NullableType("int"))
        self.assertEqual(join_types("str",nullable),join_types(nullable,"str"))
        self.assertEqual(union_type("none","bool","int","str"),NullableType(UnionType(("int_bool","str"))))
        self.assertEqual(rust_type(MaybeType(nullable)),"Option<Option<NativeInt>>")
        self.assertNotEqual(rust_type("none"),rust_type(NullableType(TupleType(()))))
        self.assertIsNone(TypeSet.from_kind(nullable).join(TypeSet(maybe_unbound=True)).native_kind)
        self.assertEqual(TypeSet.from_kind(nullable).join(TypeSet.from_kind("str")).native_kind,join_types(nullable,"str"))


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class FiniteUnionTests(unittest.TestCase):
    def compare(self,source,inputs=("0\n","1\n","4\n"),*,release=True):
        for integer in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=integer,filename="finite.py"))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            self.assertNotIn("enum Value",result.rust_source)
            self.assertNotIn("struct Runtime",result.rust_source)
            self.assertNotIn("_typed_return",result.rust_source)
            for optimized in (False,True) if release else (False,):
                with self.subTest(integer=integer,optimized=optimized):
                    with tempfile.TemporaryDirectory(prefix="pytors-finite-") as directory:
                        path=Path(directory,"main.rs");path.write_text(result.rust_source)
                        binary=path.with_suffix("")
                        compiled=subprocess.run(["rustc","--edition=2021",*(["-O"] if optimized else []),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                        self.assertEqual(compiled.returncode,0,compiled.stderr)
                        for data in inputs:
                            expected=subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=5)
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5)
                            self.assertEqual(actual.returncode,expected.returncode,(data,actual.stderr,expected.stderr))
                            self.assertEqual(actual.stdout,expected.stdout,(data,actual.stderr))
                            if expected.returncode:
                                self.assertEqual(actual.stderr.strip().splitlines()[-1],expected.stderr.strip().splitlines()[-1])

    def test_nullable_literals_truth_identity_and_value_aliases(self):
        self.compare('''n=int(input())
x=7 if n else None
y=z=x
print(None,x,y,z,x is None,x is not None,not x,bool(x))
print(x==None,x!=None,() is None)
''')

    def test_finite_branch_shapes_keep_original_tags(self):
        self.compare('''n=int(input())
if n%3==0:x=True
elif n%3==1:x="one"
else:x=2
y=x
print(x,y,bool(x),x==y,x==True,x=="one")
x=None
print(x,y,y is None)
''',tuple(str(n)+"\n" for n in range(6)))

    def test_unique_mutable_alternative_is_moved_and_printed(self):
        self.compare('''n=int(input())
if n:x=[1,2]
else:x=True
print(x,bool(x),not x)
x=None
print(x)
''')

    def test_existing_boolean_integer_list_acceptance(self):
        self.compare('''n=int(input())
x=True if n else 2
a=[x]
a.append(False)
print(a,a[0],a[1],a.copy())
''')

    def test_explicit_and_implicit_none_returns_share_typed_shape(self):
        self.compare('''def choose(n):
 print("choose",n)
 if n%3==0:return
 if n%3==1:return 17
def relay(x):
 print("relay",x)
 return x
n=int(input())
x=choose(n)
print(x,relay(x),x is None)
''',("0\n","1\n","2\n"))

    def test_function_return_joins_preserve_strings_bool_and_integer(self):
        self.compare('''def choose(n):
 if n%3==0:return False
 if n%3==1:return "abc"
 return 23
def relay(value,other=None):
 print("args",value,other)
 return value
x=choose(int(input()))
print(x,relay(x),bool(x))
''')

    def test_none_and_empty_tuple_keep_distinct_tags(self):
        self.compare('''def choose(n):
 if n:return ()
 return None
x=choose(int(input()))
print(x,x is None,x==(),bool(x))
''')

    def test_zero_iteration_unbound_is_distinct_from_bound_none(self):
        self.compare('''for i in range(int(input())):
 x=None if i%2 else "set"
print(x,x is None)
''',("0\n","1\n","2\n"))
        self.compare('''def f(n):
 if n:value=None
 print(value is None)
f(int(input()))
''',("0\n","1\n"),release=False)

    def test_next_none_default_retains_iterator_end_and_none_value(self):
        self.compare('''def default():
 print("default")
 return None
n=int(input())
x=next((int(input()) for i in range(n)),default())
print(x,x is None,int(input()))
print(next(iter([None]),7),next(iter([]),None))
''',("0\n91\n","1\n17\n93\n"),release=False)

    def test_list_fields_use_shared_union_coercion(self):
        self.compare('''n=int(input())
a=[None,3,"s",False]
a.append("t" if n else None)
print(a,a[0],a[1],a[2],a[3],a[4])
''',release=False)

    def test_structural_tuple_fields_join_and_compare_as_values(self):
        self.compare('''n=int(input())
if n:x=(7,"s")
else:x=("seven",True)
y=x
print(x,y,x==y,x!=(8,"s"),x[0],x[1])
''',release=False)

    def test_independent_random_branch_return_differential(self):
        rng=random.Random(63019)
        inputs=tuple(str(rng.randrange(-100000,100000))+"\n" for _ in range(50))
        self.compare('''def choose(n):
 if n%5==0:return None
 if n%5==1:return bool(n%2)
 if n%5==2:return n*7
 if n%5==3:return "文字"
 return ()
n=int(input())
x=choose(n)
y=x or "fallback"
print(x,y,bool(x),x is None,x==y)
''',inputs,release=False)

    def test_mutable_union_aliases_retain_the_selected_shared_reference(self):
        source="if int(input()):x=[1]\nelse:x=True\ny=x\nprint(x,y)"
        self.compare(source,release=True)

    def test_promoted_exact_tuple_shape_and_index_sources(self):
        self.compare("t=(1,'x')\nprint(t[int(input())])\n",("-3\n","-2\n","-1\n","0\n","1\n","2\n"),release=False)
        self.compare("if int(input()):\n t=(1,)\nelse:\n t=(1,2)\nprint(t)\n",release=False)

    def test_promoted_exact_function_return_sources(self):
        for source in (
            "def f(x): return [x]\nprint(f(1))",
            "def f(x):\n if x: return 1\nprint(f(0))",
            "def f(x): pass\ny=f(1)\nprint(y)",
            "def f(x):\n return x if x else False\nprint(f(7))\n",
        ):
            self.compare(source,("",),release=False)

    def test_promoted_exact_container_union_sources(self):
        for source in (
            "if int(input()):x=[1]\nelse:x=True\nprint(x)",
            "n=int(input())\nx=True if n else 2\na=[x]\nprint(a)",
        ):
            self.compare(source,release=False)

    def test_promoted_already_supported_empty_list_baseline_source(self):
        # This exact program already lowers in the saved pre-union baseline.
        for source in ("x=[]\nprint(x)\n",):
            self.compare(source,("",),release=False)

    def test_owned_mutable_union_returns_and_nested_function_return_lines(self):
        self.compare('''def choose(n):
 for i in range(n):
  if i==2:return [i]
 return True
def fresh(n):
 value=choose(n)
 return value
n=int(input())
print(fresh(n))
''',release=False)
