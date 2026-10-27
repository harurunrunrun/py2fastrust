"""Arbitrary-precision scalar programs execute compiled Rust directly."""
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from test_native_extrema import EXAMPLE


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeBigIntTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-native-bigint-")
        cls.next_binary = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self,source,release=True,header=False):
        if header:
            result=transpile(source,TranspileOptions(integer="bigint",filename="main.py"))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            rust=result.rust_source
        else:
            rust=try_generate_native(source,"main.py","bigint")
        self.assertIsNotNone(rust,source)
        for forbidden in ["enum Value","enum Op","struct Runtime","fn step(","struct PegParser"]:
            self.assertNotIn(forbidden,rust)
        type(self).next_binary+=1
        path=Path(self.tmp.name,f"program{self.next_binary}.rs")
        path.write_text(rust,encoding="utf-8")
        binary=path.with_suffix("")
        build=subprocess.run(["rustc","--edition=2021",*(["-O"] if release else []),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
        self.assertEqual(build.returncode,0,build.stderr+"\n"+source)
        return binary,rust

    def compare(self,binary,source,data=""):
        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5)
        expected=subprocess.run([sys.executable,"-c",source],input=data,capture_output=True,text=True,timeout=5)
        self.assertEqual(actual.stdout,expected.stdout,source+"\n"+data)
        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+"\n"+expected.stderr)
        if actual.returncode:
            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],expected.stderr.splitlines()[-1].split(":")[0])

    def differential(self,source,inputs=("",)):
        binary,_=self.compile(source)
        for data in inputs:
            self.compare(binary,source,data)

    def test_reported_program_is_compact_in_both_build_profiles(self):
        for release in [False,True]:
            binary,rust=self.compile(EXAMPLE,release,header=True)
            self.assertLess(len(rust.encode("utf-8")),512*1024)
            for unused in ["fn pow(","fn shl(","fn shr(","fn modpow("]:
                self.assertNotIn(unused,rust)
            for data in ["1 2 10\n","10 3 1\n","-5 -3 7\n","7 0 9\n","1 2\n","1 2 3 4 invalid\n","1 2 invalid\n","\n","",f"{-10**120} 3 {10**120}\n"]:
                with self.subTest(release=release,data=data):
                    self.compare(binary,EXAMPLE,data)

    def test_arithmetic_and_bitwise_random_limb_boundaries(self):
        source='''a=int(input())
b=int(input())
print(a+b,a-b,a*b,a//b,a%b,a&b,a|b,a^b,~a,-a,abs(a))
print(a<<71,a>>71,a**3)
'''
        rng=random.Random(3817)
        boundaries=[0,1,-1,2**31-1,2**31,2**32,2**63,2**127-1,2**127,2**128,2**256+1]
        pairs=[(a,b) for a in boundaries for b in [-2**128-1,-7,-1,1,3,2**129+7]]
        pairs += [(rng.randrange(-2**rng.randrange(1,700),2**rng.randrange(1,700)),rng.choice([-1,1])*rng.randrange(1,2**rng.randrange(1,350))) for _ in range(80)]
        for release in [False,True]:
            binary,_=self.compile(source,release)
            for a,b in pairs:
                self.compare(binary,source,f"{a}\n{b}\n")

    def test_branch_join_clones_and_straight_line_retyping(self):
        source='''a=b=10**100
c=a
if int(input()):
    a=True
else:
    a=10**120
print(a,b,c)
a,b=b,a
print(a,b)
a=False
print(a)
a=1<<300
print(a,a&True,True|a)
'''
        self.differential(source,["0\n","1\n"])

    def test_loops_break_continue_and_large_range_cursors(self):
        source='''n=int(input())
total=10**100
i=99
for i in range(n):
    if i%3==0:
        continue
    total+=i*i
    if i>12:
        break
j=0
while j<5:
    j+=1
    total^=j<<150
print(total,i,j)
for k in range(10**100,10**100+3):
    k+=5
print(k)
for k in range(10**100+7,10**100,-2):
    print(k,end=" ")
print()
'''
        self.differential(source,["0\n","1\n","17\n","-5\n"])

    def test_loop_header_and_exit_boolean_integer_unions(self):
        source='''v=True
for i in range(4):
    print(v,v&True,v|False,v^True)
    if i%2:
        v=True
        continue
    v=10**100+i
print(v)
v=True
j=0
while j<4:
    print(v)
    if j%2:
        v=False
    else:
        v=10**90+j
    j+=1
print(v)
'''
        self.differential(source)

    def test_min_max_ties_default_and_evaluation_order(self):
        source='''print(max(False,0),max(0,False),min(True,1),min(1,True))
print(max(int(input()),int(input()),int(input())),int(input()))
print(min([10**100,10**99],default=int(input())),int(input()))
print(min([],default=True),max((),default=10**100),max([False,0]),min((True,1)))
'''
        self.differential(source,["7\n3\n7\n99\n77\n88\n"])
        for name in ["min","max"]:
            self.differential(f"print(1)\nprint({name}([]))\n")

    def test_short_circuit_comparison_and_call_order(self):
        source='''a=int(input())
b=int(input())
print(a and b,a or b,0 and int(input()),1 or int(input()))
print(int(input())<int(input())<int(input()))
print(int(input()))
print(int(input())//int(input()),int(input()))
'''
        self.differential(source,["0\n5\n9\n1\n7\n8\n2\n17\n0\n99\n","5\n0\n1\n9\n7\n8\n17\n2\n99\n"])

    def test_modular_exponents_and_inverse_errors(self):
        source='''a=int(input())
b=int(input())
c=int(input())
print(pow(a,b,c))
'''
        self.differential(source,[f"{a}\n{b}\n{c}\n" for a,b,c in [(10**100+3,12345,10**80+7),(3,-1,10**100),(10,-1,100),(9,0,-7),(3,-3,-11),(0,0,0)]])

    def test_input_unicode_lazy_unpack_and_operation_errors(self):
        self.differential("print(9)\na,b=map(int,input().split())\nprint(a,b)\n",["１２ ٤\n","+1_000 -9\n","1\n","\n","1 2 3 invalid\n","1 2 invalid\n","1 invalid 3\n","1\x1c2\n",""])
        for expression,data in [("int(input())",["１２\r\n","-٤\n","1\x1c\n","-\n"]),("int('１２３')",[""]),("int('bad')",[""]),("1//0",[""]),("1<<-1",[""]),("0<<int(input())",[f"{10**100}\n"]),("-9>>int(input())",[f"{10**100}\n"]),("1<<int(input())",[f"{10**100}\n"]),("1//int(input())",["0\n"])]:
            self.differential(f"print(9)\nprint({expression})\n",data)

    def test_unproved_types_effects_and_rebinding_use_general_aot(self):
        sources=["print(2**-1)\n","print(2**int(input()))\n","print(1/2)\n","x=[]\nprint(x)\n","def f(x):return x\ng=f\nprint(g(1))\n","bool=lambda x:3\nprint(bool(1))\n","max=lambda *x:7\nprint(max(1,2))\n","for i in range(int(input())):\n pass\nprint(i)\n"]
        for source in sources:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source,"main.py","bigint"))
