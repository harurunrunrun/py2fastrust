"""Captured pow retains integer policy, current bindings and call evaluation."""
import math
import random
import unittest
import subprocess
import sys
import tempfile
import test_native_integer_methods as integer_support
import test_native_module_linking as runtime_support


class NativeCapturedPowTests(unittest.TestCase):
    exercise=runtime_support.NativeLinkedModuleTests.exercise
    compile=integer_support.NativeIntegerMethodTests.compile

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='pytors-captured-pow-width-')
        cls.next_binary=0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_bare_frame_and_keyword_calls(self):
        self.exercise({'main.py': 'MOD=101\ndef calculate(base,exponent):\n    return pow(base,exponent,MOD)\nprint(calculate(7,19),calculate(3,-4))\nfrom builtins import pow as power\nprint(power(exp=5,base=2,mod=13),power(3,mod=11,exp=4))\n'})

    def test_positive_two_argument_aliases(self):
        self.exercise({'main.py': 'from builtins import pow as p\nprint(p(2,10),p(-2,3),p(base=3,exp=4),p(2,3,None),p(True,False))\n'})

    def test_builtin_rebind_and_old_alias(self):
        self.exercise({'main.py': 'import builtins\noriginal=pow\ndef replacement(base,exp,mod):return original(base,exp,mod)+1\nbuiltins.pow=replacement\nprint(original(2,10,17),pow(2,10,17),builtins.pow(2,10,17))\n'})

    def test_callee_before_mutating_argument(self):
        self.exercise({'main.py': 'import builtins\ndef replacement(base,exp,mod):return 99\ndef change():\n    builtins.pow=replacement\n    print("change")\n    return 7\nprint(pow(2,3,change()),pow(2,3,7))\n'})

    def test_keyword_evaluation_order(self):
        self.exercise({'main.py': 'import builtins\ndef mark(name,value):\n    print(name)\n    return value\np=pow\nprint(p(mod=mark("mod",13),exp=mark("exp",5),base=mark("base",2)))\n'})

    def test_zero_modulus(self):
        self.exercise({'main.py': 'import builtins\np=pow\nprint(p(2,-1,0))\n'})

    def test_noninvertible(self):
        self.exercise({'main.py': 'from builtins import pow as power\nprint(power(6,-1,9))\n'})

    def test_float_third_argument_error(self):
        self.exercise({'main.py': 'from builtins import pow as power\nprint(power("bad",2,3.0))\n'})

    def test_sealed_three_operand_type_error(self):
        self.exercise({'main.py': 'from builtins import pow as power\nprint(power(None,2,3))\n'})

    def test_sealed_two_operand_type_error(self):
        self.exercise({'main.py': 'from builtins import pow as power\nprint(power("bad",3))\n'})

    def test_missing_required_after_argument_effect(self):
        self.exercise({'main.py': 'import builtins\ndef value():\n    print("argument")\n    return 2\nprint(pow(value(),base=3))\n'})

    def test_excess_arguments_after_effects(self):
        self.exercise({'main.py': 'import builtins\ndef value(n):\n    print(n)\n    return n\nprint(pow(value(1),value(2),value(3),bad=value(4)))\n'})

    def test_duplicate_keyword_binding(self):
        self.exercise({'main.py': 'from builtins import pow as power\nprint(power(2,3,base=4))\n'})

    def test_unknown_keyword_binding(self):
        self.exercise({'main.py': 'from builtins import pow as power\nprint(power(base=2,exp=3,unexpected=4))\n'})

    def test_empty_call_binding(self):
        self.exercise({'main.py': 'from builtins import pow as power\npower()\n'})

    def test_seeded_modular_inverse_and_signed_boundary_vectors(self):
        rng=random.Random(729184)
        rows=[(0,0,1),(0,3,-1),(-2,15,-101),(2,-5,101),(-3,-2,-101),(True,False,2),(False,False,True),(-(1<<63),3,97),((1<<63)-1,-3,-(1<<63)),(0,-1,1),(0,-2,-1)]
        while len(rows)<160:
            base=rng.randrange(-10**7,10**7)
            exponent=rng.randrange(-1000,1001)
            modulus=rng.choice((-1,1))*rng.randrange(1,100000)
            if exponent<0 and math.gcd(base,modulus)!=1:continue
            rows.append((base,exponent,modulus))
        source='from builtins import pow as power\ncases='+repr(rows)+'\nfor base,exponent,modulus in cases:\n    print(power(base,exponent,modulus))\n'
        self.exercise({'main.py':source})


    def test_selected_integer_width_normalizes_inputs_and_atomic_result(self):
        rows=[((1<<190)+7,(1<<64)+3,1000000007),(-(1<<150)+3,3,-1000000007),((1<<127)-1,2,17)]
        source='from builtins import pow as power\ncases='+repr(rows)+'\nfor base,exponent,modulus in cases:\n    print(power(base,exponent,modulus))\n'
        cp=subprocess.run([sys.executable,'-I','-S','-c',source],text=True,capture_output=True,timeout=10)
        self.assertEqual(cp.returncode,0,cp.stderr)
        def normalize(value,bits):
            return(value+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))if bits else value
        for integer,bits in(('i64',64),('i128',128),('bigint',0)):
            expected=''.join(str(normalize(pow(*(normalize(value,bits)for value in row)),bits))+'\n'for row in rows)
            if not bits:self.assertEqual(expected,cp.stdout)
            for release in(False,True):
                with self.subTest(integer=integer,release=release):
                    binary,_=self.compile(source,integer,release)
                    actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10)
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected,''))


class CapturedPowDiagnosticTests(unittest.TestCase):
    def test_unimplemented_two_argument_power_keeps_a_positioned_protocol_boundary(self):
        from py2fastrust import transpile,TranspileOptions
        # These remain required unfinished protocols, not supported conversions.
        sources=['from builtins import pow as power\nexponent=int(input())\nprint(power(2,exponent))\n','from builtins import pow as power\nprint(power(2,-3))\n','from builtins import pow as power\nprint(power(2.0,3))\n']
        for source in sources:
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,filename='pow_protocol.py'))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertEqual(result.diagnostics[0].filename,'pow_protocol.py')
                self.assertGreater(result.diagnostics[0].line,0)
                self.assertIn('power',result.diagnostics[0].message)

