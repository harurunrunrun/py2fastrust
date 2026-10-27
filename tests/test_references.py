"""Call-time references and class alias binding state use shared scope facts."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.references import BuiltinIdentity,UnknownReference,resolve_static_callable
from py2fastrust.call_semantics import normalize_call


def expression(source):return ast.parse(source,mode="eval").body


class CallScopeReferenceTests(unittest.TestCase):
    def test_definition_capture_is_not_resolved_again_in_callers_namespace(self):
        unit=build_program("def f(convert=int):pass\nf()\n").main
        signature=unit.signature_for(unit.tree.body[0])
        slot=signature.defaults[0]
        captured=resolve_static_callable(slot.expression,{"int":BuiltinIdentity("str")})
        later=resolve_static_callable(expression("int"),{"int":7})
        self.assertIsInstance(later,UnknownReference)
        plan=signature.plan(normalize_call(unit.tree.body[1].value))
        value=plan.capture(lambda *args:self.fail("default was evaluated at call time"),defaults={"convert":captured})
        self.assertIs(value["convert"],captured)

    def test_class_builtin_shadowing_is_not_silently_replaced_with_default_operations(self):
        sources=("input=3\nclass C:\n def run(self):return input()\nprint(C().run())\n",
                 "int=3\nclass C:\n def run(self):return int('4')\nprint(C().run())\n",
                 "map=3\nclass C:\n def run(self):return list(map(int,['4']))\nprint(C().run())\n")
        for source in sources:
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code,"E006")
        result=transpile("def int(value):return 9\nclass C:\n def run(self):return int('4')\nprint(C().run())\n")
        self.assertTrue(result.success,result.diagnostics)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ClassReferenceSlotTests(unittest.TestCase):
    def compare(self,source,data="line\n"):
        expected=subprocess.run([sys.executable,"-c",source],input=data,capture_output=True,text=True,timeout=5)
        with tempfile.TemporaryDirectory(prefix="pytors-class-reference-")as directory:
            root=Path(directory)
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode,filename="references.py"))
                self.assertTrue(result.success,result.diagnostics)
                path=root/"program.rs";path.write_text(result.rust_source)
                built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(root/"program")],capture_output=True,text=True,timeout=60)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(root/"program")],input=data,capture_output=True,text=True,timeout=5)
                self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr+expected.stderr)
                if expected.returncode:
                    self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],expected.stderr.splitlines()[-1].split(":")[0])

    def test_conditional_reader_binding_and_builtin_spelling_keep_unbound_local(self):
        for name in ("read","input"):
            for n in (0,1):
                source=f"import sys\nclass C:\n def run(self,n):\n  if n:{name}=sys.stdin.buffer.readline\n  print('ready')\n  print({name}())\nC().run({n})\n"
                with self.subTest(name=name,n=n):self.compare(source)

    def test_zero_trip_reader_alias_raises_before_io_and_retains_valid_later_binding(self):
        for n in (0,1):
            source=f"import sys\nclass C:\n def run(self,n):\n  for _ in range(n):read=sys.stdin.readline\n  print(read())\nC().run({n})\n"
            self.compare(source)

    def test_namespace_receiver_and_alias_copy_are_checked_before_use(self):
        for n in (0,1):
            self.compare(f"import sys\nclass C:\n def run(self,n):\n  if n:stream=sys.stdin\n  print(stream.readline())\nC().run({n})\n")
            self.compare(f"import sys\nclass C:\n def run(self,n):\n  if n:read=sys.stdin.readline\n  alias=read\n  print('after')\nC().run({n})\n")

    def test_zero_trip_module_alias_is_nameerror(self):
        self.compare("import sys\nclass Marker:pass\nfor _ in range(0):read=sys.stdin.readline\nprint(read())\n")

    def test_both_branches_bind_the_same_reader_and_keep_newlines(self):
        for n in (0,1):
            self.compare(f"import sys\nclass C:\n def run(self,n):\n  if n:read=sys.stdin.readline\n  else:read=sys.stdin.readline\n  print(read())\nC().run({n})\n")


class ClassNamespaceProofTests(unittest.TestCase):
    def test_unproved_module_builtin_fallback_and_loop_rebinding_are_not_erased(self):
        sources=("import sys\nclass Marker:pass\nif int(input()):input=sys.stdin.readline\nprint(input())\n",
                 "class C:\n def run(self):return input()\nfor _ in range(2):\n print(C().run())\n input=3\n")
        for source in sources:
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code,"E006")

    def test_import_definition_collisions_require_general_binding_versions(self):
        for source in ("import sys as value\ndef value():return 1\nclass Marker:pass\nprint(value.stdin.readline())\n",
                       "def value():return 1\nimport sys as value\nclass Marker:pass\nprint(value.stdin.readline())\n"):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
