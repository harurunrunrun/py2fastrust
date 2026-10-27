"""Typed tuple keys retain Python numeric equality and dictionary key order."""
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile
from wrapping_reference import execute


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeTupleKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="pytors-native-tuple-key-")
        cls.serial=0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def differential(self,source,inputs=("",),modes=("i64","i128","bigint"),profiles=(False,True),wrapping=False):
        references=[subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=5) for data in inputs]
        for mode in modes:
            expected=[execute(source,mode,data) for data in inputs] if wrapping else references
            result=transpile(source,TranspileOptions(integer=mode,filename="keys.py"))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            self.assertLess(len(result.rust_source.encode()),512*1024)
            for forbidden in ["enum Value","enum Op","struct Runtime","fn step("]:
                self.assertNotIn(forbidden,result.rust_source)
            for release in profiles:
                type(self).serial+=1
                path=Path(self.tmp.name,f"program{self.serial}.rs");path.write_text(result.rust_source)
                binary=path.with_suffix("")
                build=subprocess.run(["rustc","--edition=2021",*(["-O"] if release else []),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                self.assertEqual(build.returncode,0,build.stderr+"\n"+source)
                for data,reference in zip(inputs,expected):
                    with self.subTest(mode=mode,release=release,data=data):
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5,
                                              env={"PATH":"/unavailable","PYTHONPATH":"/unavailable"})
                        self.assertEqual(actual.stdout,reference.stdout)
                        self.assertEqual(actual.returncode,reference.returncode,actual.stderr+"\n"+(reference.exception_message or "" if wrapping else reference.stderr))
                        if actual.returncode:self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],reference.exception_type if wrapping else reference.stderr.splitlines()[-1].split(":")[0])

    def test_bool_integer_tuple_key_equality_and_original_dictionary_key_retention(self):
        source='''S={(True,'x'),(1,'x'),(2,'y')}
D={(True,'x'):1,(1,'x'):2,(2,'y'):3}
print(len(S),len(D),(True,'x') in S,(1,'x') in S,(False,'x') not in S)
print(D[(True,'x')],D[(1,'x')],D.get((9,'z'),-1))
for key,value in D.items():
    print(key,value)
for key in D:
    print(key)
for value in D.values():
    print(value)
'''
        self.differential(source)

    def test_numeric_key_shape_widens_without_losing_bool_keys_or_values(self):
        source='''S={(True,'x')}
S.add((1,'x'))
S.add((2,'x'))
print(len(S),(True,'x') in S,(1,'x') in S,(2,'x') in S)
D={(True,'x'):7}
D[(1,'x')]=8
D[(2,'x')]=True
print(D[(True,'x')],D[(1,'x')],D[(2,'x')])
for key,value in D.items():
    print(key,value)
'''
        self.differential(source)

    def test_literal_and_assignment_evaluation_order(self):
        source='''def mark(x):
    print(x)
    return x
D={(mark(1),mark(2)):mark(3),(mark(4),mark(5)):mark(6)}
S={(mark(7),mark(8)),(mark(9),mark(10))}
D[(mark(11),mark(12))]=mark(13)
print(D.get((mark(14),mark(15)),mark(16)),len(S))
'''
        self.differential(source)

    def test_immutable_tuple_values_and_unicode_keys(self):
        source='''D={('猫',7):(1,'first',True),('é',8):(2,'second',False)}
print(D[('猫',7)],D.get(('missing',9),(0,'default',False)))
D[('猫',7)]=(3,'new',True)
for key,value in D.items():
    print(key,value)
S={('猫',7),('é',8)}
print(('猫',7) in S,('海',7) in S)
'''
        self.differential(source)

    def test_copies_clear_and_proved_empty_container_retyping(self):
        source='''S={(1,2)}
T=S.copy()
S.clear()
S.add(('new',True))
D={(1,2):7}
E=D.copy()
D.clear()
D[('new',True)]='text'
print(len(S),len(T),(1,2) in T,('new',True) in S)
print(len(D),len(E),D[('new',True)],E[(1,2)])
'''
        self.differential(source)

    def test_straight_line_empty_set_dict_refinement(self):
        source='''S=set()
S.add((1,2))
D={}
D[(1,2)]=7
print(len(S),len(D),(1,2) in S,D[(1,2)])
'''
        self.differential(source)
        self.differential("print(len(set()),bool(set()),len({}),bool({}))\n",modes=("bigint",))

    def test_bigint_hash_representation_and_limb_boundaries(self):
        source='''n=int(input())
S={(n,'x'),(n+1,'x'),(n-n+1,'one')}
D={(n,'x'):7,(n-n+1,'one'):11}
print(len(S),(n,'x') in S,(n+1,'x') in S,(True,'one') in S)
print(D[(n,'x')],D[(True,'one')],D.get((n+2,'x'),-1))
D[(n+1,'x')]=13
for key,value in D.items():
    print(key,value)
'''
        values=[0,1,-1,2**31,2**32,2**63,2**127,2**128,-2**128,10**200,-10**200,2**700+1]
        self.differential(source,[f"{value}\n" for value in values],modes=("bigint",))

    def test_fixed_width_tuple_key_collisions_follow_wrapping_reference(self):
        source='''n=int(input())
S={(n,),(0,),(True,)}
D={(n,):7,(0,):9,(True,):11}
print(len(S),len(D),D[(n,)],D[(0,)],D[(1,)])
for key,value in D.items():
    print(key,value)
'''
        values=[0,1,-1,2**63,2**64,2**64+1,2**128,2**128+1,-2**128-1]
        self.differential(source,[f"{value}\n" for value in values],modes=("i64","i128"),wrapping=True)

    def test_missing_key_preserves_prefix_output_and_keyerror(self):
        source="D={(1,'x'):7}\nprint(99)\nprint(D[(int(input()),'x')])\n"
        self.differential(source,["1\n","2\n","0\n"])

    def test_wide_tuple_keys_avoid_rust_eq_hash_trait_arity_limit(self):
        for size in (12,13,25,257):
            key="("+",".join(str(index) for index in range(size))+")"
            source=f"S={{{key}}}\nD={{{key}:7}}\nT=S.copy()\nE=D.copy()\nprint(len(S),len(T),{key} in T,D[{key}],E[{key}])\n"
            self.differential(source,profiles=(True,))

    def test_integer_tuple_no_optimize_retains_unicode_data_notice(self):
        result=transpile("value=(1,2)\nprint(value)\n",TranspileOptions(integer="i64",optimize=False))
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn("const NATIVE_TUPLE_PRINTABLE",result.rust_source)
        self.assertIn("UNICODE LICENSE V3",result.rust_source)

    def test_seeded_dictionary_counts_and_set_membership(self):
        source='''n=int(input())
D={(0,0):0}
S={(0,0)}
for i in range(n):
    a,b=map(int,input().split())
    key=(a,b)
    D[key]=D.get(key,0)+1
    S.add(key)
print(len(D),len(S))
for key,value in D.items():
    print(key,value)
'''
        rng=random.Random(624199)
        cases=[]
        for _ in range(65):
            pairs=[(rng.randrange(-5,6),rng.randrange(-5,6)) for _ in range(rng.randrange(0,25))]
            cases.append(str(len(pairs))+"\n"+"".join(f"{a} {b}\n" for a,b in pairs))
        self.differential(source,cases,profiles=(True,))

    def test_mutable_aliases_fields_unknown_shapes_and_observable_set_order_reject(self):
        programs=["D={(1,2):7}\nE=D\nE[(1,2)]=9\n",
                  "S=T={(1,2)}\nS.add((3,4))\n",
                  "D={(1,2):[]}\nprint(len(D))\n",
                  "A=[]\nS={(A,)}\nprint(len(S))\n",
                  "D={(1,2):7}\nD[('x',2)]=8\n",
                  "S={(1,2)}\nfor key in S:\n print(key)\n",
                  "D={(1,2):7}\nfor key in D:\n D[key]=8\n",
                  "D={}\nfor i in range(3):\n D[(i,i)]=i\n"]
        for source in programs:
            for mode in ("i64","i128","bigint"):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename="unproved.py"))
                    self.assertFalse(result.success)
                    self.assertIsNone(result.rust_source)
                    self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
