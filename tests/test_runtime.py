"""End-to-end differential tests: generated Rust versus CPython 3.14."""

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class RuntimeTests(unittest.TestCase):
    def run_source(self, source, stdin="", integer="i64", argv=()):
        source = textwrap.dedent(source)
        with tempfile.TemporaryDirectory(prefix="py2fastrust-test-") as directory:
            root = Path(directory)
            options = TranspileOptions(integer=integer, filename="case.py", optimize=False)
            result = transpile(source, options)
            self.assertTrue(result.success, "\n".join(map(str, result.diagnostics)))
            target = root / "main.rs"
            target.write_text(result.rust_source, encoding="utf-8")
            compiled = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(root / "main")],
                                      capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            text_mode = isinstance(stdin, str)
            actual = subprocess.run([str(root / "main"), *argv], input=stdin,
                                    capture_output=True, text=text_mode, timeout=15)
            expected = subprocess.run([sys.executable, "-I", "-c", source, *argv], input=stdin,
                                      capture_output=True, text=text_mode, timeout=15)
            actual_error = actual.stderr if text_mode else actual.stderr.decode("utf-8", errors="replace")
            expected_error = expected.stderr if text_mode else expected.stderr.decode("utf-8", errors="replace")
            self.assertEqual(actual.returncode, expected.returncode, actual_error + "\n" + expected_error)
            self.assertEqual(actual.stdout, expected.stdout, actual_error)
            if expected.returncode:
                if expected_error.strip():
                    self.assertTrue(actual_error.strip(), "expected an exception diagnostic")
                    self.assertEqual(actual_error.strip().splitlines()[-1].split(":")[0],
                                     expected_error.strip().splitlines()[-1].split(":")[0])
                else:
                    self.assertEqual(actual_error, expected_error)
            return actual

    def test_scalars_rebinding_and_short_circuit(self):
        self.run_source('''
            x = 1
            x = "hello"
            print(x, 0 or "fallback", [] and 3, not "")
            print(-7 // 3, -7 % 3, 7 // -3, 7 % -3)
            print(1 < 2 < 3, 1 < 0 < int("invalid"))
        ''')

    def test_shared_mutation_slicing_and_unpacking(self):
        self.run_source('''
            a = [1, 2]
            b = a
            a += [3]
            a.append(a.pop())
            print(a, b, a is b)
            a = a + [4]
            print(a, b, a is b)
            first, *middle, last = range(5)
            print(first, middle, last, a[::-1])
            d = {"a": 1, "b": 2}
            d["a"] += 3
            print(d, list(d))
        ''')

    def test_loops_else_and_variable_lifetime(self):
        self.run_source('''
            x = "initial"
            for i in range(0):
                x = i
            print(x)
            for i in range(5):
                if i == 1:
                    continue
                if i == 3:
                    break
                print(i)
            else:
                print("unexpected")
            print(i)
            for i in range(2):
                i = "changed"
            print(i)
            for i in range(0):
                pass
            else:
                print("empty")
        ''')

    def test_comprehensions_and_generators(self):
        self.run_source('''
            def make(n):
                return [i*j for i in range(n) for j in range(3) if j != 1]
            print(make(3))
            print({str(i): i*i for i in range(3)})
            print(sorted({i % 3 for i in range(10)}))
            def gen():
                yield 2
                yield 4
            print(list(gen()))
            print(sum(i*i for i in range(5)))
        ''')

    def test_input_lines_unicode_and_formatting(self):
        self.run_source('''
            print(repr(input()), repr(input()), repr(input()))
            print("日本語🙂"[1:], len("日本語🙂"))
            value = 7
            print(f"value={value:04d}", f"{value!r}")
            print(1, 2, sep=":", end="!")
        ''', " first \n\nlast\n")

    def test_bigint_end_to_end(self):
        self.run_source('''
            a = 2 ** 240 + 12345
            b = 2 ** 100 - 1
            print(a * b, divmod(-a, b), a ^ -b)
            print(pow(3, -1, 1000000007))
            print(10 ** 400 / 10 ** 400)
        ''', integer="bigint")

if __name__ == "__main__":
    unittest.main()
