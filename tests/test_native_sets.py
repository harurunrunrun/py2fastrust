"""Proved exact-integer sets: native correctness and conservative fallback."""

from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from wrapping_reference import execute


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-native-sets-")
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, integer, optimized):
        rust = try_generate_native(source, "native_sets.py", integer)
        self.assertIsNotNone(rust, source)
        self.assertIn("HashSet<NativeInt>", rust)
        self.assertNotIn("enum Value", rust)
        self.assertNotIn("struct Runtime", rust)
        type(self).counter += 1
        path = Path(self.tmp.name) / f"sets{self.counter}.rs"
        path.write_text(rust, encoding="utf-8")
        command = ["rustc", "--edition=2021", *(["-O"] if optimized else []), str(path), "-o", str(path.with_suffix(""))]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(compiled.returncode, 0, compiled.stderr + "\n" + source)
        return path.with_suffix("")

    def differential(self, source, inputs=("",), modes=("i64", "i128"), optimizations=(False, True), wrapping=False):
        for integer in modes:
            expected = []
            for data in inputs:
                if wrapping:
                    value = execute(source, integer, data)
                    expected.append((value.stdout, value.returncode, value.exception_type))
                else:
                    value = subprocess.run([sys.executable, "-I", "-c", source], input=data, capture_output=True, text=True, timeout=5)
                    kind = value.stderr.strip().splitlines()[-1].split(":")[0] if value.returncode else None
                    expected.append((value.stdout, value.returncode, kind))
            for optimized in optimizations:
                with self.subTest(integer=integer, optimized=optimized):
                    binary = self.compile(source, integer, optimized)
                    for data, (stdout, returncode, kind) in zip(inputs, expected):
                        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
                        self.assertEqual(actual.stdout, stdout, source + "\n" + data)
                        self.assertEqual(actual.returncode, returncode, actual.stderr)
                        if kind is not None:
                            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0], kind)

    def test_constructor_mutations_copy_and_order_independent_consumers(self):
        self.differential('''
s=set()
s.update()
empty=set([])
empty.update(())
print(len(empty))
order={7}
order.update((len(order),sum(order)))
print(len(order),sum(order))
s.add(3)
s.add(3)
s.add(-7)
t=set(s)
s.update([1,2,3])
s.update((9,-7,9))
s.update(range(8,-4,-2))
s.update(s)
s.discard(999)
s.remove(-7)
print(len(s),sum(s),sum(s,17),len(t),sum(t),3 in s,-7 not in s)
t.clear()
print(len(t),not t,not s)
u=set({9:3,8:4})
v=set((3,-4,3))
w={17,17,-8,0}
print(sum(u),sum(v),len(w),sum(w),0 in w)
''')

    def test_input_evaluation_and_constructor_errors(self):
        self.differential('''
print(7)
s={int(input()),int(input()),int(input())}
print(len(s),sum(s))
t=set([int(input()),int(input())])
s.update((int(input()),int(input())))
print(len(s),sum(s),sum(t),int(input()))
''', ("1\n2\n1\n5\n6\n7\n8\n9\n", "1\ninvalid\n99\n"), optimizations=(True,))
        self.differential('''
s={3}
print(sum(s))
s.update(range(int(input()),int(input()),int(input())))
print(sum(s))
''', ("1\n4\n0\n", "4\n-1\n-2\n"), optimizations=(True,))

    def test_remove_and_argument_errors_preserve_prior_output(self):
        self.differential('''
s={1,3,-7}
print(len(s),sum(s))
s.remove(int(input()))
print(len(s),sum(s))
s.add(int(input()))
print(sum(s))
''', ("-7\n11\n", "99\n11\n", "1\ninvalid\n"))

    def test_branch_loop_rebinding_and_zero_iterations(self):
        self.differential('''
n=int(input())
if n%2:
 s={3,5}
else:
 s=set()
for i in range(n):
 if i==3:
  s={11}
 if i==5:
  continue
 s.add(i)
 if i==8:
  break
j=0
while j<n:
 s.discard(j)
 j+=1
print(len(s),sum(s),j)
s.clear()
print(len(s),not s)
''', ("0\n", "1\n", "4\n", "12\n"))

    def test_selected_width_key_collisions_and_sum_normalization(self):
        for integer, bits in (("i64", 64), ("i128", 128)):
            self.differential(f'''
maximum={(1 << (bits-1))-1}
s={{0,1,{1 << bits},{(1 << bits)+1},maximum,maximum+1}}
s.add(1<<{bits})
s.add((maximum*3)//5)
print(len(s),sum(s),sum(s,maximum),maximum+1 in s)
s.remove({(1 << bits)+1})
print(1 in s,len(s),sum(s))
t=set([maximum,maximum+1,maximum*maximum])
t.update(range(-3,4))
print(len(t),sum(t),sum(t,maximum))
''', modes=(integer,), wrapping=True)

    def test_random_boundary_programs(self):
        rng = random.Random(20261027)
        inputs = []
        for bits in (64, 128):
            values = [-(1 << (bits-1)), (1 << (bits-1))-1, 1 << bits, -1, 0, 1]
            values += [rng.randrange(-(1 << bits), 1 << bits) for _ in range(12)]
            inputs += [f"{value}\n{rng.randrange(0,25)}\n" for value in values]
        self.differential('''
a=int(input())
n=int(input())
s={a,a+1,a*a}
for i in range(n):
 key=(a+i*17)^(a>>3)
 s.add(key)
 if i%3==0:
  s.discard(a+i)
print(len(s),sum(s),sum(s,a),a in s)
''', inputs, wrapping=True)

    def test_order_alias_dynamic_types_and_unbound_values_fall_back(self):
        programs = [
            "s={1}; t=s; t.add(2); print(len(s))",
            "s=t=set(); print(len(s))",
            "s={1}; print(s)",
            "s={1}; print(list(s))",
            "s={1}; print(s.pop())",
            "s={1}; s.pop()",
            "s={1};\nfor x in s:\n print(x)",
            "s={1}; t=[x for x in s]; print(sum(t))",
            "s={1}; print(s=={1})",
            "s={True}; print(len(s))",
            "s=set(); s.add(True)",
            "s={1}; print(True in s)",
            "s=set(); s.add(1.5)",
            "s={1}; s.add([2])",
            "s={1}; x=s.add(2)",
            "s={1}; s.update([2],[3])",
            "s={1}\nif input(): s='changed'\nprint(s)",
            "s={1}; f(s)",
            "s=set(x)",
            "set=list; s=set([1]); print(len(s))",
            "if int(input()): s={1}\nprint(len(s))",
            "for i in range(0): s=set()\nprint(len(s))",
            "class I(int): pass\ns={I(1)}; print(len(s))",
        ]
        for source in programs:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "fallback.py", "i64"))
        self.differential("s={1}; s='changed'; print(s)")
        self.differential("s={1}\nfor i in range(1): s.clear()\nfor x in range(len(s)): pass\nprint(x)")
        result = transpile("s={1}; t=s; t.add(2); print(len(s))", TranspileOptions())
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "aot")

    def test_bigint_integer_sets_use_native_backend(self):
        source = "s={1,1<<128};s.add(1<<256);print(len(s),sum(s),1<<256 in s)"
        self.assertIsNotNone(try_generate_native(source, "big.py", "bigint"))
        result = transpile(source, TranspileOptions(integer="bigint"))
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "native")
        path = Path(self.tmp.name) / "big.rs"
        path.write_text(result.rust_source, encoding="utf-8")
        binary = path.with_suffix("")
        compiled = subprocess.run(["rustc", "--edition=2021", str(path), "-o", str(binary)], capture_output=True, text=True, timeout=90)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
        expected = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True, text=True, timeout=5)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout)


if __name__ == "__main__":
    unittest.main()
