"""Constant divisors preserve floor arithmetic and checked operand evaluation."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust import transpile, TranspileOptions
from tests import test_native_lexical_closures as lexical
from wrapping_reference import execute


def source(divisor):
    return ('def factory():\n'
            f' divisor={divisor!r}\n'
            ' def calculate(value):return value%divisor,value//divisor\n'
            ' return calculate\n'
            'calculate=factory()\n'
            'print(calculate(int(input())))\n')


class ConstantDivisorProofs(unittest.TestCase):
    def test_fixed_width_frame_uses_facts_without_erasing_reads(self):
        for divisor in (97, -97, 1, -1, True):
            for mode in ('i64', 'i128'):
                result = transpile(source(divisor), TranspileOptions(integer=mode, license='none'))
                self.assertTrue(result.success, result.diagnostics)
                self.assertIn('let class_checked_divisor=', result.rust_source)
                self.assertIn('class_lexical_get_', result.rust_source)
                self.assertIn('wrapping_rem(', result.rust_source)
                self.assertIn('wrapping_div(', result.rust_source)

    def test_plain_integer_expressions_use_the_same_lowering(self):
        for mode in ('i64', 'i128'):
            result = transpile('value=int(input())\nprint(value%97,value//-97)\n', TranspileOptions(integer=mode, license='none'))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.rust_source.count('let class_checked_divisor='), 2)

    def test_zero_and_unknown_divisors_keep_checked_division(self):
        for divisor in (0, False):
            result = transpile(source(divisor), TranspileOptions(license='none'))
            self.assertTrue(result.success, result.diagnostics)
            self.assertNotIn('let class_checked_divisor=', result.rust_source)
        result = transpile(source(97).replace('divisor=97', 'divisor=int(input())'), TranspileOptions(license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertNotIn('let class_checked_divisor=', result.rust_source)


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ConstantDivisorExecution(unittest.TestCase):
    compare = lexical.LexicalClosureExecutionTests.compare

    def test_negative_floor_and_remainder_in_all_integer_modes(self):
        for divisor in (97, -97, 1, -1, True):
            with self.subTest(divisor=divisor):
                self.compare(source(divisor), tuple(f'{value}\n' for value in (-100001, -98, -97, -1, 0, 1, 97, 98, 100001)))

    def test_left_operand_effect_precedes_uninitialized_divisor_error(self):
        self.compare('def outer(flag):\n'
                     ' if flag:divisor=97\n'
                     ' def effect():\n'
                     '  print("left")\n'
                     '  return -123\n'
                     ' def calculate():return effect()%divisor\n'
                     ' return calculate()\n'
                     'print(outer(int(input())))\n', ('0\n', '1\n'))

    def test_signed_minimum_and_width_normalized_divisors(self):
        inputs = tuple(f'{value}\n' for value in (-(1<<127), -(1<<63), -1, 0, (1<<127)+1))
        with tempfile.TemporaryDirectory(prefix='pytors-divisor-width-') as directory:
            for divisor in (-1, 1<<64, (1<<128)+1):
                program = source(divisor)
                for mode in ('i64','i128','bigint'):
                    references = [execute(program, mode, data) for data in inputs]
                    result = transpile(program, TranspileOptions(integer=mode, license='none'))
                    self.assertTrue(result.success, result.diagnostics)
                    rust = Path(directory)/'width.rs'
                    rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        binary = Path(directory)/'width'
                        build = subprocess.run(['rustc','--edition=2021',*(['-O'] if optimized else []),str(rust),'-o',str(binary)], capture_output=True,text=True,timeout=120)
                        self.assertEqual(build.returncode,0,build.stderr)
                        for data, expected in zip(inputs,references):
                            with self.subTest(divisor=divisor,mode=mode,optimized=optimized,data=data):
                                actual = subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python'})
                                self.assertEqual((actual.stdout,actual.returncode),(expected.stdout,expected.returncode),actual.stderr)
                                if expected.exception_type:
                                    self.assertEqual(actual.stderr.splitlines()[-1].split(':')[0],expected.exception_type)
                                else:
                                    self.assertEqual(actual.stderr,'')


if __name__ == '__main__':
    unittest.main()
