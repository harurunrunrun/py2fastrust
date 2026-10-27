"""BigInt list ownership, internal bounds, evaluation order and direct Rust."""
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeBigIntListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-bigint-list-")
        cls.serial = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, release=True):
        result = transpile(source, TranspileOptions(integer="bigint", filename="arrays.py"))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, "native")
        rust = result.rust_source
        self.assertLess(len(rust.encode()), 512 * 1024)
        for forbidden in ["enum Value", "enum Op", "struct Runtime", "fn step("]:
            self.assertNotIn(forbidden, rust)
        type(self).serial += 1
        path = Path(self.tmp.name, f"program{self.serial}.rs")
        path.write_text(rust, encoding="utf-8")
        binary = path.with_suffix("")
        build = subprocess.run(["rustc", "--edition=2021", *(["-O"] if release else []),
                                str(path), "-o", str(binary)], capture_output=True, text=True, timeout=120)
        self.assertEqual(build.returncode, 0, build.stderr + "\n" + source)
        return binary

    def compare(self, binary, source, data=""):
        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5,
                                env={"PATH": "/python-is-unavailable", "PYTHONPATH": "/unavailable"})
        expected = subprocess.run([sys.executable, "-c", source], input=data,
                                  capture_output=True, text=True, timeout=5)
        self.assertEqual(actual.stdout, expected.stdout, source + "\n" + data)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + "\n" + expected.stderr)
        if actual.returncode:
            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                             expected.stderr.splitlines()[-1].split(":")[0])
        return actual

    def differential(self, source, inputs=("",), profiles=(True,)):
        for release in profiles:
            binary = self.compile(source, release)
            for data in inputs:
                with self.subTest(release=release, data=data):
                    self.compare(binary, source, data)

    def test_map_input_empty_unicode_invalid_and_large_values(self):
        source = "A=list(map(int,input().split()))\nprint(len(A),sum(A),sum(A,10**100))\nprint(*A)\n"
        self.differential(source, ["\n", "-1 0 7\n", f"{10**170} {-10**140}\n",
                                   "4\u001c5\u20036\n", "1 invalid 3\n", ""], (False, True))

    def test_mutations_copy_repetition_sort_and_immutable_element_reads(self):
        source = '''A=[10**100,-7,8]
old=A[0]
A[-1]=int(input())
A[0]+=3
A.append(old)
A.extend(A)
B=list(A)
C=A.copy()
D=2*A+[1]*3
A.clear()
B.sort(reverse=True)
C.sort(key=None)
D.reverse()
print(len(A),old)
print(*B)
print(*C)
print(*D)
print(*(A*0),*([-2]*-5),sep=',')
'''
        self.differential(source, ["13\n", f"{-10**120}\n"], (False, True))

    def test_readonly_functions_lists_and_nested_loops(self):
        source = '''def score(values, offset):
    answer=offset
    for value in values:
        answer+=value*value
    return answer+len(values)+sum(values)+max(values,default=0)

def first(values):
    return values[-1]
A=list(map(int,input().split()))
print(score(A,10**120),score([1,2,3],0))
if len(A):
    print(first(A))
total=0
for value in A:
    for other in [1,2]:
        total+=value*other
print(total)
print(*A)
'''
        self.differential(source, ["\n", "1 -2 3\n", f"{10**100} {-10**101}\n"])

    def test_for_break_continue_reversed_and_target_after_loop(self):
        source = '''A=[3,10**100,-4,7]
last=99
total=0
for last in reversed(A):
    if last<0:
        continue
    total+=last
    if total>10**99:
        break
print(total,last)
B=list(reversed(A))
for last in []:
    last=0
print(last)
print(*A)
print(*B)
'''
        self.differential(source, profiles=(False, True))

    def test_branches_and_loop_container_replacement(self):
        source = '''A=[]
if int(input()):
    A=[10**100]
else:
    A=[-1,2]
i=0
while i<3:
    A.append(i)
    if i==1:
        A=A+[7]
    i+=1
print(*A)
for k in range(2):
    A=[k,10**100]
print(*A)
'''
        self.differential(source, ["0\n", "1\n"], (False, True))

    def test_index_bounds_and_assignment_evaluation_order(self):
        read = "A=[10**100,7]\nprint(5)\nprint(A[int(input())],int(input()))\n"
        update = "A=[10**100,7]\nprint(5)\nA[int(input())]=int(input())\nprint(*A)\nprint(int(input()))\n"
        augment = "A=[10**100,7]\nprint(5)\nA[int(input())]+=int(input())\nprint(*A)\n"
        for source in [read, update, augment]:
            self.differential(source, ["-1\n13\n17\n", "0\n13\n17\n", "2\n13\n17\n",
                                       f"{10**100}\n13\n17\n", f"{-10**100}\n13\n17\n",
                                       "invalid\n13\n", "2\ninvalid\n"])

    def test_subscript_effects_run_before_augmented_rhs(self):
        source = '''def index():
    print(111)
    return int(input())
def value():
    print(222)
    return int(input())
A=[10**100,7]
A[index()]+=value()
print(*A)
'''
        self.differential(source, ["0\n13\n", "2\n13\n", f"{-10**100}\n13\n"])

    def test_repetition_checked_machine_count_and_allocation(self):
        source = "A=[7]*int(input())\nprint(len(A),sum(A))\n"
        empty = "A=[]*int(input())\nprint(len(A))\n"
        for program in [source, empty]:
            self.differential(program, ["0\n", "-4\n", "5\n", f"{-2**63}\n",
                                         f"{2**63}\n", f"{-2**63-1}\n", f"{10**100}\n", f"{-10**100}\n"])
        # Request exceeds Rust's representable allocation without attempting
        # a physical large allocation. CPython raises MemoryError too.
        self.differential(source, [f"{2**63-1}\n"])

    def test_list_extrema_empty_defaults_and_evaluation_order(self):
        source = '''A=list(map(int,input().split()))
print(max(A,default=int(input())),min(A,default=int(input())))
print(int(input()))
'''
        self.differential(source, ["\n4\n5\n6\n", "1 2 3\n4\n5\n6\n",
                                   f"{10**100} {-10**100}\n4\n5\n6\n"])
        self.differential("A=[]\nprint(min(A))\n")

    def test_unpacking_checks_before_binding_and_clones_elements(self):
        self.differential("A=list(map(int,input().split()))\na,b=A\nA[0]=9\nprint(a,b,*A)\n",
                          ["1 2\n", "1\n", "1 2 3\n", f"{10**150} {-10**160}\n"])

    def test_checked_range_and_input_comprehension_builders(self):
        source = '''A=[int(word) for word in input().split()]
B=list(range(10**100,10**100+4))
C=[i*i for i in range(-3,5) if i%2]
print(*A)
print(*B)
print(*C)
print(sum(A)+sum(B)+sum(C))
'''
        self.differential(source,["\n", "1 2 -3\n", "invalid\n"],(False,True))

    def test_seeded_list_reductions_and_index_updates(self):
        source = '''A=list(map(int,input().split()))
total=0
for a in A:
    total+=a*a
if len(A):
    A[-1]+=A[0]
    print(max(A),min(A))
print(total,sum(A),len(A))
A.sort()
print(*A)
'''
        rng = random.Random(918731)
        data = [" ".join(str(rng.randrange(-10**rng.randrange(1,180),10**rng.randrange(1,180)))
                         for _ in range(rng.randrange(0,25))) + "\n" for _ in range(45)]
        self.differential(source, data)

    def test_unproved_aliases_mutation_during_iteration_and_unbound_reads_reject(self):
        programs = ["A=[1]\nB=A\nB.append(2)\nprint(*A)\n",
                    "A=B=[1]\nA.append(2)\n",
                    "A=[1]\nfor a in A:\n A.append(a)\n",
                    "A=[1]\nfor a in A:\n A[0]=2\n",
                    "A=[1]\nfor a in A:\n A=[2]\n",
                    "A=[1]\nfor a in A:\n A,b=[2],3\n",
                    "def change(A):\n A.append(2)\nA=[1]\nchange(A)\n"]
        for source in programs:
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(integer="bigint", filename="unproved.py"))
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code, "E006")


if __name__ == "__main__":
    unittest.main()
