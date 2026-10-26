"""Native scalar backend correctness, rejection, and optional speed checks."""
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest

from py2fastrust.native import try_generate_native


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-native-")
        cls.next_binary = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, integer="i64"):
        rust = try_generate_native(source, "native_input.py", integer)
        self.assertIsNotNone(rust, source)
        self.assertNotIn("enum Value", rust)
        self.assertNotIn("enum Op", rust)
        self.assertNotIn("Runtime::new", rust)
        type(self).next_binary += 1
        rs = Path(self.tmp.name) / f"program{self.next_binary}.rs"
        rs.write_text(rust)
        binary = rs.with_suffix("")
        compiled = subprocess.run(["rustc", "--edition=2021", "-O", str(rs), "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stderr + "\n" + source)
        return binary

    def differential(self, source, inputs=("",), integer="i64"):
        binary = self.compile(source, integer)
        for data in inputs:
            actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
            expected = subprocess.run([sys.executable, "-c", source], input=data, capture_output=True, text=True, timeout=5)
            self.assertEqual(actual.stdout, expected.stdout, source + "\n" + data)
            self.assertEqual(actual.returncode, expected.returncode, actual.stderr + "\n" + expected.stderr)
            if actual.returncode:
                self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0], expected.stderr.splitlines()[-1].split(":")[0])

    def test_arithmetic_inputs_and_native_loops(self):
        source = '''
n = int(input())
total = 0
for i in range(n):
    if i % 7 == 0:
        continue
    total += (i * i + 3 * i - 17) // 5
    if total > 100000:
        break
j = 0
while j < 10:
    j += 1
    if j == 3:
        continue
    total ^= (j << 4) | (j >> 2)
print(total, j)
'''
        for integer in ("i64", "i128"):
            self.differential(source, ("0\n", "1\n", "9\n", "1000\n"), integer)

    def test_floor_and_negative_bitwise(self):
        source = '''
a = int(input())
b = int(input())
print(a // b, a % b, a & b, a | b, a ^ b, ~a)
print(-a, abs(a), +a, a << 3, a >> 3, a ** 3)
'''
        data = [f"{a}\n{b}\n" for a in (-12345, -1, 0, 1, 12345) for b in (-31, -1, 1, 31)]
        self.differential(source, data)

    def test_binding_flow_and_loop_targets(self):
        source = '''
n = int(input())
if n:
    a = 11
else:
    a = 22
i = 77
for i in range(n):
    i = i + 10
print(a, i)
for j in range(3):
    j += 100
print(j)
for k in range(10, 0, -2):
    if k == 6:
        break
print(k)
'''
        self.differential(source, ("0\n", "1\n", "5\n"))

    def test_nested_break_continue(self):
        source = '''
total = 0
for i in range(5):
    for j in range(7):
        if j == 2:
            continue
        if i + j > 5:
            break
        total += i * 10 + j
    if i == 3:
        break
print(total, i)
'''
        self.differential(source)

    def test_boolean_values_and_short_circuit_order(self):
        source = '''
a = int(input())
b = int(input())
c = a < b
print(c, not c, c + True, a and b, a or b)
print(0 and int(input()), 1 or int(input()))
print(int(input()) < int(input()) < int(input()))
print(int(input()))
'''
        # The failed first comparison must not consume the third operand.
        self.differential(source, ("2\n5\n9\n1\n7\n8\n", "5\n2\n1\n9\n7\n8\n"))

    def test_input_line_and_print_boundaries(self):
        source = '''
a = int(input())
b = int(input())
c = int(input())
print(a, b, c, sep="\\t", end="|\\n")
print()
print(True, False, sep="", end="\\b\\f")
'''
        self.differential(source, ("１２\r\n-３\r\n٤\n", "12\n-3\n4", " 12 \n -3 \n 4 \n", "１２\r\n-３\r٤\n"))

    def test_errors_preserve_preceding_output(self):
        for source, data in [("print(9)\na=int(input())\nprint(a)", ""), ("print(9)\na=int(input())\nprint(a)", "\n"), ("print(9)\nprint(1//0)", ""), ("print(9)\nprint(1<<-1)", ""), ("print(9)\nfor i in range(1,2,0):\n print(i)", "")]:
            self.differential(source, (data,))
        # Input lines cannot be silently replaced with a token scanner.
        self.differential("a=int(input())\nprint(a)", ("1 2\n",))

    def test_fixed_width_policy_and_range_end_overflow(self):
        for integer, bits in (("i64", 64), ("i128", 128)):
            minimum, maximum = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
            source = f'''
a={maximum}
print(a+1, a*2, -({minimum}), abs({minimum}))
print(({minimum})//-1, ({minimum})%-1)
print(1<<{bits}, -1>>{bits})
print(pow(3, -1, {minimum}))
for i in range({maximum}-1, {maximum}, 2):
    print(i)
for j in range({minimum}+1, {minimum}, -2):
    print(j)
'''
            binary = self.compile(source, integer)
            actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            inverse = pow(3, -1, minimum)
            expected = f"{minimum} -2 {minimum} {minimum}\n{minimum} 0\n0 -1\n{inverse}\n{maximum-1}\n{minimum+1}\n"
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(actual.stdout, expected)

    def test_unit_ranges_at_both_signed_extremes(self):
        for integer, bits in (("i64", 64), ("i128", 128)):
            minimum, maximum = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
            source = f'''
for i in range({maximum}, {minimum}, -1):
    print(i)
    break
for j in range({minimum}, {maximum}):
    print(j)
    break
for k in range(5, -2, -1):
    if k == 2:
        continue
    print(k)
print(i, j, k)
'''
            self.differential(source, integer=integer)

    def test_random_integer_programs(self):
        rng = random.Random(20261026)
        lines = ["x=int(input())", "y=int(input())", "total=0"]
        for _ in range(60):
            operator = rng.choice(("+", "-", "*", "&", "|", "^", "//", "%"))
            left = rng.choice(("x", "y", str(rng.randrange(-100, 101))))
            right = str(rng.randrange(1, 101)) if operator in ("//", "%") else rng.choice(("x", "y", str(rng.randrange(-100, 101))))
            lines.append(f"total += ({left} {operator} {right})")
        lines.append("print(total)")
        self.differential("\n".join(lines), tuple(f"{rng.randrange(-100,101)}\n{rng.randrange(-100,101)}\n" for _ in range(20)))

    def test_integer_list_construction_iteration_and_scope(self):
        source = '''
n=int(input())
i=999
values=[i*i-3*i for i in range(n) if i%3]
total=0
value=77
for value in values:
    total+=value
print(total, len(values), sum(values), sum(values,5), value, i)
literal=[3,1,4]
for last in literal:
    total+=last
print(last)
shadow=[shadow+1 for shadow in range(3)]
print(shadow[0], shadow[-1])
repeated=[1,2]*3
for item in repeated:
    print(item, end=" ")
print()
other=2*[9,7]
print(other[0],other[-1],len(other))
'''
        for integer in ("i64", "i128"):
            self.differential(source, ("0\n", "1\n", "20\n"), integer)

    def test_integer_list_dynamic_programming(self):
        source = '''
n=int(input())
dp=[0]*(n+2)
dp[1]=1
for i in range(2,n+1):
    dp[i]=dp[i-1]+dp[i-2]
print(dp[n],dp[-1],len(dp))
for i in range(len(dp)):
    dp[i]+=i
print(sum(dp))
'''
        self.differential(source, ("0\n", "1\n", "2\n", "10\n", "40\n"))
        self.differential(source, ("100\n",), "i128")

    def test_list_index_and_assignment_evaluation_order(self):
        source = '''
a=[0,0,0]
a[int(input())]=int(input())
print(a[0],a[1],a[2])
a[int(input())]+=int(input())
print(a[-3],a[-2],a[-1])
b=int(input())*[int(input()),int(input())]
print(b[0],b[1],b[-1],len(b))
'''
        self.differential(source, ("9\n1\n-2\n5\n2\n7\n8\n",))
        for source in ("a=[1]\na[9]+=1//0", "a=[1]\na[9]=1//0", "a=[1]\nprint(a[1])", "a=[1]\nprint(a[-2])", "a=[]\nprint(a[0])", "a=[1]\na[-2]=3"):
            self.differential(source)
        self.differential("a=[]*(-3)\nb=[0]*0\nprint(len(a),len(b),sum(a))")
        self.differential("a=[]*(2**100)\nprint(len(a))", integer="i128")

    def test_integer_list_alias_and_mutation_fallback(self):
        rejected = [
            "a=[1]\nb=a\nprint(b[0])", "a=b=[1]\nprint(a[0])",
            "a=[1]\na[0]=True", "a=[True,1]", "a=[[1]]", "a=[1]\na=2",
            "a=[1]\na.append(2)", "a=[1]\nfor x in a:\n a[0]=2",
            "a=[1]\nfor x in a:\n a=[3]", "a=[1]\nfor x in a:\n a.append(x)",
            "a=[1]\nb=a if True else [2]\nprint(b[0])", "a=[1]\nb=a or [2]",
            "a=[1]\na*=3", "a=[1]\nprint(a[:])", "a=[1]\nb=a[0:1]",
            "a=[]\nprint(sum(a, True))",
            "a=[]\nfor x in a:\n pass\nprint(x)",
            "a=[i for i in range(3)]\nprint(i)",
            "a=[i for i in range(3) for j in range(2)]", "a=[1]\nfor a in a:\n pass",
        ]
        for source in rejected:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "fallback.py", "i64"))

    def test_conservative_fallback(self):
        rejected = [
            "print(x)\nx=1", "x=x+1", "if int(input()):\n x=1\nprint(x)",
            "for i in range(int(input())):\n pass\nprint(i)",
            "for i in range(0):\n pass\nprint(i)",
            "while int(input()):\n x=1\nprint(x)",
            "x=1\nx=True\nprint(x)", "x=1\nx='hi'\nprint(x)",
            "print(1)\nprint=2", "int=1\nx=int(input())", "range=3\nfor i in range(3):\n pass",
            "x=eval(input())", "exec('x=1')", "import math\nprint(1)",
            "def f():\n return 1\nprint(f())", "class A:\n pass", "x=[1,2]\nprint(x)",
            "print(1/2)", "x=int(input())\nprint(2**x)", "print(2**-1)",
            "print(input())", "print(1, flush=True)", "print(*(1,2))",
            "for i in range(3):\n pass\nelse:\n print(1)", "del x", "print(1 is 1)",
        ]
        for source in rejected:
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source, "fallback.py", "i64"))
        self.assertIsNone(try_generate_native("print(1)", "fallback.py", "bigint"))

    @unittest.skipUnless("--benchmark-native" in sys.argv, "optional performance benchmark")
    def test_native_loop_performance(self):
        """Run with --benchmark-native to print a repeatable Rust baseline ratio.

        The benchmark is optional because shared-host CPU scheduling should not
        make normal correctness tests fail. The intended acceptance target is
        native AOT <= 2x the handwritten scalar Rust median.
        """
        source = "n=int(input())\ns=0\nfor i in range(n):\n s += (i*i) ^ (i>>3)\nprint(s)"
        binary = self.compile(source)
        baseline = Path(self.tmp.name) / "handwritten.rs"
        baseline.write_text('''
use std::io::Read;
fn main(){let mut t=String::new();std::io::stdin().read_to_string(&mut t).unwrap();let n:i64=t.trim().parse().unwrap();let mut s=0i64;for i in 0..n{s=s.wrapping_add(i.wrapping_mul(i)^(i>>3));}println!("{}",s);}
''')
        baseline_binary = baseline.with_suffix("")
        subprocess.run(["rustc", "-O", str(baseline), "-o", str(baseline_binary)], check=True, capture_output=True)
        timings = []
        outputs = []
        for executable in (binary, baseline_binary):
            samples = []
            for _ in range(7):
                start = time.perf_counter()
                result = subprocess.run([str(executable)], input="50000000\n", capture_output=True, text=True, check=True)
                samples.append(time.perf_counter() - start)
                outputs.append(result.stdout)
            timings.append(statistics.median(samples))
        self.assertEqual(len(set(outputs)), 1)
        ratio = timings[0] / timings[1]
        print(f"native loop: {timings[0]:.6f}s; handwritten: {timings[1]:.6f}s; ratio: {ratio:.3f}")
        self.assertLessEqual(ratio, 2.0)

    @unittest.skipUnless("--benchmark-native" in sys.argv, "optional performance benchmark")
    def test_native_list_performance(self):
        benchmarks = [
            (
                "array scan",
                "n=int(input())\na=[i*3 for i in range(n)]\ns=0\nfor x in a:\n s+=x^7\nprint(s)",
                'let mut a=Vec::new();for i in 0..n{a.push(i.wrapping_mul(3));}let mut s=0i64;for &x in &a{s=s.wrapping_add(x^7);}println!("{}",s);',
            ),
            (
                "array DP",
                "n=int(input())\na=[0]*(n+2)\na[1]=1\nfor i in range(2,n+1):\n a[i]=a[i-1]+a[i-2]\nprint(a[n])",
                'let mut a=vec![0i64;n as usize+2];a[1]=1;for i in 2..=n as usize{a[i]=a[i-1].wrapping_add(a[i-2]);}println!("{}",a[n as usize]);',
            ),
        ]
        for label, source, rust_body in benchmarks:
            binary = self.compile(source)
            baseline = Path(self.tmp.name) / ("handwritten_" + label.replace(" ", "_") + ".rs")
            baseline.write_text('use std::io::Read;fn main(){let mut t=String::new();std::io::stdin().read_to_string(&mut t).unwrap();let n:i64=t.trim().parse().unwrap();' + rust_body + '}')
            baseline_binary = baseline.with_suffix("")
            subprocess.run(["rustc", "-O", str(baseline), "-o", str(baseline_binary)], check=True, capture_output=True)
            timings, outputs = [], []
            for executable in (binary, baseline_binary):
                samples = []
                for _ in range(7):
                    start = time.perf_counter()
                    result = subprocess.run([str(executable)], input="10000000\n", capture_output=True, text=True, check=True)
                    samples.append(time.perf_counter() - start)
                    outputs.append(result.stdout)
                timings.append(statistics.median(samples))
            self.assertEqual(len(set(outputs)), 1)
            ratio = timings[0] / timings[1]
            print(f"native {label}: {timings[0]:.6f}s; handwritten: {timings[1]:.6f}s; ratio: {ratio:.3f}")
            self.assertLessEqual(ratio, 2.0)


if __name__ == "__main__":
    if "--benchmark-native" in sys.argv:
        sys.argv.remove("--benchmark-native")
    unittest.main()
