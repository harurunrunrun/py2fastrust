"""Borrow namespace list slots without changing source lookup or error order."""
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
from py2fastrust import native_namespace_read_places as places

PROJECTS = {'class_parameter_index': {'main.py': 'class Shelf:\n'
                                      '    values = [17, 29, 41]\n'
                                      '    @classmethod\n'
                                      '    def read(cls, index):\n'
                                      '        return cls.values[index]\n'
                                      '\n'
                                      'position = int(input())\n'
                                      'print(Shelf.read(position))\n'},
 'class_alias_and_mutation': {'main.py': 'class Rack:\n'
                                         '    values = [4, 9]\n'
                                         '\n'
                                         'alias = Rack\n'
                                         'items = alias.values\n'
                                         'items[0] = 31\n'
                                         'index = int(input())\n'
                                         'print(alias.values[index - 1])\n'},
 'empty_class_member': {'main.py': 'class Empty:\n    values = []\n\nprint(Empty.values[-1])\n'},
 'deleted_class_member': {'main.py': 'class Removed:\n'
                                     '    values = [23]\n'
                                     '\n'
                                     'del Removed.values\n'
                                     'print(Removed.values[0])\n'},
 'replaced_class_member': {'main.py': 'class Replaced:\n'
                                      '    values = [23]\n'
                                      '\n'
                                      'alias = Replaced\n'
                                      'previous = alias.values\n'
                                      'alias.values = [47, 53]\n'
                                      'previous[0] = 71\n'
                                      'print(Replaced.values[-1], previous[0])\n'},
 'index_replaces_member': {'main.py': 'class Box:\n'
                                      '    values = [13]\n'
                                      '\n'
                                      'def choose():\n'
                                      "    print('index')\n"
                                      '    Box.values = [37]\n'
                                      '    return 0\n'
                                      '\n'
                                      'print(Box.values[choose()], Box.values[0])\n'},
 'index_deletes_member': {'main.py': 'class Box:\n'
                                     '    values = [19]\n'
                                     '\n'
                                     'def choose():\n'
                                     "    print('index')\n"
                                     '    del Box.values\n'
                                     '    return 0\n'
                                     '\n'
                                     'print(Box.values[choose()])\n'},
 'index_mutates_alias': {'main.py': 'class Queue:\n'
                                    '    values = [5, 11]\n'
                                    '\n'
                                    'alias = Queue.values\n'
                                    'def choose():\n'
                                    '    alias.pop()\n'
                                    '    alias[0] = 43\n'
                                    '    return -1\n'
                                    '\n'
                                    'print(Queue.values[choose()])\n'},
 'receiver_effect': {'main.py': 'class Result:\n'
                                '    values = [59, 61]\n'
                                '\n'
                                'def receiver():\n'
                                "    print('receiver')\n"
                                '    return Result\n'
                                '\n'
                                'index = int(input())\n'
                                'print(receiver().values[index])\n'},
 'receiver_error_before_index': {'main.py': 'class Result:\n'
                                            '    values = [59]\n'
                                            '\n'
                                            'def receiver():\n'
                                            "    print('receiver')\n"
                                            "    raise ValueError('receiver stopped')\n"
                                            '\n'
                                            'def choose():\n'
                                            "    print('index must not run')\n"
                                            '    return 0\n'
                                            '\n'
                                            'print(receiver().values[choose()])\n'},
 'member_error_before_index': {'main.py': 'class Missing:\n'
                                          '    values = [67]\n'
                                          '\n'
                                          'del Missing.values\n'
                                          'print(Missing.values[1 // 0])\n'},
 'primitive_index_error': {'main.py': 'class Present:\n'
                                      '    values = [73]\n'
                                      '\n'
                                      'divisor = int(input())\n'
                                      'print(Present.values[1 // divisor])\n'},
 'module_member': {'main.py': 'import storage\n\nindex = int(input())\nprint(storage.samples[index])\n',
                   'storage.py': 'samples = [79, 83, 89]\n'},
 'module_replacement_and_alias': {'main.py': 'import storage\n'
                                             '\n'
                                             'module_alias = storage\n'
                                             'old = storage.samples\n'
                                             'module_alias.samples = [97, 101]\n'
                                             'old.append(103)\n'
                                             'print(storage.samples[-1], old[-1])\n',
                                  'storage.py': 'samples = [107]\n'},
 'module_deleted_member': {'main.py': 'import storage\n\ndel storage.samples\nprint(storage.samples[0])\n',
                           'storage.py': 'samples = [109]\n'},
 'module_index_replacement': {'main.py': 'import storage\n'
                                         '\n'
                                         'def choose():\n'
                                         '    storage.samples = [127]\n'
                                         '    return 0\n'
                                         '\n'
                                         'print(storage.samples[choose()], storage.samples[0])\n',
                              'storage.py': 'samples = [113]\n'},
 'failed_generation_class_parameter': {'main.py': 'import state\n'
                                                  '\n'
                                                  'try:\n'
                                                  '    import unstable\n'
                                                  'except StopIteration:\n'
                                                  '    pass\n'
                                                  'import unstable\n'
                                                  'print(state.saved[0].read(0), '
                                                  'unstable.Cache.read(-1))\n',
                                       'state.py': 'generation = 0\nsaved = []\n',
                                       'unstable.py': 'import state\n'
                                                      '\n'
                                                      'state.generation += 1\n'
                                                      'class Cache:\n'
                                                      '    values = [state.generation * 10 + 1]\n'
                                                      '    @classmethod\n'
                                                      '    def read(cls, index):\n'
                                                      '        return cls.values[index]\n'
                                                      '\n'
                                                      'if state.generation == 1:\n'
                                                      '    state.saved.append(Cache)\n'
                                                      '    next(iter(()))\n'},
 'closure_actual_class': {'main.py': 'class First:\n'
                                     '    values = [131]\n'
                                     '\n'
                                     'class Second:\n'
                                     '    values = [137]\n'
                                     '\n'
                                     'def make(owner):\n'
                                     '    def read(index):\n'
                                     '        return owner.values[index]\n'
                                     '    return read\n'
                                     '\n'
                                     'read_first = make(First)\n'
                                     'print(read_first(0), make(Second)(-1))\n'},
 'scalar_element_families': {'main.py': 'class Values:\n'
                                        '    flags = [True, False]\n'
                                        '    fractions = [1.25, 2.5]\n'
                                        '\n'
                                        'index = int(input())\n'
                                        'print(Values.flags[index], Values.fractions[index])\n'},
 'custom_index_protocol': {'main.py': 'class Data:\n'
                                      '    values = [139]\n'
                                      '\n'
                                      'class Offset:\n'
                                      '    def __index__(self):\n'
                                      "        print('index protocol')\n"
                                      '        Data.values = [149]\n'
                                      '        return 0\n'
                                      '\n'
                                      'print(Data.values[Offset()], Data.values[0])\n'},
 'inherited_class_member': {'main.py': 'class Parent:\n'
                                       '    values = [151]\n'
                                       '\n'
                                       'class Child(Parent):\n'
                                       '    pass\n'
                                       '\n'
                                       'print(Child.values[0])\n'},
 'source_finalizer_barrier': {'main.py': 'class Payload:\n'
                                         '    def __del__(self):\n'
                                         "        print('payload released')\n"
                                         '\n'
                                         'class Holder:\n'
                                         '    values = [157]\n'
                                         '    payload = Payload()\n'
                                         '\n'
                                         'print(Holder.values[-1])\n'
                                         'del Holder.payload\n'},
 'saved_refcount_observer_barrier': {'main.py': 'import sys\n'
                                                '\n'
                                                'class Holder:\n'
                                                '    values = [163]\n'
                                                '\n'
                                                'observe = sys.getrefcount\n'
                                                'print(observe(Holder) > 0, Holder.values[0])\n'},
 'source_collection_barrier': {'main.py': 'import gc\n'
                                          '\n'
                                          'class Link:\n'
                                          '    def __init__(self):\n'
                                          '        self.next = self\n'
                                          '\n'
                                          'class Holder:\n'
                                          '    values = [167]\n'
                                          '\n'
                                          'item = Link()\n'
                                          'print(Holder.values[0])\n'
                                          'del item\n'
                                          'gc.collect()\n'
                                          'print(Holder.values[-1])\n'},
 'cleanup_mutates_member_after_index_error': {'main.py': 'class Holder:\n'
                                                         '    values = [173]\n'
                                                         '\n'
                                                         'class Cleanup:\n'
                                                         '    def __enter__(self):\n'
                                                         "        print('enter')\n"
                                                         '        return self\n'
                                                         '    def __exit__(self, kind, value, trace):\n'
                                                         '        Holder.values = [179]\n'
                                                         "        print('cleanup', Holder.values[-1])\n"
                                                         '        return True\n'
                                                         '\n'
                                                         'with Cleanup():\n'
                                                         '    print(Holder.values[1 // 0])\n'
                                                         'print(Holder.values[0])\n'},
 'direct_id_observer_barrier': {'main.py': 'class Holder:\n'
                                           '    values = [181]\n'
                                           '\n'
                                           'print(id(Holder) > 0, Holder.values[0])\n'}}

INPUTS = {'class_parameter_index': ['0\n', '-1\n', '3\n'],
 'class_alias_and_mutation': ['1\n', '0\n'],
 'empty_class_member': [''],
 'deleted_class_member': [''],
 'replaced_class_member': [''],
 'index_replaces_member': [''],
 'index_deletes_member': [''],
 'index_mutates_alias': [''],
 'receiver_effect': ['-1\n'],
 'receiver_error_before_index': [''],
 'member_error_before_index': [''],
 'primitive_index_error': ['0\n', '1\n'],
 'module_member': ['1\n', '-4\n'],
 'module_replacement_and_alias': [''],
 'module_deleted_member': [''],
 'module_index_replacement': [''],
 'failed_generation_class_parameter': [''],
 'closure_actual_class': [''],
 'scalar_element_families': ['0\n', '-1\n'],
 'custom_index_protocol': [''],
 'inherited_class_member': [''],
 'source_finalizer_barrier': [''],
 'saved_refcount_observer_barrier': [''],
 'source_collection_barrier': [''],
 'cleanup_mutates_member_after_index_error': [''],
 'direct_id_observer_barrier': ['']}

def convert(files, integer="i64", *, disabled=False):
    attempts, reads = [], []
    original = places.read
    def observed(emitter, node):
        value = original(emitter, node)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            attempts.append((type(node.slice), value is not None))
        if value is not None:
            place = places.select(emitter, node)
            reads.append((place, value.code))
        return value
    with tempfile.TemporaryDirectory(prefix="pytors-namespace-read-") as directory:
        root = Path(directory)
        for name, source in files.items():
            (root / name).write_text(source)
        options = TranspileOptions(filename=str(root / "main.py"), integer=integer, license="none")
        with (mock_module.patch.object(places, "read", return_value=None) if disabled
              else mock_module.patch.object(places, "read", side_effect=observed)):
            result = transpile(files["main.py"], options)
    return result, attempts, reads


class NamespaceReadPlaceProofs(unittest_module.TestCase):
    def test_actual_class_module_and_mutable_alias_slots_select(self):
        for name in ("class_parameter_index", "class_alias_and_mutation",
                     "replaced_class_member", "module_member", "module_replacement_and_alias"):
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(name=name, integer=integer):
                    result, _, reads = convert(PROJECTS[name], integer)
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertTrue(reads)
                    for place, code in reads:
                        slot = "value_" + str(place.slot)
                        self.assertIn(slot + ".as_ref()", code)
                        self.assertNotIn(slot + ".clone()", code)
                        self.assertIn("Result<", code)
                        self.assertIn(",NativeError>", code)
                        self.assertIn(".borrow()", code)

    def test_effectful_index_and_invalid_receiver_keep_the_old_conversion(self):
        for name in ("index_deletes_member", "index_mutates_alias", "receiver_error_before_index",
                     "module_deleted_member", "failed_generation_class_parameter"):
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(name=name, integer=integer):
                    # Use one stable filename for visible trace metadata.
                    with tempfile.TemporaryDirectory(prefix="pytors-namespace-barrier-") as directory:
                        root = Path(directory)
                        files = PROJECTS[name]
                        for filename, source in files.items():
                            (root / filename).write_text(source)
                        options = TranspileOptions(filename=str(root / "main.py"), integer=integer, license="none")
                        with mock_module.patch.object(places, "read", return_value=None):
                            baseline = transpile(files["main.py"], options)
                        actual = transpile(files["main.py"], options)
                    self.assertEqual(actual.success, baseline.success)
                    self.assertEqual(actual.diagnostics, baseline.diagnostics)
                    self.assertEqual(actual.rust_source, baseline.rust_source)

    def test_scalar_element_carriers_and_unconstrained_empty_member(self):
        for integer in ("i64", "i128", "bigint"):
            result, _, reads = convert(PROJECTS["scalar_element_families"], integer)
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual({place.kind.element for place, _ in reads}, {"bool", "float"})
            result, _, reads = convert(PROJECTS["empty_class_member"], integer)
            self.assertTrue(result.success, result.diagnostics)
            # In this program the existing solver closes the empty list's
            # carrier as int; selection must keep the real empty-list check.
            for _, code in reads:
                self.assertIn("IndexError: list index out of range", code)
        for name in ("source_finalizer_barrier", "saved_refcount_observer_barrier", "source_collection_barrier",
                     "direct_id_observer_barrier"):
            result, _, reads = convert(PROJECTS[name])
            self.assertFalse(reads)


@unittest_module.skipUnless(shutil.which("rustc"), "rustc is required")
class NamespaceReadPlaceExecution(unittest_module.TestCase):
    def exercise(self, name):
        files = PROJECTS[name]
        with tempfile.TemporaryDirectory(prefix="pytors-namespace-native-") as directory:
            root = Path(directory)
            for filename, source in files.items():
                (root / filename).write_text(source)
            main = root / "main.py"
            references = [subprocess.run([sys.executable, "-S", "-B", str(main)], input=data,
                          capture_output=True, text=True, timeout=15) for data in INPUTS[name]]
            result = transpile(main.read_text(), TranspileOptions(filename=str(main), integer="i64", license="none"))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native")
            rust = root / "source.rs"
            rust.write_text(result.rust_source)
            frames = lambda text: re.findall(r'File "([^"\n]+)", line (\d+), in ([^\n]+)', text)
            for optimized in (False, True):
                binary = root / ("optimized" if optimized else "debug")
                built = subprocess.run(["rustc", "--edition=2021", "--crate-name", "namespace_read_places",
                        *(["-O"] if optimized else []), str(rust), "-o", str(binary)],
                        text=True, capture_output=True, timeout=180)
                self.assertEqual(built.returncode, 0, built.stderr)
                for data, expected in zip(INPUTS[name], references):
                    with self.subTest(name=name, optimized=optimized, stdin=data):
                        actual = subprocess.run([str(binary)], input=data, text=True, capture_output=True,
                            timeout=15, env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                        self.assertEqual(actual.stdout, expected.stdout)
                        self.assertEqual(frames(actual.stderr), frames(expected.stderr))
                        self.assertEqual(actual.stderr.splitlines()[-1:], expected.stderr.splitlines()[-1:])

    def test_mutable_aliases_receiver_capture_and_effectful_indices(self):
        for name in ("class_alias_and_mutation", "module_replacement_and_alias",
                     "index_replaces_member", "receiver_effect"):
            self.exercise(name)

    def test_member_index_errors_and_original_trace_locations(self):
        for name in ("class_parameter_index", "primitive_index_error", "member_error_before_index",
                     "empty_class_member"):
            self.exercise(name)
        self.exercise("cleanup_mutates_member_after_index_error")

    def test_failed_generation_and_captured_class_receivers(self):
        for name in ("closure_actual_class",):
            self.exercise(name)


if __name__ == "__main__":
    unittest_module.main()
