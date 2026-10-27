"""Shared literal meaning and integer policy reach every direct emitter."""
import ast
import random
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.literal_semantics import Literal,integer_policy
import test_native_slices as _slices
import test_native_integer_methods as _integers


class LiteralSemanticsTests(unittest.TestCase):
    def test_integer_policy_congruence_bounds_and_idempotence(self):
        rng=random.Random(19007)
        for bits in (0,64,128):
            policy=integer_policy(bits)
            self.assertIs(policy,integer_policy(bits))
            values=[0,1,-1,*[sign*(2**power+delta)for power in (31,63,64,127,128,500)
                            for sign in (-1,1)for delta in (-1,0,1)]]
            values += [rng.getrandbits(700)*rng.choice((-1,1))for _ in range(300)]
            for value in values:
                normalized=policy.normalize(value)
                self.assertEqual(policy.normalize(normalized),normalized)
                if bits:
                    self.assertLessEqual(-(1<<(bits-1)),normalized)
                    self.assertLess(normalized,1<<(bits-1))
                    self.assertEqual((value-normalized)%(1<<bits),0)
                else:self.assertEqual(normalized,value)

    def test_literal_domain_keeps_bool_none_and_bytes_distinct(self):
        for value,kind in [(None,"none"),(True,"bool"),(1,"int"),(1.0,"float"),("猫","str"),(b"\xff","bytes")]:
            literal=Literal.from_ast(ast.Constant(value=value))
            self.assertEqual((literal.kind,literal.value),(kind,value))
        for value in (1j,Ellipsis,"\ud800"):
            self.assertIsNone(Literal.from_ast(ast.Constant(value=value)))

    def test_scalar_bigint_and_class_atoms_use_the_shared_lowerer(self):
        sources=("value=13\nflag=True\ntext='猫'\nprint(value,flag,text)\n",
                 "class Box:\n def __init__(self):self.value=13;self.flag=True;self.text='猫'\nb=Box()\nprint(b.value,b.flag,b.text)\n")
        real=Literal.rust_atom
        for source in sources:
            for mode in ("i64","i128","bigint"):
                with self.subTest(source=source,mode=mode),patch.object(Literal,"rust_atom",autospec=True,side_effect=real)as lower:
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertTrue({"int","bool","str"}<={call.args[0].kind for call in lower.call_args_list})


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class LiteralExecutionTests(unittest.TestCase):
    def test_integer_literals_and_folding_follow_one_wrapping_policy(self):
        source="print("+",".join(str(value)for value in [0,1,-1,2**63-1,2**63,-2**63,
                                                          2**127-1,2**127,-2**127,2**128+17,-2**200])+ ")\n"
        # Reuse the independent wrapping reference and standalone Rust harness.
        harness=_integers.NativeIntegerMethodTests()
        harness.setUpClass()
        try:
            for mode in ("i64","i128","bigint"):
                for release in (False,True):
                    binary,_=harness.compile(source,mode,release)
                    harness.compare(binary,source,mode)
        finally:harness.tearDownClass()

    def test_unicode_bytes_floats_and_class_literals_execute(self):
        source=r'''text="猫\x00\\海"
flag=True
data=b"\x00\xff'\\"
print(text,flag,data,sep="|")
'''
        _slices.NativeSliceTests.compare(self,source)
        source=r'''class Value:
    def __init__(self):
        self.text="猫\x00\\海"
        self.flag=True
        self.data=b"\x00\xff'\\"
        self.nothing=None
v=Value()
print(v.text,v.flag,v.data,v.nothing,sep="|")
'''
        _slices.NativeSliceTests.compare(self,source)
        floating='''class Value:
    def __init__(self):self.x=-0.0;self.y=1e400
v=Value()
print(v.x,v.y,1.25)
'''
        _slices.NativeSliceTests.compare(self,floating,modes=("i64","i128"))


if __name__=="__main__":unittest.main()
