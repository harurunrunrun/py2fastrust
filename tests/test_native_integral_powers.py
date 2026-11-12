"""Dynamic integer powers preserve result types, wrapping and call errors."""
import random
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_unpack_exact_lengths as harness


class IntegralPowerSelection(unittest.TestCase):
    def test_nonnegative_literal_powers_keep_the_existing_integer_path(self):
        for mode in ('i64','i128','bigint'):
            result=transpile('print(3**7)\n',TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('.powf(',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IntegralPowerExecution(unittest.TestCase):
    setUpClass=classmethod(harness.ExactUnpackLengthTests.setUpClass.__func__)
    tearDownClass=classmethod(harness.ExactUnpackLengthTests.tearDownClass.__func__)
    compile=harness.ExactUnpackLengthTests.compile
    def check(self,source,inputs):
        for mode in ('i64','i128','bigint'):
            for optimized in (False,True):
                compiled=self.compile(source,mode,release=optimized)
                for data in inputs:
                    expected=subprocess.run([sys.executable,'-I','-c',source],input=data,text=True,capture_output=True,timeout=10)
                    actual=subprocess.run([str(compiled[1])],input=data,text=True,capture_output=True,timeout=10)
                    with self.subTest(integer=mode,optimized=optimized,stdin=data):
                        self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                        ending=lambda text:text.rstrip().splitlines()[-1:]if text else[]
                        self.assertEqual(ending(actual.stderr),ending(expected.stderr))

    def test_dynamic_exponent_sign_on_plain_and_frame_paths(self):
        pairs=[(0,-1),(0,0),(0,2),(-2,-3),(-1,-(2**53+1)),(2,-1075),(-2,-1075),(7,-200)]
        rng=random.Random(20261112)
        pairs.extend((rng.randrange(-9,10),rng.randrange(-16,16))for _ in range(32))
        inputs=[f'{a} {b}\n'for a,b in pairs]
        for prefix in ('','class Marker:pass\n'):
            self.check(prefix+'a,b=map(int,input().split())\nprint(a**b)\n',inputs)

    def test_augmented_power_retypes_a_local_before_later_arithmetic(self):
        for prefix in ('','class Marker:pass\n'):
            self.check(prefix+'a,b=map(int,input().split())\na**=b\nprint(a)\na+=1\nprint(a)\n',
                ['2 -3\n','2 5\n','-2 -3\n','0 -1\n','0 0\n'])

    def test_binary64_base_and_integral_exponent_keep_errors_and_zero_sign(self):
        values=[('2.5',3),('0.0',-1),('-0.0',-3),('-0.0',3),('1e308',2),('-1e308',3),
                ('inf',-1),('-inf',-3),('nan',0),('nan',3),('-1e-300',3),('-1.0',-(2**53+1))]
        inputs=[f'{base}\n{exponent}\n'for base,exponent in values]
        for prefix in ('','class Marker:pass\n'):
            self.check(prefix+'a=float(input())\nb=int(input())\nprint(a**b)\n',inputs)
            self.check(prefix+'saved=pow\na=float(input())\nb=int(input())\nprint(saved(a,b,mod=None))\n',inputs)

    def test_frame_list_update_evaluates_its_index_once(self):
        self.check('''class Box:
 def __init__(self):self.values=[2]
 def index(self):
  print('index',end='|')
  return 0
 def update(self,exponent):self.values[self.index()]**=exponent
box=Box()
box.update(int(input()))
print(box.values)
''',['-3\n','0\n','5\n'])

    def test_pow_alias_and_explicit_none_keep_argument_evaluation_order(self):
        source='''class Marker:pass
n=int(input())
def base():
 print('base',end='|')
 return -2
def exponent():
 print('exp',end='|')
 return n
def modulus():
 print('mod',end='|')
 return None
saved=pow
print(saved(base(),exponent(),mod=modulus()))
'''
        self.check(source,['-3\n','0\n','4\n'])

    def test_boolean_base_has_integer_and_float_power_results(self):
        self.check('''class Marker:pass
n=int(input())
def power(flag,exponent):return flag**exponent
print(power(True,n))
print(power(False,n))
''',['-2\n','0\n','1\n'])

    def test_integer_math_consumes_dynamic_power_alternatives(self):
        for prefix in ('','class Marker:pass\n'):
            self.check(prefix+'''from math import isqrt
exponent=int(input())
power=2**exponent
print(power>1)
print(isqrt(64//power))
''',['-2\n','0\n','1\n','3\n'])

    def test_imported_pow_alias_has_dynamic_result_types(self):
        self.check('from builtins import pow as power\nexponent=int(input())\nprint(power(2,exponent))\n',
            ['-3\n','0\n','5\n'])

    def test_range_checks_types_after_all_argument_expressions(self):
        for prefix in ('','class Marker:pass\n'):
            self.check(prefix+'''n=int(input())
def stop():
 print('stop',end='|')
 return 4
for value in range(3**n,stop()):
 print(value)
''',['-1\n','0\n','1\n'])
            self.check(prefix+'''n=int(input())
def stop():
 print('stop',end='|')
 return 4
for value in range(0**n,stop()):
 print(value)
''',['-1\n','0\n'])

    def test_wrapping_and_float_conversion_boundaries(self):
        source='a,b=map(int,input().split())\nprint(a**b)\n'
        pairs=[(1<<70,3),((1<<64)-1,2),(-(1<<127),-1),(1<<1025,-1),
            (0,-(1<<1025)),(1,-(1<<1025)),(-1,1<<80)]
        for mode in ('i64','i128','bigint'):
            bits={'i64':64,'i128':128,'bigint':0}[mode]
            def normalized(value):
                if not bits:return value
                value%=1<<bits
                return value-(1<<bits)if value>=1<<(bits-1)else value
            for optimized in (False,True):
                compiled=self.compile(source,mode,release=optimized)
                for base,exponent in pairs:
                    a,b=normalized(base),normalized(exponent)
                    try:
                        value=normalized(pow(a,b,1<<bits))if bits and b>=0 else pow(a,b)
                        stdout=str(value)+'\n';error=None
                    except Exception as exception:
                        stdout='';error=type(exception).__name__+': '+str(exception)
                    actual=subprocess.run([str(compiled[1])],input=f'{base} {exponent}\n',text=True,capture_output=True,timeout=10)
                    with self.subTest(integer=mode,optimized=optimized,base=base,exponent=exponent):
                        self.assertEqual(actual.stdout,stdout)
                        self.assertEqual(actual.returncode,1 if error else 0)
                        self.assertEqual(actual.stderr.rstrip().splitlines()[-1:]if error else actual.stderr,
                            [error]if error else'')


if __name__=='__main__':
    unittest.main()
