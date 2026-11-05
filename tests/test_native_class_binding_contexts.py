"""Actual defining-class contexts preserve linked-module generations and calls."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_class_binding_contexts as contexts

CASES = {'linked_factory_forward': [{'main.py': 'import sys\n'
                                        'from weights import Weight\n'
                                        'def main():\n'
                                        ' left=Weight(10)\n'
                                        ' right=Weight(4)\n'
                                        ' '
                                        'print(left.boosted(int(sys.stdin.readline())).level,(left-right).level,(left-3).level)\n'
                                        'main()\n',
                             'weights.py': 'class Weight:\n'
                                           ' def '
                                           '__init__(self,level):self.level=level\n'
                                           ' def boosted(self,delta):\n'
                                           '  if '
                                           'isinstance(self,Weight):return '
                                           'build_weight(self.level+delta)\n'
                                           '  return Weight(-999)\n'
                                           ' def __sub__(self,other):\n'
                                           '  if '
                                           'isinstance(other,Weight):return '
                                           'build_weight(self.level-other.level)\n'
                                           '  return '
                                           'build_weight(self.level-other)\n'
                                           'def build_weight(level):\n'
                                           ' result=Weight(0)\n'
                                           ' result.level=level\n'
                                           ' return result\n'},
                            ['5\n']],
 'linked_factory_external_entry': [{'main.py': 'import sys\n'
                                               'from weights import '
                                               'Weight,build_weight\n'
                                               'first=build_weight(2)\n'
                                               'def main():\n'
                                               ' left=Weight(10)\n'
                                               ' right=Weight(4)\n'
                                               ' '
                                               'print(first.level,left.boosted(int(sys.stdin.readline())).level,(left-right).level,(left-3).level)\n'
                                               'main()\n',
                                    'weights.py': 'class Weight:\n'
                                                  ' def '
                                                  '__init__(self,level):self.level=level\n'
                                                  ' def boosted(self,delta):\n'
                                                  '  if '
                                                  'isinstance(self,Weight):return '
                                                  'build_weight(self.level+delta)\n'
                                                  '  return Weight(-999)\n'
                                                  ' def __sub__(self,other):\n'
                                                  '  if '
                                                  'isinstance(other,Weight):return '
                                                  'build_weight(self.level-other.level)\n'
                                                  '  return '
                                                  'build_weight(self.level-other)\n'
                                                  'def build_weight(level):\n'
                                                  ' result=Weight(0)\n'
                                                  ' result.level=level\n'
                                                  ' return result\n'},
                                   ['5\n']],
 'linked_unused_receiver_factory': [{'main.py': 'import sys\n'
                                                'from storage import Box\n'
                                                'def main():\n'
                                                ' data=Box(2)\n'
                                                ' '
                                                'print(data.fresh(int(sys.stdin.readline())).value)\n'
                                                'main()\n',
                                     'storage.py': 'class Box:\n'
                                                   ' def '
                                                   '__init__(self,value):self.value=value\n'
                                                   ' def '
                                                   'fresh(self,value):return '
                                                   'Box(value)\n'},
                                    ['7\n']],
 'same_source_old_function_via_mutable_builtin_fallback': [{'main.py': 'import '
                                                                       'state\n'
                                                                       'class '
                                                                       'Suppress:\n'
                                                                       ' def '
                                                                       '__enter__(self):return '
                                                                       'self\n'
                                                                       ' def '
                                                                       '__exit__(self,kind,error,trace):return '
                                                                       'True\n'
                                                                       'with '
                                                                       'Suppress():import '
                                                                       'worker\n'
                                                                       'with '
                                                                       'Suppress():import '
                                                                       'worker\n'
                                                                       'print("attempts",state.attempt)\n',
                                                            'state.py': 'saved=[]\n'
                                                                        'attempt=0\n',
                                                            'worker.py': 'import '
                                                                         'state\n'
                                                                         'import '
                                                                         'builtins\n'
                                                                         'state.attempt+=1\n'
                                                                         'tag=state.attempt*10\n'
                                                                         'class '
                                                                         'C:\n'
                                                                         ' def '
                                                                         '__init__(self,value):self.value=value\n'
                                                                         ' def '
                                                                         'run(self,value):return '
                                                                         'abs(value)+C(0).value\n'
                                                                         'if '
                                                                         'state.attempt==2:\n'
                                                                         ' '
                                                                         'previous_abs=builtins.abs\n'
                                                                         ' '
                                                                         'builtins.abs=state.saved[0]\n'
                                                                         ' '
                                                                         'print("fallback",C(0).run(5))\n'
                                                                         ' '
                                                                         'builtins.abs=previous_abs\n'
                                                                         'def '
                                                                         'abs(value):return '
                                                                         'C(0).value+tag+value\n'
                                                                         'state.saved.append(abs)\n'
                                                                         'if '
                                                                         'state.attempt==1:raise '
                                                                         'ValueError("retry")\n'},
                                                           ['']],
 'saved_class_after_module_alias_store': [{'main.py': 'import sys\n'
                                                      'import storage\n'
                                                      'from storage import '
                                                      'Number as Saved\n'
                                                      'storage.Number=0\n'
                                                      'def main():\n'
                                                      ' '
                                                      'created=Saved(int(sys.stdin.readline()))\n'
                                                      ' print(created.value)\n'
                                                      'main()\n',
                                           'storage.py': 'class Number:\n'
                                                         ' def '
                                                         '__init__(self,value):self.value=value\n'},
                                          ['7\n']],
 'linked_error_order': [{'main.py': 'from storage import Box\n'
                                    '\n'
                                    'def main():\n'
                                    '    value = Box(12)\n'
                                    '    '
                                    'print(value.divided(int(input())).value)\n'
                                    '\n'
                                    'main()\n',
                         'storage.py': 'class Box:\n'
                                       '    def __init__(self, value):\n'
                                       '        self.value = value\n'
                                       '    def divided(self, divisor):\n'
                                       '        print("body", divisor)\n'
                                       '        return Box(self.value // '
                                       'divisor)\n'},
                        ['3\n', '0\n', 'bad\n']],
 'linked_retained_bound_method': [{'main.py': 'from storage import Box\n'
                                              '\n'
                                              'def main():\n'
                                              '    value = Box(int(input()))\n'
                                              '    saved = value.shifted\n'
                                              '    '
                                              'print(value.shifted(2).value, '
                                              'saved(5).value)\n'
                                              '\n'
                                              'main()\n',
                                   'storage.py': 'class Box:\n'
                                                 '    def __init__(self, '
                                                 'value):\n'
                                                 '        self.value = value\n'
                                                 '    def shifted(self, '
                                                 'delta):\n'
                                                 '        return '
                                                 'Box(self.value + delta)\n'},
                                  ['7\n']]}


def convert_project(files, integer="i64"):
    """Observe the original-model certificate before generated Rust exists."""
    directory = tempfile.TemporaryDirectory(prefix="pytors-class-context-proof-")
    root = Path(directory.name)
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    observed = []
    original = contexts.prepare
    def observe(model):
        original(model)
        registry = model.class_binding_contexts
        observed.append({
            "barrier": registry.barrier,
            "bindings": {binding.owner.node.name for binding in registry.bindings.values()},
            "methods": {plan.node.name: plan.index for plan in model.plans
                        if plan.reachable and registry.source(plan).index in registry.methods},
            "functions": {plan.node.name for plan in model.plans
                          if plan.reachable and registry.source(plan).index in registry.functions},
        })
    with patch.object(contexts, "prepare", side_effect=observe):
        result = transpile(files["main.py"], TranspileOptions(
            filename=str(root / "main.py"), integer=integer, license="none"))
    directory.cleanup()
    return result, observed


class ClassBindingContextProofs(unittest.TestCase):
    def check(self, name, integer="i64"):
        result, facts = convert_project(CASES[name][0], integer)
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(facts)
        return result, facts[-1]

    def test_bound_operators_and_closed_factory_forward_actual_context(self):
        for integer in ("i64", "i128"):
            with self.subTest(integer=integer):
                result, facts = self.check("linked_factory_forward", integer)
                self.assertIn("Weight", facts["bindings"])
                self.assertTrue({"boosted", "__sub__"} <= facts["methods"].keys())
                self.assertIn("build_weight", facts["functions"])
                self.assertIn("class_defining_class:&ClassClassRef", result.rust_source)

    def test_external_factory_entry_keeps_its_actual_function_context(self):
        _, facts = self.check("linked_factory_external_entry")
        self.assertNotIn("build_weight", facts["functions"])

    def test_by_value_unused_receiver_has_independent_metadata_snapshot(self):
        result, facts = self.check("linked_unused_receiver_factory")
        index = facts["methods"]["fresh"]
        header = re.search(r"fn class_function_" + str(index) + r"\([^\n]+", result.rust_source).group()
        self.assertIn("class_defining_class:&ClassClassRef", header)
        self.assertRegex(header, r"class_argument_0:ClassHandle_\d+")
        self.assertRegex(result.rust_source, r"&<ClassValueMetadata_\d+ as Clone>::clone\(")

    def test_mutable_builtins_cannot_forward_another_import_generation(self):
        _, facts = self.check("same_source_old_function_via_mutable_builtin_fallback")
        self.assertIn("builtin namespace", facts["barrier"])
        self.assertFalse(facts["bindings"])
        self.assertFalse(facts["methods"])
        self.assertFalse(facts["functions"])

    def test_module_alias_class_store_keeps_original_binding_lookup(self):
        _, facts = self.check("saved_class_after_module_alias_store")
        self.assertFalse(facts["bindings"])

    def test_retained_bound_method_keeps_its_captured_entry(self):
        _, facts = self.check("linked_retained_bound_method")
        self.assertNotIn("shifted", facts["methods"])

    def test_selected_method_error_path_keeps_source_body(self):
        result, facts = self.check("linked_error_order")
        self.assertIn("divided", facts["methods"])
        self.assertIn("class_defining_class:&ClassClassRef", result.rust_source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ClassBindingContextExecution(unittest.TestCase):
    def exercise(self, name):
        files, inputs = CASES[name]
        with tempfile.TemporaryDirectory(prefix="pytors-class-context-runtime-") as directory:
            root = Path(directory)
            for filename, source in files.items():
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
            main = root / "main.py"
            references = [subprocess.run([sys.executable, "-S", str(main)], input=data,
                          text=True, capture_output=True, timeout=15) for data in inputs]
            frames = lambda error: re.findall(r'File "([^"\n]+)", line (\d+), in ([^\n]+)', error)
            for integer in ("i64", "i128", "bigint"):
                result = transpile(files["main.py"], TranspileOptions(
                    filename=str(main), integer=integer, license="none"))
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.backend, "native")
                self.assertLess(len(result.rust_source.encode()), 512 * 1024)
                rust = root / (integer + ".rs")
                rust.write_text(result.rust_source)
                for optimized in (False, True):
                    binary = root / (integer + ("_release" if optimized else "_debug"))
                    built = subprocess.run(["rustc", "--edition=2021", "--crate-name", "class_context",
                            *(["-O"] if optimized else []), str(rust), "-o", str(binary)],
                            text=True, capture_output=True, timeout=180)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    for data, expected in zip(inputs, references):
                        with self.subTest(case=name, integer=integer, optimized=optimized, input=data):
                            actual = subprocess.run([str(binary)], input=data, text=True,
                                    capture_output=True, timeout=15,
                                    env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                            self.assertEqual(actual.stdout, expected.stdout)
                            self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                            self.assertEqual(frames(actual.stderr), frames(expected.stderr))
                            self.assertEqual(actual.stderr.splitlines()[-1:], expected.stderr.splitlines()[-1:])

    def test_bound_operators_and_same_module_factory(self):
        self.exercise("linked_factory_forward")

    def test_external_factory_entry(self):
        self.exercise("linked_factory_external_entry")

    def test_owned_receiver_snapshot(self):
        self.exercise("linked_unused_receiver_factory")

    def test_failed_import_mutable_builtin_generation(self):
        self.exercise("same_source_old_function_via_mutable_builtin_fallback")

    def test_saved_class_module_alias_mutation(self):
        self.exercise("saved_class_after_module_alias_store")

    def test_retained_bound_method(self):
        self.exercise("linked_retained_bound_method")

    def test_method_body_and_argument_errors(self):
        self.exercise("linked_error_order")


if __name__ == "__main__":
    unittest.main()
