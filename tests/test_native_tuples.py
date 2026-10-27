"""Structural immutable tuple values use native Rust tuples in every mode."""
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_types import TupleType,ListType,MaybeType,rust_type,kind_tag,join_types,tuple_code,tuple_field


class StructuralTypeTests(unittest.TestCase):
    def test_shape_rendering_and_finite_numeric_joins(self):
        self.assertEqual(rust_type(TupleType(("int","str","bool"))),"(NativeInt,NativeText,bool)")
        self.assertEqual(rust_type(ListType(TupleType(("int","str")))),"Vec<(NativeInt,NativeText)>")
        self.assertEqual(rust_type(MaybeType(TupleType(("bool",)))),"Option<(bool,)>")
        self.assertEqual(rust_type("maybe_bytes"),"Option<Vec<u8>>")
        self.assertNotEqual(kind_tag(TupleType(("int",))),kind_tag(TupleType(("int","int"))))
        self.assertEqual(join_types(TupleType(("int","str")),TupleType(("bool","str"))),TupleType(("int_bool","str")))
        self.assertEqual(tuple_code(()),"()")
        self.assertEqual(tuple_field("value",1),"(value).1")


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeTupleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="pytors-native-tuple-")
        cls.serial=0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self,source,mode,release):
        result=transpile(source,TranspileOptions(integer=mode,filename="tuple.py"))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,"native")
        self.assertLess(len(result.rust_source.encode()),512*1024)
        for forbidden in ["enum Value","enum Op","struct Runtime","fn step("]:
            self.assertNotIn(forbidden,result.rust_source)
        type(self).serial+=1
        path=Path(self.tmp.name,f"program{self.serial}.rs");path.write_text(result.rust_source)
        binary=path.with_suffix("")
        build=subprocess.run(["rustc","--edition=2021",*(["-O"] if release else []),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
        self.assertEqual(build.returncode,0,build.stderr+"\n"+source)
        return binary

    def differential(self,source,inputs=("",),modes=("i64","i128","bigint"),profiles=(False,True),trace=False):
        references=[subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=5) for data in inputs]
        for mode in modes:
            for release in profiles:
                binary=self.compile(source,mode,release)
                for data,reference in zip(inputs,references):
                    with self.subTest(mode=mode,release=release,data=data):
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5,
                                              env={"PATH":"/unavailable","PYTHONPATH":"/unavailable"})
                        self.assertEqual(actual.stdout,reference.stdout)
                        self.assertEqual(actual.returncode,reference.returncode,actual.stderr+"\n"+reference.stderr)
                        if actual.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],reference.stderr.splitlines()[-1].split(":")[0])
                            if trace:self.assertEqual(re.findall(r"line (\d+), in ([^\n]+)",actual.stderr),re.findall(r"line (\d+), in ([^\n]+)",reference.stderr))

    def test_literals_aliases_unpacked_heterogeneous_fields_and_repr(self):
        source='''t=(7,'é\\n\u200b',True)
u=t
t=(9,'changed',False)
a,b,c=u
print(t,u,a,b,c)
print(u[0],u[-1],len(u),bool(u),tuple(u),tuple(),())
print(*u,sep='|',end='!')
print((1,),(),(False,0,'both\\\'"'))
'''
        self.differential(source)

    def test_tuple_function_arguments_returns_defaults_and_type_variants(self):
        source='''def make(x):
    return x+1,'name',True
def alter(value,extra=(3,'default',False)):
    a,b,c=value
    return a+extra[0],b+extra[1],c
def first(value):
    return value[0]
g=make
t=g(int(input()))
print(t,alter(t),alter((7,'x',False),(8,'y',True)))
print(first((True,'a')),first((9,'b')),t)
'''
        self.differential(source,["3\n","-8\n"])

    def test_tuple_fields_evaluate_in_order_before_binding_and_print(self):
        source='''def mark(x):
    print(x)
    return x
a,b=(mark(int(input())),mark(int(input())))
t=(mark(a),mark(b),mark(7))
print(t,mark(8))
'''
        self.differential(source,["1\n2\n","1\ninvalid\n"],trace=True)

    def test_numeric_bool_equality_lexicographic_order_and_short_circuit(self):
        source='''a=(int(input()),'x')
b=(0,1)
print((True,'x')==(1,'x'),(False,)==(0,),(True,)<(2,))
print((1,)<(1,0),(1,0)>(1,),()==(),()<(0,))
print((1,'x')==(1,2),(1,'x')!=(1,2))
print(2<1<(int(input()),))
print(a<b)
'''
        self.differential(source,["-1\n7\n","0\n7\n","1\n7\n"],trace=True)

    def test_constant_dynamic_indices_and_bounds(self):
        source="t=(True,7,False)\nprint(t[int(input())],t)\n"
        self.differential(source,["0\n","1\n","-1\n","3\n","-4\n"])
        self.differential(source,[str(10**180)+"\n",str(-10**180)+"\n"],modes=("bigint",))
        self.differential("t=(1,'x',True)\nprint(t[9])\n")

    def test_branch_shape_numeric_field_joins(self):
        source='''if int(input()):
    value=(True,'same')
else:
    value=(7,'same')
print(value,value[0],value==(1,'same'),value<(2,'same'))
alias=value
value=(False,'other')
print(alias,value)
'''
        self.differential(source,["0\n","1\n"])

    def test_zero_loop_optional_tuple_binding_and_exception_names(self):
        source='''for i in range(int(input())):
    value=(i,'é',i%2==1)
print(value)
'''
        local='''def run(n):
    for i in range(n):
        value=(i,'local',True)
    return value
print(run(int(input())))
'''
        self.differential(source,["0\n","1\n","4\n"],trace=True)
        self.differential(local,["0\n","1\n","4\n"],trace=True)

    def test_tuple_reassignments_across_loop_edges_and_while(self):
        source='''value=(9,'start',False)
for i in range(int(input())):
    value=(i,'next',i%2==1)
    if i==2:
        continue
    if i==4:
        break
i=0
while i<3:
    value=(value[0]+1,value[1],True)
    i+=1
print(value)
'''
        self.differential(source,["0\n","1\n","7\n"])

    def test_independent_random_tuple_comparisons_and_unicode_repr(self):
        source='''a=(int(input()),input(),bool(int(input())))
b=(int(input()),input(),bool(int(input())))
print(a,b)
print(a==b,a!=b,a<b,a<=b,a>b,a>=b)
'''
        rng=random.Random(916028)
        strings=["","a","é","αβ","'\"\\","\t","\u200b","\u0085","😀"]
        cases=[]
        for _ in range(75):
            a=rng.randrange(-7,8);b=rng.choice([a,rng.randrange(-7,8)])
            cases.append(f"{a}\n{rng.choice(strings)}\n{rng.randrange(2)}\n{b}\n{rng.choice(strings)}\n{rng.randrange(2)}\n")
        self.differential(source,cases,profiles=(True,))

    def test_unproved_mutable_tuple_fields_reject(self):
        for source in ["A=[]\nt=(A,)\nA.append(1)\nprint(t)\n","t=([1],)\nprint(t)\n",
                       "t=({'a':1},)\nprint(t)\n"]:
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode,filename="unsupported.py"))
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
