"""Integral round uses source argument order and decimal ties-to-even."""
import shutil
import unittest
import test_native_union_ordering as support
from py2fastrust import transpile


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeIntegralRoundTests(unittest.TestCase):
    setUpClass=classmethod(support.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(support.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=support.NativeUnionOrderingTests.compile
    exercise=support.NativeUnionOrderingTests.exercise

    def test_integral_ties_aliases_and_keywords(self):
        self.exercise('saved=round\nfor value in [15,25,35,-15,-25,-35,99,-99,True,False]:\n print(saved(value,-1),round(number=value),round(value,ndigits=None))\nprint(round(2**60+125,-3),round(2**60+125,-30))\n',('',))

    def test_binding_error_preserves_all_explicit_argument_effects(self):
        self.exercise('def mark(label,value):\n print(label)\n return value\nround(mark("first",1),mark("second",2),mark("third",3))\n',('',))

    def test_invalid_digits_has_the_real_integer_index_error(self):
        self.exercise('saved=round\nprint("before")\nsaved(17,"bad")\n',('',))

    def test_binary64_capability_is_explicit(self):
        result=transpile('print(round(2.5))\n')
        self.assertFalse(result.success)
        self.assertIn('binary64',str(result.diagnostics[0]))

    def test_sealed_absent_attribute_does_not_block_union_convergence(self):
        self.exercise('class Packet:\n def __init__(self,value):self.value=value\ndef choose(flag):\n if flag:return 5\n return Packet(9)\nprint(choose(int(input())).value)\n',('0\n','1\n'))
