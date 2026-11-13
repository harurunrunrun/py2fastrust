"""Complex powers preserve typed builtin dispatch, IEEE cases and errors."""
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_constraints import Solver
from py2fastrust.native_complex_powers import dispatch
import test_native_integer_digit_limits as digits

CASES = {'complex_exponent': ('z=(-4.0)**0.5\nprint(2**z,pow(2,z),pow(base=2,exp=z,mod=None))\n', ('',)),
 'complex_base_integer_exponents': ('z=(-9.0)**0.5\n'
                                    'for n in [-100,-7,-2,-1,0,1,2,3,8,100,101]:\n'
                                    ' print(pow(z,n))\n',
                                    ('',)),
 'complex_base_fractional': ('z=(-9.0)**0.5\nfor n in [-2.5,-0.5,0.5,1.5,4.5]:\n print(z**n)\n',
                             ('',)),
 'both_complex': ('z=(-4.0)**0.5\nw=(-9.0)**0.5\nprint(z**w,pow(w,z))\n', ('',)),
 'finite_real_complex_input': ('x=float(input())\nz=x**0.5\nprint(pow(2,z),pow(z,2))\n',
                               ('9\n', '-9\n', '0\n', '-0\n', 'inf\n', 'nan\n')),
 'zero_complex_zero': ('z=(-1.0)**0.5\nzero=z-z\nprint(zero**zero,pow(0,zero),pow(zero,2))\n',
                       ('',)),
 'zero_complex_negative': ('z=(-1.0)**0.5\nprint((z-z)**-1)\n', ('',)),
 'zero_complex_imaginary': ('z=(-1.0)**0.5\nprint(0**z)\n', ('',)),
 'complex_integer_overflow': ('z=(-1.0)**0.5+1e308\nprint(z**2)\n', ('',)),
 'complex_reciprocal_underflow': ('z=(-1.0)**0.5+1e308\nprint(z**-2)\n', ('',)),
 'nonfinite_complex_components': ('z=(-1.0)**0.5+float(input())\nprint(z**float(input()))\n',
                                  ('inf\n0\n',
                                   'inf\n1\n',
                                   'inf\n-1\n',
                                   'inf\n0.5\n',
                                   'nan\n0\n',
                                   'nan\n2\n',
                                   'nan\n0.5\n')),
 'complex_infinite_exponent': ('z=(-4.0)**0.5\nprint(z**float(input()))\n',
                               ('inf\n', '-inf\n', 'nan\n')),
 'mod_complex_base': ('z=(-1.0)**0.5\nprint(pow(z,2,7))\n', ('',)),
 'mod_complex_exponent': ('z=(-1.0)**0.5\nprint(pow(2,z,7))\n', ('',)),
 'mod_float_base_complex_exponent': ('z=(-1.0)**0.5\nprint(pow(2.0,z,7))\n', ('',)),
 'mod_complex_base_float_exponent': ('z=(-1.0)**0.5\nprint(pow(z,2.0,7))\n', ('',)),
 'invalid_base_type': ('z=(-1.0)**0.5\nprint(pow("text",z))\n', ('',)),
 'invalid_exponent_type': ('z=(-1.0)**0.5\nprint(pow(z,"text",7))\n', ('',)),
 'operand_effect_order': ('def mark(label,value):\n'
                          ' print(label)\n'
                          ' return value\n'
                          'z=(-1.0)**0.5\n'
                          'print(pow(exp=mark("exp",z),base=mark("base",2),mod=mark("mod",None)))\n',
                          ('',)),
 'wrong_binding_effects': ('def mark(label,value):\n'
                           ' print(label)\n'
                           ' return value\n'
                           'z=(-1.0)**0.5\n'
                           'print(pow(mark("base",z),mark("exp",2),base=mark("keyword",3)))\n',
                           ('',)),
 'bigint_conversion_after_operands': ('def first():\n'
                                      ' print("first")\n'
                                      ' return 1<<10000\n'
                                      'def second():\n'
                                      ' print("second")\n'
                                      ' return (-1.0)**0.5\n'
                                      'print(first()**second())\n',
                                      ('',)),
 'bigint_conversion_before_complex_modulo': ('z=(-1.0)**0.5\nprint(pow(z,1<<10000,7))\n', ('',)),
 'alias_callee_capture': ('power=pow\n'
                          'def change():\n'
                          ' global power\n'
                          ' power=print\n'
                          ' print("change")\n'
                          ' return (-1.0)**0.5\n'
                          'print(power(2,change()))\n'
                          'power("after")\n',
                          ('',)),
 'augmented_complex_power': ('z=(-4.0)**0.5\nz**=2\nprint(z)\n', ('',)),
 'recursive_numeric_union': ('def power(value,n):\n'
                             ' if n==0:return value\n'
                             ' return power(pow(value,0.5),n-1)\n'
                             'print(pow(2,power(-4,2)))\n',
                             ('',)),
 'complex_ordering_error': ('z=(-1.0)**0.5\nprint("before")\nprint(z>=0)\n', ('',)),
 'complex_min_error': ('z=(-1.0)**0.5\nprint(min(z,4))\n', ('',)),
 'ternary_slot_0': ('z=(-1.0)**0.5\nprint(pow(2,3,1.5))\n', ('',)),
 'ternary_slot_1': ('z=(-1.0)**0.5\nprint(pow(2,3,z))\n', ('',)),
 'ternary_slot_2': ('z=(-1.0)**0.5\nprint(pow(2,3,"x"))\n', ('',)),
 'ternary_slot_3': ('z=(-1.0)**0.5\nprint(pow("x",z,2.0))\n', ('',)),
 'ternary_slot_4': ('z=(-1.0)**0.5\nprint(pow(z,"x",2.0))\n', ('',)),
 'ternary_slot_5': ('z=(-1.0)**0.5\nprint(pow(None,z,2.0))\n', ('',)),
 'ternary_slot_6': ('z=(-1.0)**0.5\nprint(pow(z,None,2.0))\n', ('',)),
 'ternary_slot_7': ('z=(-1.0)**0.5\nprint(pow("x",2.0,3))\n', ('',)),
 'ternary_slot_8': ('z=(-1.0)**0.5\nprint(pow(2.0,"x",3))\n', ('',)),
 'ternary_slot_9': ('z=(-1.0)**0.5\nprint(pow(z,2,0.0))\n', ('',)),
 'ternary_slot_10': ('z=(-1.0)**0.5\nprint(pow(2,z,0.0))\n', ('',)),
 'ternary_slot_11': ('z=(-1.0)**0.5\nprint(pow(False,z,False))\n', ('',)),
 'ternary_slot_12': ('z=(-1.0)**0.5\nprint(pow(z,False,False))\n', ('',)),
 'ternary_slot_13': ('z=(-1.0)**0.5\nprint(pow(z,z,z))\n', ('',)),
 'ternary_slot_14': ('z=(-1.0)**0.5\nprint(pow(2,3,None))\n', ('',))}

BOUNDARIES = {'complex_literal_boundary': 'print(pow(2,1j))\n',
 'complex_constructor_boundary': 'print(pow(2,complex(0,1)))\n'}

CASES['mixed_additive_existing'] = ('z=(-1.0)**0.5\nzero=z-z\nreal=zero+1.0\nnegative=0.0-real\nprint(negative,real+0.0,0.0+real)\n', ('',))

CASES['mixed_additive_then_power'] = ('z=(-1.0)**0.5\nzero=z-z\nreal=zero+1.0\nnegative=0.0-real\nprint(negative**0.5)\n', ('',))

CASES['power_zero_then_mixed'] = ('z=(-1.0)**0.5\nvalue=z**0\nnegative=0.0-value\nprint(negative,negative+0.0,0.0+negative,negative-0.0,0.0-negative)\nprint(negative**0.5)\n', ('',))


# The original unsupported literal input is now an executable contract.
CASES['original_complex_literal_input'] = (BOUNDARIES.pop('complex_literal_boundary'), ('',))


class ComplexPowerExecutionTests(unittest.TestCase):
    compare = digits.IntegerDigitLimitExecutionTests.compare


def _case(name):
    def test(self):
        source, inputs = CASES[name]
        self.compare(source, inputs, ('i64', 'i128', 'bigint'), 'ascii')
    return test


for _name in CASES:
    setattr(ComplexPowerExecutionTests, 'test_' + _name, _case(_name))


class ComplexPowerProofTests(unittest.TestCase):
    def test_graph_records_numeric_complex_power(self):
        self.assertEqual(Solver.computed('binary:Pow', ('int', 'complex')), 'complex')
        self.assertEqual(Solver.computed('binary:Pow', ('complex', 'float')), 'complex')

    def test_actual_builtin_slot_priority(self):
        self.assertEqual(dispatch(('float', 'complex', 'int')), 'float_mod')
        self.assertEqual(dispatch(('complex', 'float', 'int')), 'complex')
        self.assertEqual(dispatch(('int', 'int', 'complex')), 'complex')
        self.assertEqual(dispatch(('complex', 'str', 'float')), 'float_mod')
        self.assertIsNone(dispatch(('str', 'complex', 'int')))

    def test_unrepresented_complex_creation_is_positioned(self):
        for source in BOUNDARIES.values():
            for integer in ('i64', 'i128', 'bigint'):
                with self.subTest(source=source, integer=integer):
                    with patch('py2fastrust.codegen.generate', side_effect=AssertionError('VM used')):
                        result = transpile(source, TranspileOptions(integer=integer, license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(result.diagnostics)
                    self.assertEqual(result.diagnostics[0].code, 'E006')
                    self.assertIn('complex', result.diagnostics[0].message)
                    self.assertEqual(result.diagnostics[0].line, 1)
