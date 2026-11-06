"""Canonical native phases preserve source-list facts without hiding callbacks."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_native_source_state as state_tests
from py2fastrust.native_source_native_effects import sealed_builtin, builtin_iterable
from py2fastrust.references import BuiltinIdentity
from py2fastrust.native_types import ListType
from py2fastrust.native_classes import InstanceType

SOURCES = {'stream_word_input': 'import sys\n'
                      'class Stack:\n'
                      '    items = []\n'
                      '    def __init__(self, value):\n'
                      '        self.value = value\n'
                      '    def __enter__(self):\n'
                      '        self.items.append(self.value)\n'
                      '    def __exit__(self, kind, error, trace):\n'
                      '        self.items.pop()\n'
                      '    @classmethod\n'
                      '    def current(cls):\n'
                      '        return cls.items[-1]\n'
                      'with Stack(37):\n'
                      '    n, m = map(int, sys.stdin.readline().split())\n'
                      '    print(n + m, Stack.current())\n',
 'bytes_reader_alias': 'import sys\n'
                       'class Stack:\n'
                       '    items = []\n'
                       '    def __init__(self, value):\n'
                       '        self.value = value\n'
                       '    def __enter__(self):\n'
                       '        self.items.append(self.value)\n'
                       '    def __exit__(self, kind, error, trace):\n'
                       '        self.items.pop()\n'
                       '    @classmethod\n'
                       '    def current(cls):\n'
                       '        return cls.items[-1]\n'
                       'input = sys.stdin.buffer.readline\n'
                       'with Stack(41):\n'
                       '    n, m = map(int, input().split())\n'
                       '    print(n * m, Stack.current())\n',
 'canonical_instance_tests': 'class Stack:\n'
                             '    items = []\n'
                             '    def __init__(self, value):\n'
                             '        self.value = value\n'
                             '    def __enter__(self):\n'
                             '        self.items.append(self.value)\n'
                             '    def __exit__(self, kind, error, trace):\n'
                             '        self.items.pop()\n'
                             '    @classmethod\n'
                             '    def current(cls):\n'
                             '        return cls.items[-1]\n'
                             'class Box:\n'
                             '    def __init__(self, value):\n'
                             '        self.value = value\n'
                             'with Stack(29):\n'
                             '    item = Box(3)\n'
                             '    print(isinstance(item, Box), isinstance(3, int), '
                             'Stack.current())\n',
 'shadowed_instance_test': 'class Stack:\n'
                           '    items = []\n'
                           '    def __init__(self, value):\n'
                           '        self.value = value\n'
                           '    def __enter__(self):\n'
                           '        self.items.append(self.value)\n'
                           '    def __exit__(self, kind, error, trace):\n'
                           '        self.items.pop()\n'
                           '    @classmethod\n'
                           '    def current(cls):\n'
                           '        return cls.items[-1]\n'
                           'def isinstance(value, kind):\n'
                           '    Stack.items.clear()\n'
                           '    return False\n'
                           'with Stack(23):\n'
                           '    print(isinstance(3, int))\n'
                           '    print(Stack.current())\n',
 'replaced_native_stream': 'import sys\n'
                           'class Stack:\n'
                           '    items = []\n'
                           '    def __init__(self, value):\n'
                           '        self.value = value\n'
                           '    def __enter__(self):\n'
                           '        self.items.append(self.value)\n'
                           '    def __exit__(self, kind, error, trace):\n'
                           '        self.items.pop()\n'
                           '    @classmethod\n'
                           '    def current(cls):\n'
                           '        return cls.items[-1]\n'
                           'class Reader:\n'
                           '    def readline(self):\n'
                           '        Stack.items.clear()\n'
                           '        return "1 2"\n'
                           'sys.stdin = Reader()\n'
                           'with Stack(19):\n'
                           '    text = sys.stdin.readline()\n'
                           '    print(text, Stack.current())\n',
 'split_index_protocol': 'class Stack:\n'
                         '    items = []\n'
                         '    def __init__(self, value):\n'
                         '        self.value = value\n'
                         '    def __enter__(self):\n'
                         '        self.items.append(self.value)\n'
                         '    def __exit__(self, kind, error, trace):\n'
                         '        self.items.pop()\n'
                         '    @classmethod\n'
                         '    def current(cls):\n'
                         '        return cls.items[-1]\n'
                         'class Limit:\n'
                         '    def __index__(self):\n'
                         '        Stack.items.clear()\n'
                         '        return 0\n'
                         'with Stack(17):\n'
                         '    print("a b".split(None, Limit()))\n'
                         '    print(Stack.current())\n',
 'native_text_and_numeric_queries': 'class Stack:\n'
                                    '    items = []\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value = value\n'
                                    '    def __enter__(self):\n'
                                    '        self.items.append(self.value)\n'
                                    '    def __exit__(self, kind, error, trace):\n'
                                    '        self.items.pop()\n'
                                    '    @classmethod\n'
                                    '    def current(cls):\n'
                                    '        return cls.items[-1]\n'
                                    'with Stack(43):\n'
                                    '    text = input()\n'
                                    '    print(len(text.strip().split()), (7).bit_count(), '
                                    'Stack.current())\n',
 'tracked_receiver_temporary_empty': 'class Stack:\n'
                                     '    items = []\n'
                                     '    def __init__(self, value):\n'
                                     '        self.value = value\n'
                                     '    def __enter__(self):\n'
                                     '        self.items.append(self.value)\n'
                                     '    def __exit__(self, kind, error, trace):\n'
                                     '        self.items.pop()\n'
                                     '    @classmethod\n'
                                     '    def current(cls):\n'
                                     '        return cls.items[-1]\n'
                                     'def key(value):\n'
                                     '    return Stack.current()\n'
                                     'with Stack(31):\n'
                                     '    Stack.items.sort(key=key)\n'
                                     '    print("after sort", Stack.current())\n',
 'disjoint_receiver_callback': 'class Stack:\n'
                               '    items = []\n'
                               '    def __init__(self, value):\n'
                               '        self.value = value\n'
                               '    def __enter__(self):\n'
                               '        self.items.append(self.value)\n'
                               '    def __exit__(self, kind, error, trace):\n'
                               '        self.items.pop()\n'
                               '    @classmethod\n'
                               '    def current(cls):\n'
                               '        return cls.items[-1]\n'
                               'def key(value):\n'
                               '    return Stack.current()\n'
                               'values = [3, 1]\n'
                               'with Stack(31):\n'
                               '    values.sort(key=key)\n'
                               '    print(values, Stack.current())\n'}
INPUTS = {'stream_word_input': ('4 9\n', 'bad 9\n'),
 'bytes_reader_alias': ('3 7\n',),
 'canonical_instance_tests': ('',),
 'shadowed_instance_test': ('',),
 'replaced_native_stream': ('',),
 'split_index_protocol': ('',),
 'native_text_and_numeric_queries': (' a b c \n', '\n'),
 'tracked_receiver_temporary_empty': ('',),
 'disjoint_receiver_callback': ('',)}


class NativeSourceNativeEffectProofs(unittest.TestCase):
    def test_apparent_class_protocol_is_not_a_no_write_builtin_phase(self):
        from py2fastrust.native_aot_callables import AotFunctionType
        owner = SimpleNamespace(node=ast.parse('class Proxy: pass').body[0],
                                index=3, methods={}, fields={})
        members = {}
        model = SimpleNamespace(classes={'Proxy': owner},
                                class_namespaces=SimpleNamespace(members=members))
        arguments = (InstanceType('Proxy'), AotFunctionType((), (BuiltinIdentity('int'),)))
        self.assertTrue(sealed_builtin(model, BuiltinIdentity('isinstance'), arguments))
        for table, key in ((owner.methods, '__class__'), (owner.fields, '__class__'),
                           (members, (3, '__class__'))):
            with self.subTest(storage=key):
                table[key] = object()
                self.assertFalse(sealed_builtin(model, BuiltinIdentity('isinstance'), arguments))
                table.clear()

    def test_builtin_length_does_not_visit_object_elements(self):
        kind = ListType(InstanceType("Object"))
        self.assertTrue(sealed_builtin(None, BuiltinIdentity("len"), (kind,)))
        self.assertTrue(sealed_builtin(None, BuiltinIdentity("bool"), (kind,)))
        self.assertFalse(sealed_builtin(None, BuiltinIdentity("int"), (kind,)))
        self.assertTrue(builtin_iterable(kind))

    def test_native_input_phases_keep_the_completed_append_value(self):
        for name in ("stream_word_input", "bytes_reader_alias", "native_text_and_numeric_queries"):
            for integer in ("i64", "i128"):
                with self.subTest(name=name, integer=integer):
                    result, model, reads, exports = state_tests.convert(SOURCES[name], integer)
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertTrue(model.source_state.bridges)
                    self.assertTrue(reads)
                    self.assertTrue(exports)

    def test_canonical_type_queries_keep_the_completed_append_value(self):
        result, _, reads, exports = state_tests.convert(SOURCES["canonical_instance_tests"])
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_sort_callback_cannot_observe_a_stale_nonempty_receiver(self):
        result, _, reads, exports = state_tests.convert(SOURCES["tracked_receiver_temporary_empty"])
        self.assertTrue(result.success, result.diagnostics)
        self.assertFalse(reads)
        self.assertFalse(exports)

    def test_disjoint_sort_callback_may_use_the_unchanged_source_list(self):
        result, _, reads, exports = state_tests.convert(SOURCES["disjoint_receiver_callback"])
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(reads)
        self.assertTrue(exports)

    def test_shadowed_and_protocol_calls_preserve_existing_admission(self):
        for name in ("shadowed_instance_test", "replaced_native_stream", "split_index_protocol"):
            with self.subTest(name=name):
                result, _, _, _ = state_tests.convert(SOURCES[name])
                baseline, _, _, _ = state_tests.convert(SOURCES[name], enabled=False)
                self.assertEqual(result.success, baseline.success)
                if not result.success:
                    self.assertTrue(result.diagnostics)
                    self.assertEqual([str(d) for d in result.diagnostics], [str(d) for d in baseline.diagnostics])


@unittest.skipUnless(state_tests.shutil.which("rustc"), "rustc is required")
class NativeSourceNativeEffectExecution(unittest.TestCase):
    def exercise(self, name):
        with patch.dict(state_tests.SOURCES, SOURCES):
            state_tests.NativeSourceStateExecutionTests.exercise(self, name, INPUTS[name])

    def test_text_and_byte_input_paths(self):
        for name in ("stream_word_input", "bytes_reader_alias", "native_text_and_numeric_queries"):
            self.exercise(name)

    def test_canonical_type_test(self):
        self.exercise("canonical_instance_tests")

    def test_native_sort_internal_phases(self):
        for name in ("tracked_receiver_temporary_empty", "disjoint_receiver_callback"):
            self.exercise(name)

    def test_shadowed_builtin_remains_a_source_call(self):
        self.exercise("shadowed_instance_test")


if __name__ == "__main__":
    unittest.main()
