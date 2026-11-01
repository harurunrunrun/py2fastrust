"""Canonical native members preserve captured calls and Python effects."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'argument_effects_before_error': 'from operator import add\n'
                                  'def mark(v):\n'
                                  ' print(v)\n'
                                  ' return v\n'
                                  'add(mark(1),mark(2),mark(3))\n',
 'arithmetic_aliases': 'import operator as op\n'
                       'print(op.add(7,3),op.sub(7,3),op.mul(7,3),op.floordiv(-7,3),op.mod(-7,3),op.truediv(7,2))\n',
 'bitwise_members': 'from operator import and_,or_,xor,lshift,rshift\n'
                    'print(and_(7,3),or_(4,3),xor(7,3),lshift(3,2),rshift(-9,2))\n',
 'callable_alias_identity': 'from operator import mul\n'
                            'saved=mul\n'
                            'mul=lambda a,b:99\n'
                            'print(saved(3,4),mul(3,4))\n',
 'captured_finite_callables': 'from operator import add,mul\n'
                              'def apply(fn,a,b):return fn(a,b)\n'
                              'print(apply(add,3,4),apply(mul,3,4))\n',
 'division_error': 'from operator import floordiv\nfloordiv(1,0)\n',
 'invalid_arity': 'from operator import add\nadd(1)\n',
 'invalid_keywords': 'from operator import mul\nmul(a=1,b=2)\n',
 'invalid_operands': 'from operator import sub\nsub("a",1)\n',
 'negative_shift': 'from operator import lshift\nlshift(1,-1)\n',
 'nonclass_member_typequery': 'from operator import mul\nprint(isinstance(1,mul))\n',
 'sequence_add_and_repetition': 'from operator import add,mul\n'
                                'seed=[1]\n'
                                'result=add(seed,[2])\n'
                                'repeat=mul(seed,3)\n'
                                'print(seed,result,repeat,result is seed,repeat is '
                                'seed,add("a","b"))\n'}

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class OperatorTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_arithmetic_aliases(self):self.check('arithmetic_aliases')

    def test_bitwise_members(self):self.check('bitwise_members')

    def test_sequence_add_and_repetition(self):self.check('sequence_add_and_repetition')

    def test_callable_alias_identity(self):self.check('callable_alias_identity')

    def test_captured_finite_callables(self):self.check('captured_finite_callables')

    def test_invalid_arity(self):self.check('invalid_arity')

    def test_invalid_keywords(self):self.check('invalid_keywords')

    def test_argument_effects_before_error(self):self.check('argument_effects_before_error')

    def test_division_error(self):self.check('division_error')

    def test_invalid_operands(self):self.check('invalid_operands')

    def test_negative_shift(self):self.check('negative_shift')

    def test_nonclass_member_typequery(self):self.check('nonclass_member_typequery')
