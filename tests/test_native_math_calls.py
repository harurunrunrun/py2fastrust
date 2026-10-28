"""Mathematical calls retain native widths, exact internal results and errors."""
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile


DRIVER = '''import math as arithmetic
q=int(input())
for _ in range(q):
    op,a,b,c=map(int,input().split())
    if op==0:print(arithmetic.gcd(a,b,c))
    elif op==1:print(arithmetic.lcm(a,b,c))
    elif op==2:print(arithmetic.isqrt(a))
    elif op==3:print(arithmetic.factorial(a))
    elif op==4:print(arithmetic.comb(a,b))
    elif op==5:print(arithmetic.perm(a,b))
    else:print(arithmetic.perm(a,None))
'''

REFERENCE = '''import json,sys
try:exec(compile(sys.argv[1],sys.argv[2],'exec'),{'__name__':'__main__'})
except BaseException as error:
 frames=[];trace=error.__traceback__
 while trace is not None:
  if trace.tb_frame.f_code.co_filename==sys.argv[2]:frames.append((str(trace.tb_lineno),trace.tb_frame.f_code.co_name))
  trace=trace.tb_next
 print(json.dumps({'message':type(error).__name__+': '+str(error),'frames':frames}),file=sys.stderr);sys.exit(1)
'''


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class NativeMathCallTests(unittest.TestCase):
    def build(self, source, mode, directory, *, prune=True, optimized=False):
        with patch('py2fastrust.codegen.generate', side_effect=AssertionError('VM fallback')):
            result = transpile(source, TranspileOptions(integer=mode, filename='math_calls.py',
                                                       license='NONE', optimize=prune))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, 'native')
        self.assertLess(len(result.rust_source.encode()), 512 * 1024)
        if mode != 'bigint':
            self.assertNotIn('struct Int', result.rust_source)
        rust = Path(directory) / (mode + '.rs')
        rust.write_text(result.rust_source)
        binary = rust.with_suffix('.opt' if optimized else '.debug')
        build = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []),
                                str(rust), '-o', str(binary)], capture_output=True, text=True, timeout=120)
        self.assertEqual(build.returncode, 0, build.stderr)
        return binary

    def test_float_values_retain_their_representation_in_every_integer_mode(self):
        source = 'def identity(value):return value\nx=identity(-0.0)\ny=identity(1.5)\nz=identity(1e-300)\na=identity(1e309)\nb=identity(-1e309)\nprint(x,y,z,a,b,not x,bool(y),bool(z))\n'
        cp = subprocess.run([sys.executable, '-I', '-S', '-c', source], capture_output=True, text=True, timeout=10)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        with tempfile.TemporaryDirectory(prefix='pytors-float-value-') as directory:
            for mode in ('i64', 'i128', 'bigint'):
                for optimized in (False, True):
                    binary = self.build(source, mode, directory, optimized=optimized)
                    actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (cp.returncode, cp.stdout, cp.stderr))

    def test_typed_frames_keep_float_fields_and_return_values(self):
        source = 'class Holder:\n def __init__(self,value):self.value=value\n def read(self):return self.value\nfirst=Holder(1.5)\nprint(first.read(),bool(first.read()),-first.read(),not first.read())\n'
        cp = subprocess.run([sys.executable, '-I', '-S', '-c', source], capture_output=True, text=True, timeout=10)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        with tempfile.TemporaryDirectory(prefix='pytors-float-frame-') as directory:
            for mode in ('i64', 'i128', 'bigint'):
                for optimized in (False, True):
                    binary = self.build(source, mode, directory, optimized=optimized)
                    actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (cp.returncode, cp.stdout, cp.stderr))

    def test_float_integer_conversion_uses_the_selected_integer_representation(self):
        sources = [
            'convert=int\ndef identity(value):return value\nprint(convert(identity(1.9)),int(identity(-1.9)))\n',
            'class Converter:\n def convert(self,value):return int(value)\nitem=Converter()\nprint(item.convert(1.9),item.convert(-1.9))\n',
            'class Converter:\n def convert(self,value):return int(value)\nitem=Converter()\nprint(item.convert(1e309))\n',
        ]
        for source in sources:
            cp = subprocess.run([sys.executable, '-I', '-S', '-c', REFERENCE, source, 'math_calls.py'],
                                capture_output=True, text=True, timeout=10)
            reference = json.loads(cp.stderr) if cp.returncode else None
            with tempfile.TemporaryDirectory(prefix='pytors-float-int-') as directory:
                for mode in ('i64', 'i128', 'bigint'):
                    for optimized in (False, True):
                        binary = self.build(source, mode, directory, optimized=optimized)
                        actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                        self.assertEqual((actual.returncode, actual.stdout), (cp.returncode, cp.stdout))
                        if reference:
                            self.assertEqual(actual.stderr.splitlines()[-1], reference['message'])
                            self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)', actual.stderr),
                                             [tuple(frame) for frame in reference['frames']])
                        else:
                            self.assertEqual(actual.stderr, '')

    def test_mathematical_results_wrap_without_bigint_temporaries(self):
        rng = random.Random(290610)
        for mode, bits in (('i64', 64), ('i128', 128), ('bigint', 0)):
            edge = 1 << (bits - 1) if bits else 1 << 255
            cases = [(0, -edge, 0, 0), (0, -edge, edge - 1, 0),
                     (1, 17, 19, 17), (1, 4, 4, 8), (1, -edge, 3, 7),
                     (2, edge - 1, 0, 0), (3, 60, 0, 0), (6, 100, 0, 0),
                     (4, edge - 1, 20, 0), (5, edge - 1, 20, 0)]
            for _ in range(40):
                n = rng.randrange(0, 250)
                k = rng.randrange(0, 270)
                cases += [(4, n, k, 0), (5, n, k, 0), (3, n, 0, 0)]
            expected = []
            for op, a, b, c in cases:
                result = (math.gcd(a,b,c) if op == 0 else math.lcm(a,b,c) if op == 1 else
                          math.isqrt(a) if op == 2 else math.factorial(a) if op == 3 else
                          math.comb(a,b) if op == 4 else math.perm(a,b) if op == 5 else math.perm(a,None))
                if bits:
                    result = (result + (1 << (bits - 1))) % (1 << bits) - (1 << (bits - 1))
                expected.append(str(result))
            data = str(len(cases)) + '\n' + ''.join(' '.join(map(str, row)) + '\n' for row in cases)
            with tempfile.TemporaryDirectory(prefix='pytors-native-math-') as directory:
                for optimized in (False, True):
                    binary = self.build(DRIVER, mode, directory, optimized=optimized)
                    actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=10,
                                            env={**os.environ, 'PATH': '/no-python-runtime'})
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (0, '\n'.join(expected) + '\n', ''))

    def test_math_errors_capture_arguments_before_binding_and_index_conversion(self):
        cases = [
            'import math\nprint(math.factorial(n=4))\n',
            'from math import comb\nprint(comb())\n',
            'from math import perm\nprint(perm(1,2,3))\n',
            'from math import gcd\nprint(gcd(1.0))\n',
            'from math import gcd\nprint(gcd(None))\n',
            'from math import perm\nprint(perm(-1,None))\n',
            'import math\ndef mark(value):\n print(value)\n return value\nprint(math.gcd(mark(1),other=mark(2)))\n',
            'import math\ndef mark(value):\n print(value)\n return value\nprint(math.gcd(1.5,mark(2)))\n',
            'import math\ndef mark(value):\n print(value)\n return value\nprint(math.gcd([],mark(3)))\n',
        ]
        for source in cases:
            cp = subprocess.run([sys.executable, '-I', '-S', '-c', REFERENCE, source, 'math_calls.py'],
                                capture_output=True, text=True, timeout=10)
            reference = json.loads(cp.stderr)
            with tempfile.TemporaryDirectory(prefix='pytors-math-error-') as directory:
                for mode in ('i64', 'i128', 'bigint'):
                    for optimized in (False, True):
                        with self.subTest(source=source, integer=mode, optimized=optimized):
                            binary = self.build(source, mode, directory, optimized=optimized)
                            actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                            self.assertEqual((actual.returncode, actual.stdout), (cp.returncode, cp.stdout))
                            self.assertEqual(actual.stderr.splitlines()[-1], reference['message'])
                            frames = re.findall(r'File ".*?", line (\d+), in ([^\n]+)', actual.stderr)
                            self.assertEqual(frames, [tuple(frame) for frame in reference['frames']])

    def test_disabling_pruning_preserves_native_math_types(self):
        source = 'from math import gcd,lcm,isqrt,factorial,comb,perm\nprint(gcd(-12,8),lcm(17,19,17),isqrt(99),factorial(10),comb(20,3),perm(20,3))\n'
        expected = subprocess.run([sys.executable, '-I', '-S', '-c', source], capture_output=True, text=True, timeout=10)
        with tempfile.TemporaryDirectory(prefix='pytors-math-no-prune-') as directory:
            for mode in ('i64', 'i128', 'bigint'):
                binary = self.build(source, mode, directory, prune=False)
                actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                 (expected.returncode, expected.stdout, expected.stderr))
