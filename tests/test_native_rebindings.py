"""Typed slots and control-flow merges for native Python name rebinding."""

from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from wrapping_reference import execute


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeRebindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-native-rebindings-")
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, integer, optimized):
        rust = try_generate_native(source, "rebindings.py", integer)
        self.assertIsNotNone(rust, source)
        self.assertNotIn("enum Value", rust)
        self.assertNotIn("struct Runtime", rust)
        declarations = re.findall(r"let mut (native_var_\d+): ([^;]+);", rust)
        self.assertTrue(declarations)
        # Every generated slot has one type within its Rust function. Names
        # can reuse a slot or move to a different typed slot on assignment.
        self.assertTrue(all(kind in {"NativeInt", "bool", "Vec<NativeInt>", "NativeDict", "NativeSet"}
                            for _, kind in declarations))
        type(self).counter += 1
        path = Path(self.tmp.name) / f"rebindings{self.counter}.rs"
        path.write_text(rust, encoding="utf-8")
        compiled = subprocess.run(["rustc", "--edition=2021", *(["-O"] if optimized else []), str(path), "-o", str(path.with_suffix(""))],
                                  capture_output=True, text=True, timeout=90)
        self.assertEqual(compiled.returncode, 0, compiled.stderr + "\n" + source)
        return path.with_suffix("")

    def differential(self, source, inputs=("",), modes=("i64", "i128"), optimized=(False, True), wrapping=False):
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
            for optimization in optimized:
                with self.subTest(integer=integer, optimized=optimization):
                    binary = self.compile(source, integer, optimization)
                    for data, (stdout, code, kind) in zip(inputs, expected):
                        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
                        self.assertEqual(actual.stdout, stdout, source + "\n" + data)
                        self.assertEqual(actual.returncode, code, actual.stderr)
                        if kind:
                            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0], kind)

    def test_straight_line_every_supported_type_and_scalar_copies(self):
        self.differential('''
value=7
old=value
print(value,old)
value=True
print(value,old)
value=[1,2,3]
print(len(value),sum(value))
value={7:11,9:13}
print(value[7],sum(value.values()))
value={2,3,5}
value.add(7)
print(len(value),sum(value))
value=False
value+=3
print(value,old)
left=[5]
right={3:7}
left=right=True
print(left,right)
value=[4,8]
value,last=value
print(value,last)
''')

    def test_branch_phi_moves_for_bool_and_owned_containers(self):
        self.differential('''
flag=int(input())
value=7
if flag:
 value=True
else:
 value=False
print(value)
if flag:
 value=[1,2]
else:
 value=[7]
print(len(value),sum(value))
if flag%2:
 value={3:9,5:2}
else:
 value={3:7}
print(value[3],sum(value.values()))
if flag<0:
 value={1,2,3}
else:
 value={7,11}
print(len(value),sum(value))
''', ("-1\n", "0\n", "2\n"))

    def test_heterogeneous_or_unbound_join_can_be_overwritten_before_read(self):
        self.differential('''
flag=int(input())
value=3
if flag:
 value=[7]
else:
 value=True
value={7:13}
print(value[7])
if flag:
 temporary=False
temporary=[3,5]
print(sum(temporary))
''', ("0\n", "1\n"))

    def test_loop_header_and_exit_moves_cover_continue_break_and_zero(self):
        self.differential('''
n=int(input())
value=10
i=99
for i in range(n):
 print(value)
 value=[i,value]
 value=sum(value)+1
 if i%3==1:
  continue
 value={3:value,7:i}
 value=sum(value.values())
 if i==6:
  break
print(value,i)
''', ("0\n", "1\n", "5\n", "12\n"))

    def test_iteration_local_type_changes_and_proved_nonempty_exit(self):
        self.differential('''
n=int(input())
value=3
for i in range(n):
 value=[i,7]
 print(sum(value))
 value=True
value={9:17}
print(value[9])
value=3
for i in range(3):
 value=[i,11]
print(sum(value))
''', ("0\n", "1\n", "4\n"))

    def test_zero_and_single_iteration_can_change_for_target_type(self):
        self.differential('''
value=[7]
for value in range(0):
 value=True
print(sum(value))
for value in range(1):
 print(value)
 value=[5]
print(sum(value))
value=4
for i in range(1):
 print(value)
 value=True
print(value)
''')

    def test_while_header_versions_and_break_exit(self):
        self.differential('''
n=int(input())
value=5
i=0
while i<n:
 print(value)
 value=[i,value]
 value=sum(value)+3
 i+=1
 if i%2==0:
  continue
 if i==5:
  break
print(value,i)
value=9
while True:
 value={1:7}
 if n:
  break
 value={1:9}
 break
print(value[1])
value=[17]
while False:
 value=True
print(sum(value))
''', ("0\n", "1\n", "3\n", "9\n"))

    def test_parameters_evaluation_order_and_exceptions(self):
        self.differential('''
def change(value):
 original=value
 value=value>0
 print(value,original)
 value=[original,int(input())]
 value={3:sum(value),7:original}
 value={value[3],value[7]}
 return sum(value)
print(change(int(input())))
''', ("3\n9\n", "-7\n2\n", "3\ninvalid\n"))

    def test_nested_loops_and_container_carried_versions(self):
        self.differential('''
n=int(input())
value=[2]
for i in range(n):
 value=sum(value)
 for j in range(2):
  value=[value,j]
  value=sum(value)
 value=[value+i]
 if i%2:
  continue
 value=[sum(value)+3]
print(sum(value))
value={0:5}
for i in range(n):
 value=sum(value.values())
 if i%2:
  value={0:value+i}
 else:
  value={0:value,1:i}
 if i==4:
  break
print(sum(value.values()))
value={2,7}
for i in range(n):
 value=sum(value)
 value={value,i}
 if i%3:
  continue
 value.add(3)
print(sum(value))
''', ("0\n", "1\n", "3\n", "8\n"))

    def test_fixed_width_random_programs_across_rebindings(self):
        rng = random.Random(20261028)
        inputs = []
        for bits in (64, 128):
            values = [-(1 << (bits-1)), (1 << (bits-1))-1, 1 << bits, -1, 0, 1]
            values += [rng.randrange(-(1 << bits), 1 << bits) for _ in range(8)]
            inputs += [f"{value}\n{rng.randrange(-99,100)}\n{rng.randrange(0,9)}\n" for value in values]
        self.differential('''
value=int(input())
b=int(input())
n=int(input())
for i in range(n):
 old=value
 value=old>0
 if i%2:
  value=[old,b,old*b]
 else:
  value=[old-b,b,old//3]
 value=sum(value)
 value={i:value,value:i}
 value=sum(value.values())
 if i%3==0:
  continue
 value={value,old,b}
 value=sum(value)
print(value)
''', inputs, wrapping=True)

    def test_ambiguous_loop_carried_types_aliases_and_order_fall_back(self):
        programs = [
            "value=1\nif int(input()): value=True\nprint(value)",
            "value=1\nfor i in range(int(input())): value=True\nprint(value)",
            "value=1\nfor i in range(3):\n print(value)\n value=True\nprint(value)",
            "value=1\ni=0\nwhile i<3:\n print(value)\n value=True\n i+=1\nprint(value)",
            "value=1\ni=0\nwhile True:\n if i==1: break\n value=[2]\n i+=1\nprint(value)",
            "value=[1]\nold=value\nvalue=3\nold.append(2)\nprint(old,value)",
            "value={1:2}\nold=value\nvalue=True\nold[3]=4\nprint(old,value)",
            "value={1}\nold=value\nvalue=[3]\nold.add(2)\nprint(old,value)",
            "value=[1,2]\nfor x in value:\n value=3\nprint(value)",
            "value=[1,2]\nfor value in value: pass\nprint(value)",
            "value=1\nvalue='text'\nprint(value)",
        ]
        for source in programs:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "fallback.py", "i64"))
        alias = '''
value=[1]
old=value
value=True
old.append(2)
print(old,value,old is value)
value={1:2}
old=value
value=3
old[4]=5
print(old,value)
value={1}
old=value
value=[7]
old.add(2)
print(sorted(old),value)
'''
        result = transpile(alias, TranspileOptions())
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "vm")
        path = Path(self.tmp.name) / "alias.rs"
        path.write_text(result.rust_source, encoding="utf-8")
        binary = path.with_suffix("")
        compiled = subprocess.run(["rustc", "--edition=2021", str(path), "-o", str(binary)], capture_output=True, text=True, timeout=90)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
        expected = subprocess.run([sys.executable, "-I", "-c", alias], capture_output=True, text=True, timeout=5)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout)


if __name__ == "__main__":
    unittest.main()
