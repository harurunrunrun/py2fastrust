"""Direct sequence slicing: Python bounds, evaluation order and ownership."""
from pathlib import Path
import itertools
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeSliceTests(unittest.TestCase):
    def compare(self, source, inputs=("",), modes=("i64", "i128", "bigint"), profiles=(False, True)):
        with tempfile.TemporaryDirectory(prefix="pytors-native-slice-") as directory:
            root = Path(directory)
            for mode, release in itertools.product(modes, profiles):
                with self.subTest(integer=mode, release=release):
                    result = transpile(source, TranspileOptions(integer=mode, filename="slices.py"))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    self.assertLess(len(result.rust_source.encode()), 512 * 1024)
                    for marker in ("enum Value", "struct Runtime", "enum Op", "fn step("):
                        self.assertNotIn(marker, result.rust_source)
                    path = root / "main.rs"
                    path.write_text(result.rust_source)
                    binary = root / "main"
                    build = subprocess.run(["rustc", "--edition=2021", *(["-O"] if release else []),
                                            str(path), "-o", str(binary)], capture_output=True, text=True, timeout=90)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    for data in inputs:
                        expected = subprocess.run([sys.executable, "-c", source], input=data, text=True,
                                                  capture_output=True, timeout=5)
                        actual = subprocess.run([str(binary)], input=data, text=True, capture_output=True,
                                                timeout=5, env={"PATH": "/unavailable", "PYTHONPATH": "/unavailable"})
                        self.assertEqual((actual.returncode, actual.stdout), (expected.returncode, expected.stdout),
                                         actual.stderr + expected.stderr + "\n" + data)
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                             expected.stderr.splitlines()[-1].split(":")[0])

    def test_random_bounds_and_steps(self):
        rng = random.Random(7751)
        limits = [-2**63, -100, -8, -1, 0, 1, 8, 100, 2**63 - 1]
        cases = [(a, b, c) for a, b, c in itertools.product(limits, limits, [-9, -1, 1, 9])]
        cases += [(rng.randrange(-40, 40), rng.randrange(-40, 40), rng.choice([-17, -3, -1, 1, 3, 17]))
                  for _ in range(400)]
        source = '''a=[2,3,5,7,11,13,17]
n=int(input())
for _ in range(n):
    lo,hi,step=map(int,input().split())
    print(*a[lo:hi:step])
'''
        data = str(len(cases)) + "\n" + "".join(f"{a} {b} {c}\n" for a,b,c in cases)
        self.compare(source, [data])

    def test_defaults_none_reverse_and_independent_copies(self):
        source = '''a=[2,3,5,7]
b=a[:]
c=a[::-1]
d=a[None:None:None]
b[0]=99
c.append(11)
print(*a)
print(*b)
print(*c)
print(*d)
print(*a[:-1:-1])
print(*a[::True])
print(*[][::-(2**63)])
'''
        self.compare(source)

    def test_unicode_ascii_empty_and_character_bounds(self):
        source = '''s=input()
n=int(input())
for _ in range(n):
    lo,hi,step=map(int,input().split())
    print(s[lo:hi:step])
print(s[:],s[::-1],s[:-1:-1],sep="|")
'''
        bounds = "8\n-100 100 1\n-100 100 2\n100 -100 -1\n3 0 -1\n0 100 9\n100 0 -100\n0 0 1\n-1 -8 -2\n"
        self.compare(source, [text + "\n" + bounds for text in ["", "abcdef", "猫🐈é海", "a\x00b"]],
                     modes=("i64", "i128"))

    def test_argument_effects_and_step_zero(self):
        source = '''def bound(x):
    print(x)
    return int(input())
a=[2,3,5]
print(*a[bound(1):bound(2):bound(3)])
print(99)
'''
        self.compare(source, ["0\n3\n1\n", "0\n3\n0\n", "0\ninvalid\n1\n"])

    def test_huge_bounds_are_structural_not_wrapping(self):
        source = '''a=[2,3,5,7]
n=int(input())
print(*a[-n:n:1])
print(*a[n:-n:-1])
print(*a[::n])
print(*a[::-n])
'''
        self.compare(source, [f"{2**127-1}\n", f"{2**127-2}\n"], modes=("i128", "bigint"))
        self.compare(source, [f"{10**200}\n"], modes=("bigint",))

    def test_slices_inside_readonly_specializations(self):
        source = '''def total(a,k):
    return sum(a[::k])
a=[1,2,3,4,5]
print(total(a,2),total(a,-1),total([],1))
print(*a)
'''
        self.compare(source)

    def test_sorted_copies_input_and_evaluates_keyword_once(self):
        source = '''def direction():
    print(17)
    return int(input())
a=[3,-1,3,2]
b=sorted(a,reverse=direction(),key=None)
b[0]=8
print(*a)
print(*b)
print(*sorted([4,1,2]))
print(*sorted([],reverse=True))
'''
        self.compare(source, ["0\n", "1\n", "-1\n"])

    def test_unsupported_shallow_matrix_or_custom_key_stays_diagnostic(self):
        for source in ("a=[[1],[2]]\nb=a[:]\nb[0].append(3)\nprint(a)\n",
                       "a=[2,1]\nprint(sorted(a,key=abs))\n",
                       "sorted=3\na=[2,1]\nprint(sorted(a))\n"):
            for mode in ("i64", "i128", "bigint"):
                result = transpile(source, TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")


if __name__ == "__main__":
    unittest.main()
