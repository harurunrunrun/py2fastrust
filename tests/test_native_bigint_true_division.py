import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'boolean_zero_denominator': 'print(1/False)\n',
 'huge_cancellation': 'print((10**400)/(10**400),(2**2000+2**100)/(2**1999+1))\n',
 'largest_finite': 'print((2**1024-2**971)/1)\n',
 'normal_rounding': 'print((2**53+1)/(2**53),(2**53+3)/(2**53),((2**100)+2**47)/(2**100))\n',
 'operator_callback': 'from functools import reduce\n'
                      'from operator import truediv\n'
                      'print(reduce(truediv,[12,3]),truediv(7,2))\n',
 'overflow': 'print((2**1024)/1)\n',
 'overflow_rounding_boundary': 'print((2**1024-2**970)/1)\n',
 'small_signed_and_boolean': 'print(7/2,-7/2,7/-2,True/2,False/-2,0/-2)\n',
 'subnormal_and_halfway_rounding': 'print(1/(2**1074),1/(2**1075),3/(2**1075),-1/(2**1075))\n',
 'underflow_sign': 'print(1/(10**400),-1/(10**400),0/(-(10**400)))\n',
 'zero_denominator': 'print((10**400)/0)\n'}

class BigIntDivisionTests(unittest.TestCase):
    def check(self,name):
        source=CASES[name];filename='iterator_case.py'
        cp=subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,filename],capture_output=True,text=True,timeout=10)
        failure=json.loads(cp.stderr)if cp.returncode else None
        with tempfile.TemporaryDirectory(prefix='pytors-bigint-ratio-')as directory:
            with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
                result=transpile(source,TranspileOptions(integer='bigint',filename=filename,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            self.assertLess(len(result.rust_source.encode()),512*1024)
            rust=Path(directory,'program.rs');rust.write_text(result.rust_source)
            for optimized in (False,True):
                binary=rust.with_suffix('.opt'if optimized else'.debug')
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
                if failure:
                    self.assertEqual(actual.stderr.splitlines()[-1],failure['message'])
                    self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in failure['frames']])
                else:self.assertEqual(actual.stderr,'')

    def test_small_signed_and_boolean(self):self.check('small_signed_and_boolean')

    def test_huge_cancellation(self):self.check('huge_cancellation')

    def test_subnormal_and_halfway_rounding(self):self.check('subnormal_and_halfway_rounding')

    def test_underflow_sign(self):self.check('underflow_sign')

    def test_normal_rounding(self):self.check('normal_rounding')

    def test_largest_finite(self):self.check('largest_finite')

    def test_overflow(self):self.check('overflow')

    def test_overflow_rounding_boundary(self):self.check('overflow_rounding_boundary')

    def test_zero_denominator(self):self.check('zero_denominator')

    def test_boolean_zero_denominator(self):self.check('boolean_zero_denominator')

    def test_operator_callback(self):self.check('operator_callback')
