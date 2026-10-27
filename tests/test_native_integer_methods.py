"""Integer bit queries and owned BigInt assignment stay direct Rust."""
from pathlib import Path
import random
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.aot import rust_mask
from py2fastrust.native import try_generate_native
from wrapping_reference import execute


BENCHMARK = runpy.run_path(str(Path(__file__).resolve().parents[1] / "benchmarks/run.py"))["CASES"]["bigint"]


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeIntegerMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-native-bit-methods-")
        cls.next_binary = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, integer="bigint", release=False):
        result = transpile(source, TranspileOptions(integer=integer, filename="main.py"))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, "native", source)
        rust = result.rust_source
        self.assertLess(len(rust.encode("utf-8")), 512 * 1024)
        masked = rust_mask(rust)
        for forbidden in [r"\benum\s+Value\b", r"\benum\s+Op\b", r"\bstruct\s+Runtime\b", r"\bfn\s+step\b", r"\bstruct\s+PegParser\b"]:
            self.assertNotRegex(masked, forbidden)
        type(self).next_binary += 1
        target = Path(self.tmp.name, f"program{self.next_binary}.rs")
        target.write_text(rust, encoding="utf-8")
        binary = target.with_suffix("")
        result = subprocess.run(["rustc", "--edition=2021", *(["-O"] if release else []), str(target), "-o", str(binary)], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr + "\n" + source)
        return binary, masked

    def compare(self, binary, source, integer="bigint", data=""):
        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=10)
        expected = execute(source, integer, data)
        self.assertEqual(actual.stdout, expected.stdout, source + "\n" + data)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
        if actual.returncode:
            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0], expected.exception_type)

    def test_actual_bigint_benchmark_is_compact_standalone_in_both_profiles(self):
        for release in (False, True):
            binary, masked = self.compile(BENCHMARK, release=release)
            self.assertIn(".bit_length()", masked)
            self.assertNotIn(".step(", masked)
            for n in (0, 1, 31, 127, 512, 5000):
                self.compare(binary, BENCHMARK, data=f"{n}\n")

    def test_signed_limb_boundaries_and_wrapped_receivers_all_modes(self):
        source = "n=int(input())\nfor i in range(n):\n a=int(input())\n print(a.bit_length(),a.bit_count())\n"
        values = [0, 1, -1]
        for bit in (1, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255, 256, 511):
            values.extend(sign*((1<<bit)+offset) for sign in (-1,1) for offset in (-1,0,1))
        rng = random.Random(6347)
        values += [rng.choice((-1,1))*rng.getrandbits(rng.randrange(1,1000)) for _ in range(80)]
        data = str(len(values)) + "\n" + "\n".join(map(str,values)) + "\n"
        for mode in ("i64", "i128", "bigint"):
            binary, _ = self.compile(source, mode)
            self.compare(binary, source, mode, data)

    def test_boolean_integer_unions_and_function_argument_specialization(self):
        source = '''def bits(value):
    return value.bit_length()+value.bit_count()
value=1
if int(input()):
    value=True
else:
    value=1<<60
print(value.bit_length(),value.bit_count(),True.bit_length(),False.bit_count())
print(bits(True),bits(1<<60),bits(False))
'''
        for mode in ("i64", "i128", "bigint"):
            binary, _ = self.compile(source, mode)
            for data in ("0\n", "1\n"):
                self.compare(binary, source, mode, data)

    def test_constant_method_results_remain_available_to_control_flow_proof(self):
        source = '''for i in range((1<<10).bit_count()):
    x=i+7
print(x,i,2**((255).bit_count()))
print((-17).bit_length(),(-17).bit_count(),(0).bit_length(),True.bit_count())
'''
        for mode in ("i64", "i128", "bigint"):
            binary, _ = self.compile(source, mode)
            self.compare(binary, source, mode)

    def test_receiver_is_evaluated_once_before_following_arguments_and_errors(self):
        source = '''def number():
    print(7,end="|")
    return int(input())
print(number().bit_length(),number().bit_count(),int(input()))
'''
        for mode in ("i64", "i128", "bigint"):
            binary, _ = self.compile(source, mode)
            for data in ("123\n-17\n99\n", "bad\n-17\n99\n", "123\n", ""):
                self.compare(binary, source, mode, data)

    def test_single_and_final_chained_target_move_the_owned_temporary(self):
        source = "a=b=c=10**100\nprint(a,b,c)\n"
        binary, masked = self.compile(source)
        self.compare(binary, source)
        main = masked[masked.rindex("fn main("):]
        clone_assignments = re.findall(r"native_var_\d+\s*=\s*\(native_temp_\d+\)\.clone\(\);", main)
        move_assignments = re.findall(r"native_var_\d+\s*=\s*native_temp_\d+;", main)
        self.assertEqual(len(clone_assignments), 2)
        self.assertEqual(len(move_assignments), 1)
        source = "a=10**100\nfor i in range(4):\n a=a*2+1\nprint(a)\n"
        binary, masked = self.compile(source)
        self.compare(binary, source)
        main = masked[masked.rindex("fn main("):]
        self.assertNotRegex(main, r"native_var_\d+\s*=\s*\(native_temp_\d+\)\.clone\(\);")

    def test_chains_aliases_phi_values_and_eager_rhs_effects_keep_values(self):
        source = '''def make(value):
    print(value,end="|")
    return value*(10**100)
a=b=c=make(int(input()))
d=a
a+=7
b=0
print(a,b,c,d)
v=True if int(input()) else 1<<300
x=y=v
v=False
print(x,y,v)
s=1
for i in range(5):
    left=right=s
    if i%2:
        s=True
    else:
        s=s*2+1
    print(left,right,s)
print(s)
'''
        binary, _ = self.compile(source)
        for data in ("3\n0\n", "3\n1\n", "bad\n0\n"):
            self.compare(binary, source, data=data)
        source = "print(9)\na=b=int(input())//int(input())\nprint(a,b)\n"
        binary, _ = self.compile(source)
        for data in ("123\n0\n", "123\n", "123\n3\n"):
            self.compare(binary, source, data=data)

    def test_user_method_with_integer_builtin_name_keeps_its_class_identity(self):
        source = "class C:\n def bit_count(self):return 77\nprint(C().bit_count())\n"
        expected = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=10)
        for mode in ("i64", "i128", "bigint"):
            binary, _ = self.compile(source, mode)
            actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual((actual.returncode, actual.stdout), (expected.returncode, expected.stdout), actual.stderr)

    def test_unproved_descriptors_bad_arity_and_noninteger_receivers_are_not_lowered(self):
        programs = [
            "class I(int):\n def bit_length(self):return 77\nprint(I(1).bit_length())\n",
            "print((1).bit_length(3))\n",
            "print((1).bit_count(extra=3))\n",
            "print((1.5).bit_length())\n",
            "m=(1).bit_count\nprint(m())\n",
        ]
        for mode in ("i64", "i128", "bigint"):
            for source in programs:
                with self.subTest(mode=mode,source=source):
                    self.assertIsNone(try_generate_native(source, "main.py", mode))
