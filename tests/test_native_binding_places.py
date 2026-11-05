"""Checked source-binding presence is distinct from owned callable transport."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_binding_places as places
from py2fastrust.native_global_callable_payload import read as owned_read

ARITHMETIC = {'main.py': 'import library\n'
            'result=library.Number(5).add(library.Number(2))\n'
            'print(result.value)\n'
            'saved=library.inspect_factory()\n'
            'print(saved is library.factory)\n',
 'library.py': 'class Number:\n'
               '    def __init__(self,value): self.value=value\n'
               '    def add(self,other):\n'
               '        assert isinstance(other,Number)\n'
               '        return factory(argument(self.value+other.value))\n'
               'def argument(value):\n'
               '    print("argument")\n'
               '    return value\n'
               'if int(input())==0:\n'
               '    print("before")\n'
               '    Number(1).add(Number(2))\n'
               'def factory(value): return Number(value)\n'
               'def inspect_factory(): return factory\n'}

ORIGINALS = {'early_callee_precedes_arguments': {'main.py': 'import support\n'
                                                'def argument():\n'
                                                '    print("argument")\n'
                                                '    return 4\n'
                                                'print(Later(argument()))\n'
                                                'class Later:\n'
                                                '    def __init__(self,value): '
                                                'self.value=value\n',
                                     'support.py': ''},
 'late_function_presence': {'main.py': 'import support\n'
                                       'def forward(value):\n'
                                       '    return later(value)\n'
                                       'print("before")\n'
                                       'print(forward(4))\n'
                                       'def later(value):\n'
                                       '    return value+9\n',
                            'support.py': ''},
 'module_alias_replaces_class_binding': {'main.py': 'import library as alias\n'
                                                    'old=alias.Parcel\n'
                                                    'alias.Parcel=alias.Other\n'
                                                    'print(old(3).value,alias.make(4).value)\n',
                                         'library.py': 'class Parcel:\n'
                                                       '    def __init__(self,value): '
                                                       'self.value=value\n'
                                                       'class Other:\n'
                                                       '    def __init__(self,value): '
                                                       'self.value=100+value\n'
                                                       'def make(value): return '
                                                       'Parcel(value)\n'},
 'failed_generation_late_function_absent': {'main.py': 'import state\n'
                                                       'def load(value):\n'
                                                       '    import worker\n'
                                                       '    return value\n'
                                                       'print(list(map(load,[0])))\n'
                                                       'import worker\n'
                                                       'old,current=state.saved\n'
                                                       'print(current().read(2))\n'
                                                       'print(old().read(3))\n',
                                            'state.py': 'attempts=0\n'
                                                        'saved=[]\n'
                                                        'def keep(value): '
                                                        'saved.append(value)\n',
                                            'worker.py': 'import state\n'
                                                         'state.attempts+=1\n'
                                                         'seed=10*state.attempts\n'
                                                         'class Reader:\n'
                                                         '    def read(self,value): return '
                                                         'finish(value)\n'
                                                         'state.keep(Reader)\n'
                                                         'if state.attempts==1:\n'
                                                         '    next(iter([]))\n'
                                                         'def finish(value): return '
                                                         'seed+value\n'},
 'actual_defaults_and_function_alias': {'main.py': 'import library\n'
                                                   'saved=library.combine\n'
                                                   'library.seed=40\n'
                                                   'print(saved(),library.combine(3),saved '
                                                   'is library.combine)\n',
                                        'library.py': 'seed=6\n'
                                                      'def default():\n'
                                                      '    print("default")\n'
                                                      '    return seed+1\n'
                                                      'def combine(value=default()):\n'
                                                      '    return seed+value\n'},
 'argument_rebinds_immutable_candidate': {'main.py': 'import library\n'
                                                     'def change():\n'
                                                     '    print("argument")\n'
                                                     '    library.combine=library.other\n'
                                                     '    return 2\n'
                                                     'print(library.combine(change()),library.combine(3))\n',
                                          'library.py': 'seed=10\n'
                                                        'def combine(value): return '
                                                        'seed+value\n'
                                                        'def other(value): return '
                                                        '100+value\n'},
 'builtin_fallback_keeps_failed_function_generation': {'main.py': 'import state\n'
                                                                  'def load(value):\n'
                                                                  '    import worker\n'
                                                                  '    return value\n'
                                                                  'print(list(map(load,[0])))\n'
                                                                  'import worker\n'
                                                                  'first,second=state.saved\n'
                                                                  'print(first(2),second(2))\n',
                                                       'state.py': 'attempts=0\n'
                                                                   'saved=[]\n'
                                                                   'def keep(value): '
                                                                   'saved.append(value)\n',
                                                       'worker.py': 'import builtins\n'
                                                                    'import state\n'
                                                                    'state.attempts+=1\n'
                                                                    'prefix="old:" if '
                                                                    'state.attempts==1 '
                                                                    'else "new:"\n'
                                                                    'def invoke(value): '
                                                                    'return oct(value)\n'
                                                                    'if '
                                                                    'state.attempts==2:\n'
                                                                    '    '
                                                                    'print("fallback",invoke(1))\n'
                                                                    'def oct(value): '
                                                                    'return '
                                                                    'prefix+str(value)\n'
                                                                    'state.keep(oct)\n'
                                                                    'if '
                                                                    'state.attempts==1:\n'
                                                                    '    builtins.oct=oct\n'
                                                                    '    next(iter([]))\n'},
 'circular_publication_missing_export': {'main.py': 'import left\n',
                                         'left.py': 'import right\n'
                                                    'class Published:\n'
                                                    '    value=7\n',
                                         'right.py': 'import left\n'
                                                     'print("before")\n'
                                                     'print(left.Published)\n'},
 'valid_external_caller_retains_payload': {'main.py': 'import library\n'
                                                      'print(library.Number(5).add(2).value,library.ordinary().value)\n',
                                           'library.py': 'class Number:\n'
                                                         '    def __init__(self,value): '
                                                         'self.value=value\n'
                                                         '    def add(self,value): return '
                                                         'build(self.value+value)\n'
                                                         'def build(value): return '
                                                         'Number(value)\n'
                                                         'def ordinary(): return '
                                                         'build(4)\n'},
 'mixed_eligible_and_binding_error': {'main.py': 'import library\n'
                                                 'print(library.Number(5).add(2).value)\n'
                                                 'library.ordinary()\n',
                                      'library.py': 'class Number:\n'
                                                    '    def __init__(self,value): '
                                                    'self.value=value\n'
                                                    '    def add(self,value): return '
                                                    'build(self.value+value)\n'
                                                    'def build(value): return '
                                                    'Number(value)\n'
                                                    'def ordinary(): return build()\n'},
 'callee_presence_before_argument': {'main.py': 'import library\n',
                                     'library.py': 'class Number:\n'
                                                   '    def __init__(self,value): '
                                                   'self.value=value\n'
                                                   '    def add(self,value): return '
                                                   'build(argument(value))\n'
                                                   'def argument(value):\n'
                                                   '    print("argument")\n'
                                                   '    return value\n'
                                                   'print("before")\n'
                                                   'print(Number(5).add(2).value)\n'
                                                   'def build(value): return '
                                                   'Number(value)\n'}}


def compile_project(files, integer="i64", *, disabled=False, register_owned=False):
    observed = []
    original = places.capture
    def capture(emitter, node, request):
        result = original(emitter, node, request)
        if result is not None:
            access = result[1].plan
            target = emitter.model.callable_cells.plans[request.layout.definition]
            from py2fastrust.native_call_context_effects import source_plan
            target = source_plan(target)
            unit = emitter.model.unit.original_unit(target.node)
            observed.append({
                "place": access.place, "key": access.key,
                "private": isinstance(result[1], places.CapturedBinding),
                "expected_event": (unit.name, unit.ordinal(target.node)),
                "model": emitter.model,
            })
            if register_owned:
                # Exercise both accessor contracts on the same actual source
                # binding; this does not claim a second source call is selected.
                with patch.object(emitter, "global_callable_request", request):
                    owned_read(emitter, request.node, emitter.kind(request.node))
        return result
    with tempfile.TemporaryDirectory(prefix="pytors-binding-place-") as directory:
        root = Path(directory)
        for name, source in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        with patch.object(places, "capture", return_value=None) if disabled else patch.object(places, "capture", side_effect=capture):
            result = transpile(files["main.py"], TranspileOptions(
                filename=str(root / "main.py"), integer=integer, license="none"))
    return result, observed


class BindingPlaceProofs(unittest.TestCase):
    def test_checked_presence_changes_only_the_private_call_capture(self):
        for integer in ("i64", "i128"):
            with self.subTest(integer=integer):
                result, observed = compile_project(ARITHMETIC, integer)
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(observed)
                self.assertTrue(all(row["private"] for row in observed))
                self.assertTrue(all(row["place"].definition_event == row["expected_event"] for row in observed))
                source = result.rust_source
                for row in observed:
                    place = row["place"]
                    header = f"fn class_binding_present_{place.slot}_{place.definition}"
                    helper = next(line for line in source.splitlines() if line.startswith(header))
                    self.assertIn("Result<(),String>", helper)
                    self.assertIn(f"value_{place.slot}.as_ref()", helper)
                    self.assertNotIn(".clone()", helper)
                    self.assertIn("NameError: name 'factory' is not defined", helper)
                # Saved aliases keep the full payload and actual module. Only
                # the private immediate invocation uses a presence token.
                self.assertRegex(source, r"fn class_global_get_\d+\(scope:&ClassScope\)->Result<ClassCallablePayload_F\d+,String>")
                self.assertIn("class_same_identity", source)
                self.assertIn("struct ClassGlobals{", source)

    def test_read_owned_and_check_presence_use_separate_actual_registry_entries(self):
        result, observed = compile_project(ARITHMETIC, register_owned=True)
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(observed)
        from py2fastrust.native_global_callable_payload import runtime
        for row in observed:
            model, place = row["model"], row["place"]
            self.assertIn(("check_presence", place.slot, place.definition), model.binding_place_accessors)
            self.assertIn((place.slot, place.definition), model.global_callable_payload_accessors)
            declarations = runtime(model)
            self.assertIn(f"fn class_binding_present_{place.slot}_{place.definition}(scope:&ClassScope)->Result<(),String>", declarations)
            self.assertIn(f"fn class_global_payload_{place.slot}_{place.definition}(scope:&ClassScope)->Result<ClassModuleRef,String>", declarations)

    def test_valid_external_entry_keeps_the_original_payload_path(self):
        files = ORIGINALS["valid_external_caller_retains_payload"]
        for integer in ("i64", "i128", "bigint"):
            with self.subTest(integer=integer):
                result, observed = compile_project(files, integer)
                self.assertTrue(result.success, result.diagnostics)
                self.assertFalse(observed)
                self.assertNotIn("fn class_binding_present_", result.rust_source)

    def test_original_generation_default_rebinding_and_circular_controls_keep_their_code(self):
        for name, files in ORIGINALS.items():
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(name=name, integer=integer):
                    # Keep the filename identical in both compilations, since
                    # source path is part of Python's visible trace metadata.
                    with tempfile.TemporaryDirectory(prefix="pytors-binding-barrier-") as directory:
                        root = Path(directory)
                        for filename, source in files.items():
                            target = root / filename
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(source)
                        options = TranspileOptions(filename=str(root / "main.py"), integer=integer, license="none")
                        result = transpile(files["main.py"], options)
                        with patch.object(places, "capture", return_value=None):
                            baseline = transpile(files["main.py"], options)
                    self.assertEqual(result.success, baseline.success)
                    self.assertEqual(result.diagnostics, baseline.diagnostics)
                    self.assertEqual(result.rust_source, baseline.rust_source)

    def test_standalone_source_uses_official_plan_definition_events(self):
        files = {"main.py": "class Number:\n def __init__(self,value):self.value=value\n def add(self,other):\n  assert isinstance(other,Number)\n  return factory(self.value+other.value)\ndef factory(value):return Number(value)\nprint(Number(2).add(Number(3)).value)\n"}
        result, observed = compile_project(files)
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(observed)
        self.assertTrue(all(row["place"].definition_event == row["expected_event"] for row in observed))
        # The public converter may retain even one module as a LinkedUnit.
        # The raw frontend SourceUnit has no definition_key method; actual
        # native plans already own that qualified original event in both cases.
        from py2fastrust.frontend import build_program
        from py2fastrust.native_classes import Model
        unit = build_program(files["main.py"], "main.py").main
        self.assertFalse(hasattr(unit, "definition_key"))
        model = Model(unit.tree, unit.filename, "i64", unit.native_imports, unit=unit)
        for plan in model.plans:
            self.assertEqual(plan.definition_key, (unit.name, unit.ordinal(plan.node)))


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class BindingPlaceExecution(unittest.TestCase):
    def test_actual_presence_alias_identity_and_argument_order_all_modes(self):
        with tempfile.TemporaryDirectory(prefix="pytors-binding-place-run-") as directory:
            root = Path(directory)
            for name, source in ARITHMETIC.items():
                (root / name).write_text(source)
            main = root / "main.py"
            inputs = ("1\n", "0\n")
            expected = [subprocess.run([sys.executable, "-S", str(main)], input=data,
                        capture_output=True, text=True, timeout=15) for data in inputs]
            self.assertEqual(expected[0].stdout, "argument\n7\nTrue\n")
            self.assertEqual(expected[1].stdout, "before\n")
            frames = lambda text: re.findall(r'File "([^"\n]+)", line (\d+), in ([^\n]+)', text)
            for integer in ("i64", "i128", "bigint"):
                result = transpile(main.read_text(), TranspileOptions(
                    filename=str(main), integer=integer, license="none"))
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.backend, "native")
                self.assertEqual("fn class_binding_present_" in result.rust_source, integer != "bigint")
                source = root / (integer + ".rs")
                source.write_text(result.rust_source)
                for optimized in (False, True):
                    binary = root / (integer + ("_release" if optimized else "_debug"))
                    build = subprocess.run(["rustc", "--edition=2021", "--crate-name", "binding_place_tests",
                            *(["-O"] if optimized else []), str(source), "-o", str(binary)],
                            text=True, capture_output=True, timeout=180)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    for data, reference in zip(inputs, expected):
                        with self.subTest(integer=integer, optimized=optimized, input=data):
                            actual = subprocess.run([str(binary)], input=data, text=True,
                                capture_output=True, timeout=15,
                                env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                            self.assertEqual(actual.stdout, reference.stdout)
                            self.assertEqual(actual.returncode, reference.returncode, actual.stderr)
                            self.assertEqual(frames(actual.stderr), frames(reference.stderr))
                            self.assertEqual(actual.stderr.splitlines()[-1:], reference.stderr.splitlines()[-1:])


if __name__ == "__main__":
    unittest.main()
