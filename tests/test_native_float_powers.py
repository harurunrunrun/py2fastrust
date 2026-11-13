"""Floating powers use finite native real/complex alternatives."""
import shutil
import random
import subprocess
import sys
import unittest

from py2fastrust import TranspileOptions, transpile
import test_native_stdio as stdio_tests


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class NativeFloatPowerTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential
    def test_dynamic_power_observers_and_ieee_boundaries(self):
        source = '''a=float(input())
b=float(input())
z=a**b
print(z,repr(z),str(z),bool(z),f"{z}")
'''
        pairs = [('4', '.5'), ('-4', '.5'), ('-2', '.5'), ('-1e-300', '1.5'),
                 ('-5e-324', '.5'), ('-0', '.5'), ('-0', '3'), ('-0', '-3'),
                 ('inf', '-2'), ('-inf', '.5'), ('-inf', '-.5'), ('-inf', '3'),
                 ('-inf', '-3'), ('nan', '0'), ('nan', '2'), ('1', 'nan'),
                 ('-1', 'nan'), ('-1', 'inf'), ('0', '-inf'), ('0', 'inf'),
                 ('2', 'inf'), ('.5', '-inf'), ('-2', '3'), ('-2', '2'),
                 ('1e308', '2'), ('-1e308', '2.5'), ('-1e-300', '-2.5'),
                 ('-1e-300', '2.5'), ('2', '-.5'), ('-1', '4503599627370495.5')]
        self.differential(source, [(a+'\n'+b+'\n').encode() for a,b in pairs], profiles=(False, True))

    def test_pow_alias_keyword_binding_and_real_literal_proof(self):
        source = '''power=pow
x=float(input())
a=power(base=x,exp=2.0)
b=power(x,exp=0.5,mod=None)
print(a+1,b,repr(b),bool(b))
'''
        self.differential(source, [b'4\n',b'-4\n',b'-0\n',b'nan\n',b'inf\n'], profiles=(False, True))

    def test_power_argument_and_callback_evaluation_order(self):
        source = '''def number(name):
    print(name)
    return float(input())
print(pow(exp=number('exponent'),base=number('base'),mod=None))
print(number('left')**number('right'))
'''
        self.differential(source, [b'.5\n-4\n-2\n.5\n',b'-1\n0\n4\n2\n'], profiles=(False, True))

    def test_int_and_float_complex_conversion_errors(self):
        for conversion in ('int', 'float'):
            source = 'x=float(input())\ny=x**0.5\nprint(y)\nprint('+conversion+'(y))\n'
            self.differential(source, [b'4\n',b'-4\n',b'nan\n',b'inf\n'], profiles=(False, True))

    def test_augmented_assignment_and_nested_carrier(self):
        source = '''x=float(input())
x**=0.5
z=[x,pow(-4,.5)]
print(z,(x,),str(z),bool(x))
if x:
    print('nonzero')
else:
    print('zero')
'''
        self.differential(source, [b'4\n',b'-4\n',b'0\n'], profiles=(False, True))

    def test_fixed_width_wrapped_literal_keeps_complex_result(self):
        for mode,bits in [('i64',64),('i128',128)]:
            magnitude=1<<(bits-1)
            source=f'z={magnitude}**0.5\nprint(z,repr(z),bool(z))\n'
            reference=f'z=({-magnitude})**0.5\nprint(z,repr(z),bool(z))\n'
            expected=subprocess.run([sys.executable,'-c',reference],capture_output=True,timeout=5)
            for release in (False,True):
                binary=self.compile(source,mode,release)
                actual=subprocess.run([str(binary)],capture_output=True,timeout=5)
                self.assertEqual(actual.stdout,expected.stdout,(mode,actual.stderr))
                self.assertEqual(actual.returncode,expected.returncode)

    def test_big_integer_conversion_occurs_after_both_arguments(self):
        source = '''def exponent():
    print('evaluated exponent')
    return 0.0
print((10**400)**exponent())
'''
        self.differential(source,modes=('bigint',),profiles=(False,True))

    def test_fresh_random_signed_bases_and_fractional_exponents(self):
        source = """count=int(input())
for _ in range(count):
    a=float(input())
    b=float(input())
    result=pow(a,b)
    print(result,bool(result))
"""
        rng=random.Random(73119)
        pairs=[(rng.uniform(-100,100),rng.uniform(-5,5)) for _ in range(160)]
        pairs += [(rng.choice([-1.0,1.0])*10**rng.uniform(-120,120),rng.uniform(-2,2))
                  for _ in range(80)]
        data=(str(len(pairs))+'\n'+''.join(repr(a)+'\n'+repr(b)+'\n' for a,b in pairs)).encode()
        self.differential(source,[data],profiles=(False,True))

    def test_proven_real_operands_remain_usable_by_scalar_arithmetic(self):
        source = """count=int(input())
for _ in range(count):
    x=float(input())
    print(x**2.0+pow(9.0,x),pow(base=16,exp=x)+1)
"""
        self.differential(source,[b'4\n-2.5\n0\n0.5\n3\n'],profiles=(False,True))

    def test_unsupported_complex_observer_is_positioned(self):
        cases=[('z+1','complex arithmetic'),('z==0','complex comparison'),('format(z,".2f")','complex')]
        for observer,reason in cases:
            result=transpile('x=float(input())\nz=x**0.5\nprint('+observer+')\n',
                             TranspileOptions(filename='complex_observer.py'))
            self.assertFalse(result.success)
            diagnostic='\n'.join(map(str,result.diagnostics))
            self.assertIn('complex_observer.py:3:',diagnostic)
            self.assertIn(reason,diagnostic)
            self.assertIn('E006',diagnostic)

