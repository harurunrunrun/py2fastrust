"""Static callbacks do not require an embedded runtime Python compiler."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.aot import rust_mask
from py2fastrust.compiler import Compiler
from py2fastrust.ir import Instruction
from py2fastrust.reachability import dynamic_compilation_unreachable


class StaticReachabilityTests(unittest.TestCase):
    def proof(self, source):
        source = textwrap.dedent(source)
        return dynamic_compilation_unreachable(source, Compiler().compile(source))

    def test_static_functions_closures_and_comprehensions_are_closed(self):
        for source in (
            "def f(x): return f(x-1) if x else 0\nprint(f(5))",
            "def f(): pass\nprint(f())",
            "f=lambda x:x+1\nprint(f(2))",
            "print([x*x for x in range(5)])",
            "print({x*x for x in range(5)})",
            "print({x:x*x for x in range(5)})",
            "print(tuple(x*x for x in range(5)))",
            "def f():\n yield from range(3)\nprint(list(f()))",
            "def outer(x):\n def inner(y):\n  nonlocal x\n  x+=y\n  return x\n return inner(3)\nprint(outer(2))",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.proof(source))

    def test_reflection_imports_and_dynamic_capabilities_keep_compiler(self):
        for source in (
            "def f(s): return eval(s)\nprint(f('1+2'))",
            "def f(): return globals()['eval']\nprint(f())",
            "def f(): return __builtins__\nprint(f())",
            "def f(): return getattr(str,'upper')\nprint(f())",
            "def f():\n import math\n return math.sqrt(9)\nprint(f())",
            "def f(): return 1\nprint(f.__globals__)",
            "def f(): return 1\nf=compile\nf('1+2','x','eval')",
            "def f(): return 1\nf=__import__\nf('builtins')",
            "def f(): return 1\nf=breakpoint\nf()",
            "def f(): return 1\nf=type\nf('X',(),{})",
            "def f(): return 1\nf=open\nf('source.py')",
            "def f(): return 1\nf=__build_class__\nf(f,'X')",
            "def f(): return 1\nprint([f][0]())",
            "def f(): return 1\nprint(sorted([1],key=f))",
            "def f(): return 1\nclass C: pass",
        ):
            with self.subTest(source=source):
                self.assertFalse(self.proof(source))

    def test_lowered_helper_changes_invalidate_the_proof(self):
        source = "def f(): return 1\nprint(f())\n"
        for operation in (
            Instruction("Load", ("eval",)),
            Instruction("Load", ("type",)),
            Instruction("GetAttr", ("__globals__",)),
            Instruction("SetAttr", ("__globals__",)),
            Instruction("Import", ("builtins", [], 0)),
            Instruction("FutureUnknownOperation"),
        ):
            with self.subTest(operation=operation.op):
                program = Compiler().compile(source)
                program.codes[1].ops.insert(0, operation)
                self.assertFalse(dynamic_compilation_unreachable(source, program))


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ClosedStaticExecutionTests(unittest.TestCase):
    def compare(self, source, integer="i64", optimize=False):
        source = textwrap.dedent(source)
        result = transpile(source, TranspileOptions(integer=integer, optimize=optimize))
        self.assertTrue(result.success, result.diagnostics)
        masked = rust_mask(result.rust_source)
        self.assertIsNone(re.search(r"\bOp\b|\bInstr\b|\.ops\b|\bfn\s+step\b", masked))
        self.assertNotIn("struct PegParser", masked)
        with tempfile.TemporaryDirectory(prefix="pytors-closed-static-") as directory:
            root = Path(directory)
            (root / "main.rs").write_text(result.rust_source, encoding="utf-8")
            compiled = subprocess.run(["rustc", "--edition=2021", str(root / "main.rs"), "-o", str(root / "main")],
                                      capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            expected = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True, text=True, timeout=20)
            actual = subprocess.run([str(root / "main")], capture_output=True, text=True, timeout=20)
            self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
            self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_recursive_and_nonlocal_calls_all_integer_modes(self):
        source = '''
            def recurse(n):
                return recurse(n-1)+1 if n else 0
            def outer(x):
                def inner(y=2):
                    nonlocal x
                    x += y
                    return x
                return inner(3)+inner()
            print(recurse(350),outer(4))
        '''
        for integer in ("i64", "i128", "bigint"):
            with self.subTest(integer=integer):
                self.compare(source, integer)

    def test_comprehensions_and_generator_resumption(self):
        self.compare('''
            def values():
                yield 5
                yield from range(3)
                yield 7
            print(list(values()))
            print([str(x) for x in range(4)])
            print({x:x*x for x in range(4)})
            print(tuple(x*x for x in range(4)))
        ''', optimize=True)

    def test_annotations_defaults_and_decorators_stay_static(self):
        self.compare('''
            def decorate(fn):
                return fn
            @decorate
            def combine(left: int, right: int=3) -> int:
                return left+right
            print(combine(5),combine(5,7))
        ''')
