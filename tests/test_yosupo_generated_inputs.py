"""Offline, bounded Library Checker inputs compared with CPython first."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


CONVOLUTION = '''from atcoder.convolution import convolution
n, m = map(int, input().split())
a = list(map(int, input().split()))
b = list(map(int, input().split()))
print(" ".join(map(str, convolution(998244353, a, b))))
'''

AFFINE = '''from atcoder.lazysegtree import LazySegTree
from atcoder.modint import ModContext, Modint

def op(left, right):
    return (left[0] + right[0], left[1] + right[1])

def mapping(action, value):
    return (action[0] * value[0] + action[1] * value[1], value[1])

def composition(new, old):
    return (new[0] * old[0], new[0] * old[1] + new[1])

with ModContext(998244353):
    n, q = map(int, input().split())
    initial = [(Modint(value), 1) for value in map(int, input().split())]
    tree = LazySegTree(op, (Modint(0), 0), mapping, composition,
                      (Modint(1), Modint(0)), initial)
    answers = []
    for _ in range(q):
        query = list(map(int, input().split()))
        if query[0] == 0:
            _, left, right, b, c = query
            tree.apply(left, right, (Modint(b), Modint(c)))
        else:
            _, left, right = query
            answers.append(str(tree.prod(left, right)[0].val()))
    print("\\n".join(answers))
'''


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class YosupoGeneratedInputTests(unittest.TestCase):
    def exercise(self, problem, source):
        root=Path(__file__).resolve().parents[1]
        fixture=json.loads((root/'tests/fixtures/yosupo_generated.json').read_text())
        cases=[case for case in fixture['cases'] if case['problem']==problem]
        self.assertTrue(cases)
        vendor=root/'py2fastrust/vendor/ac_library_python'
        with tempfile.TemporaryDirectory(prefix='pytors-yosupo-') as temporary:
            folder=Path(temporary);main=folder/'main.py';main.write_text(source)
            references=[]
            for case in cases:
                reference=subprocess.run([sys.executable,'-B',str(main)],input=case['input'],
                    capture_output=True,text=True,timeout=15,
                    env={**os.environ,'PYTHONPATH':str(vendor)})
                self.assertEqual((reference.returncode,reference.stderr),(0,''))
                self.assertEqual(reference.stdout.split(),case['expected'].split())
                references.append(reference.stdout)
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(filename=str(main),integer=integer,license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                rust=folder/(integer+'.rs');rust.write_text(result.rust_source)
                binary=folder/integer
                build=subprocess.run(['rustc','--edition=2021','--crate-name','yosupo_regression',
                    '-O',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                self.assertEqual(build.returncode,0,build.stderr)
                for case,expected in zip(cases,references):
                    with self.subTest(integer=integer,case=case['name']):
                        actual=subprocess.run([str(binary)],input=case['input'],capture_output=True,
                            text=True,timeout=15,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
                        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected,''))

    def test_modular_convolution(self):
        self.exercise('convolution_mod',CONVOLUTION)

    def test_range_affine_range_sum_with_source_modint(self):
        self.exercise('range_affine_range_sum',AFFINE)


if __name__=='__main__':
    unittest.main()
