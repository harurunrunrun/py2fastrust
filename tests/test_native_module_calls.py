"""Standard callables use resolved identity, typed arguments and checked bounds."""
import random
import shutil
import tempfile
from pathlib import Path
import unittest

import test_native_slices as _slices
from py2fastrust import TranspileOptions,transpile


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeModuleCallTests(unittest.TestCase):
    def compare(self,source,inputs=("",),modes=("i64","i128","bigint")):
        return _slices.NativeSliceTests.compare(self,source,inputs,modes=modes)

    def test_gcd_lcm_variadic_aliases_and_random_inputs(self):
        source='''import math as m
from math import gcd as common
old=m.gcd
m=7
print(common(),old(),common(-18,30),old(True,False))
import math
n=int(input())
for _ in range(n):
    a,b,c=map(int,input().split())
    print(math.gcd(a,b,c),math.lcm(a,b,c),math.lcm())
'''
        rng=random.Random(7311)
        triples=[(0,0,0),(-6,12,18),(1,0,3)]+[tuple(rng.randrange(-1000,1000)for _ in range(3))for _ in range(100)]
        self.compare(source,[str(len(triples))+"\n"+"".join(f"{a} {b} {c}\n"for a,b,c in triples)])

    def test_integer_algorithms_and_boundary_failures(self):
        source='''from math import isqrt,factorial,comb,perm
n,k=map(int,input().split())
print(isqrt(n),factorial(n),comb(n,k),perm(n,k),perm(n,None))
'''
        self.compare(source,["0 0\n","1 2\n","12 4\n","-1 2\n","5 -1\n"])
        self.compare(source,["100 7\n","500 2\n"],modes=("bigint",))
        large='''import math
n=int(input())
print(math.isqrt(n),math.comb(n,2),math.perm(n,2))
'''
        self.compare(large,[f"{10**200}\n",f"{2**1024-1}\n"],modes=("bigint",))

    def test_call_order_local_imports_and_captured_globals(self):
        source='''from math import comb as choose
def value(tag):
    print(tag)
    return int(input())
def root(n):
    import math as m
    from math import isqrt as square_root
    return square_root(n)+m.gcd(n,12)
print(choose(value(1),value(2)))
print(root(144))
'''
        self.compare(source,["5\n2\n","-1\n2\n","5\n-1\n","5\ninvalid\n"])

    def test_bisect_aliases_duplicates_and_structural_bounds(self):
        source='''import bisect as b
from bisect import bisect_left as left
right=b.bisect_right
a=[-7,-1,0,2,2,9]
x,lo,hi=map(int,input().split())
print(left(a,x,lo,hi),right(a,x,lo=lo,hi=hi,key=None),b.bisect(a,x,lo,hi))
print(*a)
'''
        self.compare(source,[f"{x} {lo} {hi}\n"for x in [-8,0,2,99]
                             for lo,hi in [(0,6),(0,-1),(0,-2),(1,5),(5,1),(100,0),(-1,6),(0,100)]])
        large='''from bisect import bisect_left
a=[1,2,3]
print(bisect_left(a,2,int(input()),int(input())))
'''
        self.compare(large,[f"0\n{2**63}\n",f"{2**63}\n-1\n",f"-1\n{2**63}\n"],modes=("i128","bigint"))

    def test_insort_mutation_and_readonly_search_specializations(self):
        source='''import bisect
def lower(a,x):
    return bisect.bisect_left(a,x)
a=[1,2,2,7]
bisect.insort_left(a,2)
bisect.insort_right(a,-1,0,None,key=None)
bisect.insort(a,9,100,0)
print(*a)
print(lower(a,2),lower([],5))
'''
        self.compare(source)

    def test_module_shadowing_and_unproved_writes_are_not_substituted(self):
        with tempfile.TemporaryDirectory(prefix="pytors-native-module-")as directory:
            root=Path(directory)
            (root/"math.py").write_text("def isqrt(n):return 123\n")
            result=transpile("import math\nprint(math.isqrt(9))\n",TranspileOptions(module_paths=(root,)))
            self.assertFalse(result.success)
        for source in ["import math\nmath.gcd=lambda a,b:7\nprint(math.gcd(1,2))\n",
                       "import bisect\ndef insert(a):bisect.insort(a,3)\na=[1,4]\ninsert(a)\nprint(*a)\n",
                       "import math\nprint(math.factorial(n=4))\n"]:
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
