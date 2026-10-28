"""Differential evidence for ordinary Rust String/f64 lowering."""

import random
import struct

from test_native import NativeTests
from py2fastrust.native import try_generate_native


class NativeTextFloatTests(NativeTests):
    string_mode = "unicode"

    # Reuse the compile/differential harness without rerunning its test cases.
    def test_native_string_assignments_unicode_and_type_changes(self):
        self.differential('''
value = 7
print(value)
value = "猫🐈é"
other = value
a = b = value
value += "!"
print(value, other, a, b, len(other), other[0], other[-1])
value = 2.5
print(value, 3 * "海", "x" * -3, True * "a", "海" + "風")
''')

    def test_native_string_and_float_same_type_joins_and_loop_phis(self):
        self.differential('''
n = int(input())
text = "old"
number = 0.25
if n > 0:
    text = "晴"
    number = 1.25
else:
    text = "雨"
    number = -0.0
for i in range(n):
    if i % 2:
        text = text + "!"
        number += 0.5
    else:
        text = text + "?"
        number -= 0.25
print(text, number)
''', ("0\n", "1\n", "6\n"))

    def test_native_text_input_and_conversions(self):
        self.differential('''
s = input()
t = input()
print(s, t, bool(s), s and t, s or t, sep="|")
print(len(s), len(t), s == t, s != t, s < t, s <= t, s > t, s >= t)
print("猫" in s, "猫" not in t, str(12), str(True), str(0.25))
print(float(s), int(t), float(True), bool(float(s)), float(), str(), bool())
''', ("1_2.5\n42\n", "  １２.５ \n  -٤٢ \n"))

    def test_native_float_arithmetic_floor_and_zero_sign(self):
        self.differential('''
a = float(input())
b = float(input())
print(a + b, a - b, a * b, a / b, a // b, a % b)
print(+a, -a, abs(a), bool(a), int(a), str(a))
''', tuple(f"{a}\n{b}\n" for a in (-10.0, -0.0, 0.0, 1.0, 10.0, 0.7)
                   for b in (-3.0, 0.1, 3.0)))

    def test_native_float_format_random_bits(self):
        randomizer = random.Random(1729)
        values = [-0.0, 0.0, 1e-4, 1e-5, 1e15, 1e16, 1e23,
                  float("inf"), float("-inf"), float("nan"), 5e-324]
        values += [struct.unpack(">d", randomizer.getrandbits(64).to_bytes(8, "big"))[0] for _ in range(4000)]
        values += [sign * (randomizer.randrange(2**50, 2**51) + .25)
                   for sign in (-1, 1) for _ in range(1000)]
        text = str(len(values)) + "\n" + "\n".join(map(repr, values)) + "\n"
        self.differential('''
n = int(input())
for i in range(n):
    print(float(input()))
''', (text,))

    def test_native_integer_float_comparison_is_exact(self):
        source = '''
n = int(input())
for k in range(n):
    i = int(input())
    f = float(input())
    print(i == f, i != f, i < f, i <= f, i > f, i >= f)
    print(f == i, f != i, f < i, f <= i, f > i, f >= i)
'''
        for bits in (64, 128):
            pairs = [(i, f) for i in (0, 1, -1, 2**53-1, 2**53+1, -(2**53+1),
                                               2**(bits-1)-1, -(2**(bits-1)))
                     for f in (0.0, -0.0, 0.5, -0.5, float(2**53), float(2**(bits-1)),
                               -float(2**(bits-1)), float("nan"), float("inf"), float("-inf"))]
            rng = random.Random(bits)
            pairs += [(rng.randrange(-(2**(bits-1)), 2**(bits-1)),
                       struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]) for _ in range(400)]
            data = str(len(pairs)) + "\n" + "".join(f"{i}\n{f!r}\n" for i, f in pairs)
            self.differential(source, (data,), f"i{bits}")

    def test_native_integer_true_division_rounds_once(self):
        source = '''
n = int(input())
for k in range(n):
    a = int(input())
    b = int(input())
    print(a / b)
'''
        for bits in (64, 128):
            edge = 2**(bits-1)
            pairs = [(a, b) for a in (-edge, -1, 0, 1, 2**53+1, edge-1)
                     for b in (-edge, -1, 1, 3, edge-1)]
            rng = random.Random(bits)
            pairs += [(rng.randrange(-edge, edge), rng.choice((-1, 1))*rng.randrange(1, edge)) for _ in range(1000)]
            data = str(len(pairs)) + "\n" + "".join(f"{a}\n{b}\n" for a,b in pairs)
            self.differential(source, (data,), f"i{bits}")

    def test_native_float_errors_and_short_circuit(self):
        for expression in ("1.0 / 0.0", "1.0 // -0.0", "1.0 % 0", "int(float('inf'))",
                           "int(float('nan'))", "float('1__2')", "float('nanx')", "float('\\x1c1')", "'猫'[3]"):
            self.differential(f"print('before', flush=True)\nprint({expression})\n")
        self.differential('''
print(1.0 > 2.0 > float(input()))
print("a" > "b" > input())
print(0.0 and float(input()), 1.0 or float(input()))
print("a" if True else input())
''')

    def test_native_float_integer_conversion_wraps(self):
        # CPython supplies mathematical integers; normalize in the oracle,
        # exactly as required by the fixed-width integer specification.
        import subprocess
        for bits in (64, 128):
            values = [0.0, -0.0, 0.5, -0.5, float(2**53+1), -float(2**53+1),
                      float(2**(bits-1)), -float(2**(bits-1)), float(2**(bits+20)), 1e300, -1e300]
            binary = self.compile("n = int(input())\nfor i in range(n):\n print(int(float(input())))\n", f"i{bits}")
            data = str(len(values)) + "\n" + "\n".join(map(repr, values)) + "\n"
            actual = subprocess.run([str(binary)], input=data, text=True, capture_output=True, timeout=5)
            expected = [((int(x)+2**(bits-1)) % 2**bits)-2**(bits-1) for x in values]
            self.assertEqual(actual.stdout, "".join(f"{x}\n" for x in expected))
            self.assertEqual(actual.returncode, 0, actual.stderr)

    def test_native_scalar_rust_types_and_conservative_boundary(self):
        rust = try_generate_native('s="abc"\nf=1.25\nprint(s, f)\n', "types.py", "i64")
        self.assertIsNotNone(rust)
        self.assertIn("struct NativeText", rust)
        self.assertIn('NativeTextLiteral::new("abc")', rust)
        self.assertIn("1.25_f64", rust)
        self.assertNotIn("enum Value", rust)
        self.assertNotIn("enum Op", rust)
        self.assertNotIn("NativeScalar", rust)
        self.assertIsNone(try_generate_native('s="abc"\nprint(id(s))\n', "types.py", "i64"))
        self.assertIsNone(try_generate_native('s="abc"\nprint(s is "abc")\n', "types.py", "i64"))
        self.differential('s="abc"\nf=1.25\nprint(s,f)\n',("",))
        self.differential('a=1.0\nif input(): a="x"\nprint(a)\n',("\n","x\n"))

    def test_native_scalar_function_specializations_and_defaults(self):
        self.differential('''
def add(a, b=0.5):
    return a + b
def adorn(text, sep="猫", *, count=2):
    return text + sep * count
def identity(value):
    return value
def choose(flag, text="海", number=-0.25):
    if flag:
        print(text, number)
        return text + "!"
    return text + "?"
print(add(2.0), add(1, b=2.5), adorn("x"), adorn("y", "風", count=3))
print(identity("text"), identity(2.5), identity(7), identity(True))
print(choose(True), choose(False, number=1.25))
''')

    def test_native_scalar_function_argument_order_and_output(self):
        self.differential('''
def decorate(left, right):
    print("called", left, right)
    left += "!"
    return left + right
def add(left, right):
    return left + right
original = input()
print(decorate(right=input(), left=original), original)
print(add(float(input()), float(input())))
''', ("猫\n海\n1.25\n2.5\n", "\n風\n-0.0\n0.0\n"))

    def test_native_scalar_function_error_retains_python_frames(self):
        import re
        import subprocess
        import sys
        source = '''
def divide(a, b):
    print("before", a, b, flush=True)
    return a / b
def caller(value):
    return divide(value, 0.0)
print(caller(2.5))
'''
        binary = self.compile(source)
        actual = subprocess.run([str(binary)], text=True, capture_output=True, timeout=5)
        expected = subprocess.run([sys.executable, "-c", source], text=True, capture_output=True, timeout=5)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertEqual(actual.returncode, expected.returncode)
        self.assertEqual(re.findall(r"line (\d+), in ([^\n]+)", actual.stderr),
                         re.findall(r"line (\d+), in ([^\n]+)", expected.stderr))
        self.assertEqual(actual.stderr.splitlines()[-1], expected.stderr.splitlines()[-1])

    def test_native_scalar_helpers_match_in_debug_and_release(self):
        from pathlib import Path
        import subprocess
        import sys
        for bits in (64, 128):
            source = f'''
a = -{2**(bits-1)}
b = {2**(bits-1)-1}
print(a / -1, b / 3, a / b)
print(1288281069789064.25, 0.7 // 0.1, -0.0 % -3.0)
print(a == float(a), b < -float(a), "海🐈"[-1])
'''
            rust = try_generate_native(source, "native_input.py", f"i{bits}",string_mode=self.string_mode)
            self.assertIsNotNone(rust)
            path = Path(self.tmp.name) / f"scalar_debug_{bits}.rs"
            path.write_text(rust)
            expected = subprocess.run([sys.executable, "-c", source], text=True, capture_output=True, timeout=5)
            for flags in ([], ["-O"]):
                binary = path.with_suffix("")
                compiled = subprocess.run(["rustc", "--edition=2021", *flags, str(path), "-o", str(binary)],
                                          text=True, capture_output=True)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                actual = subprocess.run([str(binary)], text=True, capture_output=True, timeout=5)
                self.assertEqual((actual.stdout, actual.returncode), (expected.stdout, expected.returncode), actual.stderr)


# Harness inheritance is for methods only, not inherited test discovery.
for _name in dir(NativeTests):
    if _name.startswith("test_") and _name not in NativeTextFloatTests.__dict__:
        setattr(NativeTextFloatTests, _name, None)
del NativeTests
