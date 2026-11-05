"""Each FunctionDef event owns its identity/defaults; names store current values."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest as unittest_module
import unittest.mock as mock_module

from py2fastrust import transpile, TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model
from py2fastrust.native_aot_callables import CallableCells

PROJECTS = {'module_alias_versions': {'main.py': 'def calculate(value=3):\n'
                                      '    return value + 10\n'
                                      '\n'
                                      'old = calculate\n'
                                      'def calculate(value=7):\n'
                                      '    return value + 20\n'
                                      '\n'
                                      'print(old(), calculate(), old is calculate, old is old)\n'},
 'definition_default_effects': {'main.py': 'def stamp(label):\n'
                                           '    print(label)\n'
                                           '    return len(label)\n'
                                           '\n'
                                           "def calculate(value=stamp('first')):\n"
                                           '    return value, 10\n'
                                           '\n'
                                           'old = calculate\n'
                                           "def calculate(value=stamp('second')):\n"
                                           '    return value, 20\n'
                                           '\n'
                                           'print(old(), calculate())\n'},
 'mutable_default_aliases': {'main.py': 'items = [2]\n'
                                        'def collect(values=items):\n'
                                        '    values.append(5)\n'
                                        '    return values\n'
                                        '\n'
                                        'old = collect\n'
                                        'items = [7]\n'
                                        'def collect(values=items):\n'
                                        '    values.append(11)\n'
                                        '    return values\n'
                                        '\n'
                                        'print(old(), collect(), old())\n'},
 'recursive_name_uses_current_binding': {'main.py': 'def walk(value):\n'
                                                    '    if value == 0:\n'
                                                    '        return 0\n'
                                                    '    return 7 + walk(value - 1)\n'
                                                    '\n'
                                                    'old = walk\n'
                                                    'def walk(value):\n'
                                                    '    return 100 + value\n'
                                                    '\n'
                                                    'number = int(input())\n'
                                                    'print(old(number), walk(number))\n'},
 'callee_capture_before_rebinding_argument': {'main.py': 'def calculate(value):\n'
                                                         '    return value + 1\n'
                                                         '\n'
                                                         'old = calculate\n'
                                                         'def replacement(value):\n'
                                                         '    return value + 100\n'
                                                         '\n'
                                                         'def change():\n'
                                                         '    global calculate\n'
                                                         '    calculate = replacement\n'
                                                         "    print('argument')\n"
                                                         '    return 5\n'
                                                         '\n'
                                                         'def calculate(value):\n'
                                                         '    return value + 10\n'
                                                         '\n'
                                                         'print(calculate(change()), calculate(1), '
                                                         'old(1))\n'},
 'unpublished_binding_precedes_argument': {'main.py': 'def argument():\n'
                                                      "    print('argument must not run')\n"
                                                      '    return 5\n'
                                                      '\n'
                                                      'def enter():\n'
                                                      '    return versioned_target(argument())\n'
                                                      '\n'
                                                      'print(enter())\n'
                                                      'def versioned_target(value):\n'
                                                      '    return value + 1\n'
                                                      '\n'
                                                      'def versioned_target(value):\n'
                                                      '    return value + 2\n'},
 'default_reads_previous_definition': {'main.py': 'def combine(value=1):\n'
                                                  '    return value + 2\n'
                                                  '\n'
                                                  'old = combine\n'
                                                  'def combine(value=combine()):\n'
                                                  '    return value * 3\n'
                                                  '\n'
                                                  'print(old(), combine())\n'},
 'different_signatures_and_binding_errors': {'main.py': 'def combine(first, second=2):\n'
                                                        '    return first + second\n'
                                                        '\n'
                                                        'old = combine\n'
                                                        'def combine(first=9):\n'
                                                        '    return first * 2\n'
                                                        '\n'
                                                        'def mark(value):\n'
                                                        "    print('argument', value)\n"
                                                        '    return value\n'
                                                        '\n'
                                                        'if int(input()) == 0:\n'
                                                        '    print(old(3), combine())\n'
                                                        'else:\n'
                                                        '    print(combine(mark(4), mark(5)))\n'},
 'branch_definition_versions': {'main.py': 'if int(input()):\n'
                                           '    def choose(value=2):\n'
                                           '        return value + 1\n'
                                           'else:\n'
                                           '    def choose(value=4):\n'
                                           '        return value + 10\n'
                                           '\n'
                                           'old = choose\n'
                                           'def choose(value=8):\n'
                                           '    return value + 100\n'
                                           '\n'
                                           'print(old(), choose())\n'},
 'loop_definition_default_instances': {'main.py': 'functions = []\n'
                                                  'for value in range(3):\n'
                                                  '    def calculate(number=value):\n'
                                                  '        return number\n'
                                                  '    functions.append(calculate)\n'
                                                  '\n'
                                                  'def calculate(number=9):\n'
                                                  '    return number + 20\n'
                                                  '\n'
                                                  'print(functions[0](), functions[1](), functions[2](), '
                                                  'calculate())\n'
                                                  'print(functions[0] is functions[1])\n'},
 'local_versions_and_default_captures': {'main.py': 'def factory(seed):\n'
                                                    '    def calculate(value=seed):\n'
                                                    '        return value + 1\n'
                                                    '    old = calculate\n'
                                                    '    def calculate(value=seed + 10):\n'
                                                    '        return value + 2\n'
                                                    '    return old, calculate\n'
                                                    '\n'
                                                    'first, second = factory(2)\n'
                                                    'third, fourth = factory(5)\n'
                                                    'print(first(), second(), third(), fourth(), first is '
                                                    'second)\n'},
 'nonlocal_definition_rebind': {'main.py': 'def factory(seed):\n'
                                           '    def calculate(value=seed):\n'
                                           '        return value + 1\n'
                                           '    old = calculate\n'
                                           '    def replace():\n'
                                           '        nonlocal calculate\n'
                                           '        def calculate(value=seed + 3):\n'
                                           '            return value + 10\n'
                                           '    replace()\n'
                                           '    return old, calculate\n'
                                           '\n'
                                           'first, second = factory(4)\n'
                                           'print(first(), second(), first is second)\n'},
 'global_definition_inside_function': {'main.py': 'def calculate(value=1):\n'
                                                  '    return value + 1\n'
                                                  '\n'
                                                  'old = calculate\n'
                                                  'def replace(seed):\n'
                                                  '    global calculate\n'
                                                  '    def calculate(value=seed):\n'
                                                  '        return value + 10\n'
                                                  '\n'
                                                  'replace(7)\n'
                                                  'print(old(), calculate())\n'},
 'imported_module_versions': {'main.py': 'from library import previous, calculate\n'
                                         '\n'
                                         'print(previous(), calculate(), previous is calculate)\n',
                              'library.py': 'def calculate(value=2):\n'
                                            '    return value + 3\n'
                                            '\n'
                                            'previous = calculate\n'
                                            'def calculate(value=4):\n'
                                            '    return value + 7\n'},
 'failed_module_generation_versions': {'main.py': 'import state\n'
                                                  '\n'
                                                  'def load(value):\n'
                                                  '    import worker\n'
                                                  '    return value\n'
                                                  '\n'
                                                  'print(list(map(load, [0])))\n'
                                                  'import worker\n'
                                                  'print(state.saved[0](), state.saved[1](), '
                                                  'state.saved[2](), state.saved[3]())\n',
                                       'state.py': 'attempts = 0\nsaved = []\n',
                                       'worker.py': 'import state\n'
                                                    '\n'
                                                    'state.attempts += 1\n'
                                                    'seed = state.attempts * 100\n'
                                                    'def calculate(value=seed):\n'
                                                    '    return value\n'
                                                    '\n'
                                                    'state.saved.append(calculate)\n'
                                                    'def calculate(value=seed + 1):\n'
                                                    '    return value\n'
                                                    '\n'
                                                    'state.saved.append(calculate)\n'
                                                    'if state.attempts == 1:\n'
                                                    '    next(iter([]))\n'},
 'class_caller_uses_current_factory': {'main.py': 'def build(value=2):\n'
                                                  '    return Parcel(value + 1)\n'
                                                  '\n'
                                                  'old = build\n'
                                                  'class Parcel:\n'
                                                  '    def __init__(self, value):\n'
                                                  '        self.value = value\n'
                                                  '    def advance(self):\n'
                                                  '        return build(self.value)\n'
                                                  '\n'
                                                  'def build(value=4):\n'
                                                  '    return Parcel(value + 10)\n'
                                                  '\n'
                                                  'print(old().value, build().value, '
                                                  'Parcel(5).advance().value)\n'},
 'builtin_shadow_versions': {'main.py': 'print(abs(-3))\n'
                                        'def abs(value=2):\n'
                                        '    return value + 10\n'
                                        '\n'
                                        'old = abs\n'
                                        'def abs(value=4):\n'
                                        '    return value + 20\n'
                                        '\n'
                                        'print(old(), abs())\n'},
 'deleted_binding_precedes_argument': {'main.py': 'def calculate(value):\n'
                                                  '    return value + 1\n'
                                                  '\n'
                                                  'old = calculate\n'
                                                  'del calculate\n'
                                                  'def argument():\n'
                                                  "    print('argument must not run')\n"
                                                  '    return 7\n'
                                                  '\n'
                                                  'print(old(1))\n'
                                                  'print(calculate(argument()))\n'
                                                  'def calculate(value):\n'
                                                  '    return value + 10\n'},
 'unchanged_inherited_aliases': {'main.py': 'def f(x=3):\n'
                                            '    return x+10\n'
                                            'old=f\n'
                                            'f=99\n'
                                            'print(old(),old(7),f)\n'
                                            'def f(x=4):\n'
                                            '    return x+20\n'
                                            'new=f\n'
                                            'print(old(),new(),f(8))\n'
                                            'f=old\n'
                                            'new_alias=f\n'
                                            'print(f(1),new_alias(2),new(3))\n'}}

INPUTS = {'module_alias_versions': [''],
 'definition_default_effects': [''],
 'mutable_default_aliases': [''],
 'recursive_name_uses_current_binding': ['0\n', '2\n'],
 'callee_capture_before_rebinding_argument': [''],
 'unpublished_binding_precedes_argument': [''],
 'default_reads_previous_definition': [''],
 'different_signatures_and_binding_errors': ['0\n', '1\n'],
 'branch_definition_versions': ['0\n', '1\n'],
 'loop_definition_default_instances': [''],
 'local_versions_and_default_captures': [''],
 'nonlocal_definition_rebind': [''],
 'global_definition_inside_function': [''],
 'imported_module_versions': [''],
 'failed_module_generation_versions': [''],
 'class_caller_uses_current_factory': [''],
 'builtin_shadow_versions': [''],
 'deleted_binding_precedes_argument': [''],
 'unchanged_inherited_aliases': ['']}

def convert_project(files, integer="i64"):
    observed = []
    original = CallableCells.definition_emission
    def emission(provider, emitter, node):
        value = original(provider, emitter, node)
        if value:
            observed.append((node, provider.model.functions.definitions[node],
                             provider.definition_value(node), value))
        return value
    with tempfile.TemporaryDirectory(prefix="pytors-function-version-") as directory:
        root = Path(directory)
        for filename, text in files.items():
            (root/filename).write_text(text)
        with mock_module.patch.object(CallableCells, "definition_emission", emission):
            result = transpile(files["main.py"], TranspileOptions(
                filename=str(root/"main.py"), integer=integer, license="none"))
    return result, observed


class FunctionDefinitionVersionProofs(unittest_module.TestCase):
    def test_actual_source_nodes_have_independent_plans_cells_and_defaults(self):
        text = PROJECTS["module_alias_versions"]["main.py"]
        unit = build_program(text, "versions.py").main
        before = ast.dump(unit.tree, include_attributes=True)
        nodes = [node for node in unit.tree.body if isinstance(node, ast.FunctionDef)]
        model = Model(unit.tree, unit.filename, "i64", unit.native_imports, unit=unit)
        self.assertEqual(set(model.functions.definitions), set(nodes))
        versions = model.function_versions("calculate")
        self.assertEqual(tuple(plan.node for plan in versions), tuple(nodes))
        self.assertIs(model.functions["calculate"], versions[-1])
        self.assertIsNot(versions[0].default_cells["value"], versions[1].default_cells["value"])
        self.assertEqual([plan.default_literals["value"] for plan in versions], [3, 7])
        provider = model.callable_cells
        self.assertIn("calculate", provider.versioned_names)
        self.assertIn("calculate", provider.mutable_names)
        self.assertIn("calculate", provider.function_bindings)
        for plan in versions:
            definition = unit.ordinal(plan.node)
            self.assertIs(provider.plans[definition], plan)
            self.assertEqual(provider.definition_value(plan.node).root().args, (definition,))
            self.assertEqual(plan.definition_key, (unit.name, definition))
        self.assertEqual(ast.dump(unit.tree, include_attributes=True), before)

    def test_publication_uses_each_original_event_in_both_module_carriers(self):
        for name in ("module_alias_versions", "imported_module_versions", "class_caller_uses_current_factory"):
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(name=name, integer=integer):
                    result, observed = convert_project(PROJECTS[name], integer)
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    versions = [(node, plan, cell, code) for node, plan, cell, code in observed
                                if node.name in {"calculate", "build"}]
                    self.assertEqual(len(versions), 2)
                    self.assertIsNot(versions[0][1], versions[1][1])
                    for node, plan, cell, code in versions:
                        self.assertIs(plan.node, node)
                        self.assertEqual(len(cell.root().args), 1)
                        self.assertIn(".borrow_mut().value_", code)
                    self.assertNotIn("enum ClassFunctionRef", result.rust_source)

    def test_nonmodule_definition_versions_keep_the_existing_positioned_boundary(self):
        for name in ("branch_definition_versions", "loop_definition_default_instances",
                     "local_versions_and_default_captures", "global_definition_inside_function",
                     "nonlocal_definition_rebind"):
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(name=name, integer=integer):
                    result, _ = convert_project(PROJECTS[name], integer)
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code, "E006")
                    self.assertGreater(result.diagnostics[0].line, 0)


@unittest_module.skipUnless(shutil.which("rustc"), "rustc is required")
class FunctionDefinitionVersionExecution(unittest_module.TestCase):
    def exercise(self, name):
        files = PROJECTS[name]
        with tempfile.TemporaryDirectory(prefix="pytors-function-version-run-") as directory:
            root = Path(directory)
            for filename, text in files.items():
                (root/filename).write_text(text)
            main = root/"main.py"
            references = [subprocess.run([sys.executable, "-S", "-B", str(main)], input=data,
                text=True, capture_output=True, timeout=15) for data in INPUTS[name]]
            result = transpile(main.read_text(), TranspileOptions(filename=str(main), integer="i64", license="none"))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native")
            rust = root/"program.rs"
            rust.write_text(result.rust_source)
            frames = lambda text: re.findall(r'File "([^"\n]+)", line (\d+), in ([^\n]+)', text)
            for optimized in (False, True):
                binary = root/("optimized" if optimized else "debug")
                built = subprocess.run(["rustc", "--edition=2021", "--crate-name", "function_versions",
                    *(["-O"] if optimized else []), str(rust), "-o", str(binary)],
                    text=True, capture_output=True, timeout=180)
                self.assertEqual(built.returncode, 0, built.stderr)
                for data, expected in zip(INPUTS[name], references):
                    with self.subTest(name=name, optimized=optimized, stdin=data):
                        actual = subprocess.run([str(binary)], input=data, text=True, capture_output=True,
                            timeout=15, env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.stdout, expected.stdout)
                        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                        self.assertEqual(frames(actual.stderr), frames(expected.stderr))
                        self.assertEqual(actual.stderr.splitlines()[-1:], expected.stderr.splitlines()[-1:])

    def test_old_aliases_keep_literal_evaluated_and_mutable_defaults(self):
        for name in ("unchanged_inherited_aliases", "module_alias_versions", "definition_default_effects",
                     "default_reads_previous_definition", "mutable_default_aliases"):
            self.exercise(name)

    def test_current_names_callee_capture_and_real_binding_errors(self):
        for name in ("recursive_name_uses_current_binding", "callee_capture_before_rebinding_argument",
                     "unpublished_binding_precedes_argument", "different_signatures_and_binding_errors",
                     "deleted_binding_precedes_argument"):
            self.exercise(name)

    def test_imported_defaults_failed_generations_class_callers_and_builtin_shadowing(self):
        for name in ("imported_module_versions", "failed_module_generation_versions",
                     "class_caller_uses_current_factory", "builtin_shadow_versions"):
            self.exercise(name)


if __name__ == "__main__":
    unittest_module.main()
