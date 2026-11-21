"""Typed list membership, in-place list addition and None row placeholders."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile


CASES = {
    'membership_scalars': ('''primes=[2,3,5,7]
print(5 in primes,4 in primes,4 not in primes)
print(3 in [1,2,3],"b" in ["a","b"],"z" not in ["a"])
flags=[False,False]
print(True in flags,0 in flags,True in [1,2])
def owns(value,values):
    return value in values
print(owns(7,primes),owns(8,primes),owns(1,[]))
table=[[4,5],[6]]
print(6 in table[1],4 in table[1],[6] in table,[7] in table)
''', ''),
    'membership_structured': ('''pairs=[(1,2),(3,4)]
print((3,4) in pairs,(2,1) in pairs)
blobs=[b"ab",b"c"]
print(b"c" in blobs,b"x" not in blobs)
holes=[None,1]
print(None in holes,2 in holes)
def look(pair,table):
    return pair in table
print(look((1,2),pairs),look((5,6),pairs))
''', ''),
    'float_identity_search': ('''first=float("nan")
second=float("nan")
samples=[first,2.0,first]
print(first in samples,second in samples)
print(samples.count(first),samples.count(second),samples.index(first),samples.count(2))
samples.remove(first)
print(len(samples),samples.count(first),samples.index(2.0))
''', ''),
    'membership_order_and_alias': ('''events=[]
def key():
    events.append("key")
    return 3
def box():
    events.append("box")
    return [1,3]
print(key() in box(),events)
left=[1,2]
right=left
left.append(9)
print(9 in right,10 not in right)
for limit in range(3):
    print(limit in left)
''', ''),
    'augmented_extend': ('''values=[3,1]
values+=[4,1,5]
print(values,len(values))
same=values
values+=[9]
print(same,same is values)
values+=values
print(len(same),values[-1])
joined=[]
for row in [[1],[2,3],[]]:
    joined+=row
print(joined)
words=["a"]
words+=["b","c"]
print(words)
def grow(tail):
    head=[0]
    head+=tail
    head.extend(tail)
    return head
print(grow([7,8]))
pair=[1]
pair+=(2,3)
print(pair)
''', ''),
    'none_row_placeholders': ('''n,m=map(int,input().split())
rows=[None]*n
for i in range(n-1):
    rows[i]=list(map(int,input().split()))
print(rows,rows[n-1] is None,len(rows))
pair=[None,None]
pair[1]=[m]
print(pair)
''', '3 2\n1 2\n3 4\n'),
}


def compare(test, source, stdin):
    with tempfile.TemporaryDirectory(prefix='pytors-list-membership-') as directory:
        script = Path(directory) / 'program.py'
        script.write_text(source)
        expected = subprocess.run([sys.executable, '-I', '-S', str(script)], input=stdin,
                                  capture_output=True, text=True, timeout=10)
        test.assertEqual(expected.returncode, 0, expected.stderr)
        for integer in ('i64', 'i128', 'bigint'):
            with patch('py2fastrust.codegen.generate', side_effect=AssertionError('VM fallback')):
                result = transpile(source, TranspileOptions(integer=integer, filename=str(script), license='none'))
            test.assertTrue(result.success, result.diagnostics)
            test.assertEqual(result.backend, 'native')
            test.assertLess(len(result.rust_source.encode()), 512 * 1024)
            for marker in ('enum Value', 'enum Op', 'struct Runtime', 'struct PegParser'):
                test.assertNotIn(marker, result.rust_source)
            rust = Path(directory) / (integer + '.rs')
            rust.write_text(result.rust_source)
            for optimized in (False, True):
                binary = rust.with_suffix('.opt' if optimized else '.debug')
                built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                                       capture_output=True, text=True, timeout=120)
                test.assertEqual(built.returncode, 0, built.stderr)
                actual = subprocess.run([str(binary)], input=stdin, capture_output=True, text=True, timeout=10,
                                        env={**os.environ, 'PATH': '/no-python-runtime'})
                with test.subTest(integer=integer, optimized=optimized):
                    test.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (expected.returncode, expected.stdout, expected.stderr))


class NativeListMembershipExtendTests(unittest.TestCase):
    def test_membership_scalars(self):
        compare(self, *CASES['membership_scalars'])

    def test_membership_structured(self):
        compare(self, *CASES['membership_structured'])

    def test_float_identity_search(self):
        compare(self, *CASES['float_identity_search'])

    def test_membership_order_and_alias(self):
        compare(self, *CASES['membership_order_and_alias'])

    def test_augmented_extend(self):
        compare(self, *CASES['augmented_extend'])

    def test_none_row_placeholders(self):
        compare(self, *CASES['none_row_placeholders'])

    def test_unproved_cases_are_positioned(self):
        boundaries = {
            'print(1.0 in [1,2])\n': ('list membership', ':1:7:'),
            'x=[1]\nrows=[None]*2\nrows[0]=x\nx.append(2)\nprint(rows)\n': ('alias-preserving', ':3:1:'),
        }
        for source, (reason, position) in boundaries.items():
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='boundary.py'))
                self.assertFalse(result.success)
                text = '\n'.join(map(str, result.diagnostics))
                self.assertIn(reason, text)
                self.assertIn('boundary.py' + position, text)
