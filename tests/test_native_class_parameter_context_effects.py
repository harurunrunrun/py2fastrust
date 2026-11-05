"""Parameter class attributes retain their actual namespace without module views."""
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from py2fastrust import native_call_context_effects as effects
from py2fastrust import native_immediate_classmethod as immediate
from tests import test_native_class_binding_contexts as linked

CASES = {'scalar_attribute': [{'main.py': 'from library import Gauge\n'
                                  'print(Gauge.read(int(input())))\n',
                       'library.py': 'class Gauge:\n'
                                     '    base = 7\n'
                                     '    @classmethod\n'
                                     '    def read(cls, offset):\n'
                                     '        return cls.base + offset\n'},
                      ['5\n']],
 'list_alias_and_replacement': [{'main.py': 'from library import Shelf\n'
                                            'Alias = Shelf\n'
                                            'print(Alias.peek())\n'
                                            'Shelf.items.append(9)\n'
                                            'print(Alias.peek())\n'
                                            'Alias.items = [21]\n'
                                            'print(Shelf.peek())\n',
                                 'library.py': 'class Shelf:\n'
                                               '    items = [3, 5]\n'
                                               '    @classmethod\n'
                                               '    def peek(cls):\n'
                                               '        return '
                                               'cls.items[-1]\n'},
                                ['']],
 'index_error_frames': [{'main.py': 'from library import Shelf\n'
                                    'print("before")\n'
                                    'print(Shelf.read(int(input())))\n',
                         'library.py': 'class Shelf:\n'
                                       '    items = [4, 8]\n'
                                       '    @classmethod\n'
                                       '    def read(cls, index):\n'
                                       '        return cls.items[index]\n'},
                        ['1\n', '3\n']],
 'callback_keeps_actual_class': [{'main.py': 'from library import Shelf\n'
                                             'def apply(callback, index):\n'
                                             '    return callback(index)\n'
                                             'saved = Shelf.read\n'
                                             'print(apply(saved, 1))\n',
                                  'library.py': 'class Shelf:\n'
                                                '    items = [6, 10]\n'
                                                '    @classmethod\n'
                                                '    def read(cls, index):\n'
                                                '        return '
                                                'cls.items[index]\n'},
                                 ['']],
 'argument_mutates_attribute': [{'main.py': 'from library import Shelf\n'
                                            'def change():\n'
                                            '    print("argument")\n'
                                            '    Shelf.items = [13]\n'
                                            '    return 0\n'
                                            'print(Shelf.read(change()))\n',
                                 'library.py': 'class Shelf:\n'
                                               '    items = [2]\n'
                                               '    @classmethod\n'
                                               '    def read(cls, index):\n'
                                               '        return '
                                               'cls.items[index]\n'},
                                ['']],
 'saved_class_global_rebound': [{'main.py': 'import library\n'
                                            'Saved = library.Shelf\n'
                                            'library.Shelf = 0\n'
                                            'print(Saved.read())\n',
                                 'library.py': 'class Shelf:\n'
                                               '    base = 17\n'
                                               '    @classmethod\n'
                                               '    def read(cls):\n'
                                               '        return cls.base\n'},
                                ['']],
 'deleted_attribute_error': [{'main.py': 'from library import Shelf\n'
                                         'del Shelf.base\n'
                                         'print(Shelf.read())\n',
                              'library.py': 'class Shelf:\n'
                                            '    base = 17\n'
                                            '    @classmethod\n'
                                            '    def read(cls):\n'
                                            '        return cls.base\n'},
                             ['']],
 'nonliteral_default_effect': [{'main.py': 'from library import Shelf\n'
                                           'print(Shelf.read())\n',
                                'library.py': 'def choose():\n'
                                              '    print("default")\n'
                                              '    return 1\n'
                                              'class Shelf:\n'
                                              '    items = [3, 9]\n'
                                              '    @classmethod\n'
                                              '    def read(cls, '
                                              'index=choose()):\n'
                                              '        return '
                                              'cls.items[index]\n'},
                               ['']],
 'real_global_dependency': [{'main.py': 'import library\n'
                                        'offset = 1000\n'
                                        'library.offset = 20\n'
                                        'print(library.Shelf.read())\n',
                             'library.py': 'offset = 5\n'
                                           'class Shelf:\n'
                                           '    base = 7\n'
                                           '    @classmethod\n'
                                           '    def read(cls):\n'
                                           '        return cls.base + '
                                           'offset\n'},
                            ['']],
 'foreign_class_same_attribute': [{'main.py': 'from first import Shelf as '
                                              'First\n'
                                              'from second import Shelf as '
                                              'Second\n'
                                              'print(First.read(), '
                                              'Second.read())\n',
                                   'first.py': 'class Shelf:\n'
                                               '    base = 11\n'
                                               '    @classmethod\n'
                                               '    def read(cls):\n'
                                               '        return cls.base\n',
                                   'second.py': 'class Shelf:\n'
                                                '    base = 29\n'
                                                '    @classmethod\n'
                                                '    def read(cls):\n'
                                                '        return cls.base\n'},
                                  ['']],
 'inherited_classmethod_boundary': [{'main.py': 'from library import Base, '
                                                'Child\n'
                                                'print(Base.read(), '
                                                'Child.read())\n',
                                     'library.py': 'class Base:\n'
                                                   '    base = 11\n'
                                                   '    @classmethod\n'
                                                   '    def read(cls):\n'
                                                   '        return cls.base\n'
                                                   'class Child(Base):\n'
                                                   '    base = 23\n'},
                                    ['']],
 'custom_descriptor_boundary': [{'main.py': 'from library import Shelf\n'
                                            'print(Shelf.read())\n',
                                 'library.py': 'class Descriptor:\n'
                                               '    def __get__(self, '
                                               'instance, owner):\n'
                                               '        print("descriptor")\n'
                                               '        return 31\n'
                                               'class Shelf:\n'
                                               '    base = Descriptor()\n'
                                               '    @classmethod\n'
                                               '    def read(cls):\n'
                                               '        return cls.base\n'},
                                ['']],
 'frame_observer_boundary': [{'main.py': 'from library import Shelf\n'
                                         'print(Shelf.read())\n',
                              'library.py': 'import sys\n'
                                            'class Shelf:\n'
                                            '    base = 7\n'
                                            '    @classmethod\n'
                                            '    def read(cls):\n'
                                            '        frame = sys._getframe()\n'
                                            '        return '
                                            'frame.f_globals["Shelf"].base\n'},
                             ['']],
 'failed_import_actual_class_generation': [{'main.py': 'import state\n'
                                                       'def load(value):\n'
                                                       '    import unstable\n'
                                                       '    return value\n'
                                                       'print(list(map(load, '
                                                       '[1])))\n'
                                                       'import unstable\n'
                                                       'Old, New = '
                                                       'state.saved\n'
                                                       'print(Old.read(), '
                                                       'New.read(), Old is '
                                                       'New)\n',
                                            'state.py': 'attempts = 0\n'
                                                        'saved = []\n'
                                                        'def keep(value):\n'
                                                        '    '
                                                        'saved.append(value)\n',
                                            'unstable.py': 'import state\n'
                                                           'state.attempts += '
                                                           '1\n'
                                                           'class Shelf:\n'
                                                           '    base = 11 * '
                                                           'state.attempts\n'
                                                           '    @classmethod\n'
                                                           '    def '
                                                           'read(cls):\n'
                                                           '        return '
                                                           'cls.base\n'
                                                           'state.keep(Shelf)\n'
                                                           'if state.attempts '
                                                           '== 1:\n'
                                                           '    '
                                                           'next(iter([]))\n'},
                                           ['']],
 'saved_starred_default': [{'main.py': 'from library import Shelf\n'
                                       'saved = Shelf.read\n'
                                       'arguments = list(map(int, '
                                       'input().split()))\n'
                                       'print(saved(*arguments))\n',
                            'library.py': 'class Shelf:\n'
                                          '    items = [5, 12]\n'
                                          '    @classmethod\n'
                                          '    def read(cls, index=0):\n'
                                          '        return cls.items[index]\n'},
                           ['\n', '1\n', '0 1\n']],
 'direct_starred_classmethod': [{'main.py': 'from library import Shelf\n'
                                            'print(Shelf.read(*[1]))\n',
                                 'library.py': 'class Shelf:\n'
                                               '    items = [5, 12]\n'
                                               '    @classmethod\n'
                                               '    def read(cls, index):\n'
                                               '        return '
                                               'cls.items[index]\n'},
                                ['']],
 'mixed_callable_family': [{'main.py': 'from library import Shelf, other\n'
                                       'callbacks = [Shelf.read, other]\n'
                                       'print(callbacks[int(input())](1))\n',
                            'library.py': 'offset = 40\n'
                                          'class Shelf:\n'
                                          '    items = [5, 12]\n'
                                          '    @classmethod\n'
                                          '    def read(cls, index):\n'
                                          '        return cls.items[index]\n'
                                          'def other(index):\n'
                                          '    return offset + index\n'},
                           ['0\n', '1\n']],
 'ordinary_class_parameter': [{'main.py': 'from library import Shelf, read\n'
                                          'print(read(Shelf, int(input())))\n',
                               'library.py': 'class Shelf:\n'
                                             '    base = 19\n'
                                             'def read(actual, offset):\n'
                                             '    return actual.base + '
                                             'offset\n'},
                              ['4\n']],
 'scalar_instance_classmethod': [{'main.py': 'from library import Meter\n'
                                             'item = Meter(7)\n'
                                             'print(item.value, '
                                             'Meter.read(2))\n',
                                  'library.py': 'class Meter:\n'
                                                '    factor = 5\n'
                                                '    def __init__(self, '
                                                'value):\n'
                                                '        self.value = value\n'
                                                '    @classmethod\n'
                                                '    def read(cls, offset):\n'
                                                '        return cls.factor + '
                                                'offset\n'},
                                 ['']]}


def convert(name, integer="i64"):
    facts = []
    payloads = []
    original, direct = effects.prepare, immediate.direct_payload
    def prepare(model):
        original(model)
        facts.extend((getattr(plan.node, "name", "<module>"), effects.summary(model, plan))
                     for plan in model.plans if plan.reachable)
    def capture(emitter, node, reference, member):
        value = direct(emitter, node, reference, member)
        if value is not None:
            payloads.append((member.name, emitter.immediate_classmethod_request.module, value.code))
        return value
    with patch.object(effects, "prepare", side_effect=prepare), patch.object(immediate, "direct_payload", side_effect=capture):
        result, _ = linked.convert_project(CASES[name][0], integer)
    return result, facts, payloads


class ClassParameterContextProofs(unittest.TestCase):
    def check(self, name, method="read"):
        result, facts, payloads = convert(name)
        self.assertTrue(result.success, result.diagnostics)
        summaries = [summary for member, summary in facts if member == method]
        self.assertTrue(summaries)
        return result, summaries, payloads

    def test_exact_parameter_namespace_uses_actual_class(self):
        for name, method in (("scalar_attribute", "read"), ("list_alias_and_replacement", "peek"),
                             ("callback_keeps_actual_class", "read"), ("argument_mutates_attribute", "read"),
                             ("foreign_class_same_attribute", "read"), ("failed_import_actual_class_generation", "read")):
            with self.subTest(case=name):
                _, summaries, _ = self.check(name, method)
                self.assertTrue(all(not summary.incoming_module and not summary.lexical_parent for summary in summaries))

    def test_direct_private_payload_owns_the_actual_class_without_extra_module(self):
        for integer in ("i64", "i128"):
            with self.subTest(integer=integer):
                result, facts, payloads = convert("scalar_instance_classmethod", integer)
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(payloads)
                for member, module, code in payloads:
                    self.assertEqual(member, "read")
                    self.assertFalse(module)
                    self.assertNotIn(".module.clone()", code)

    def test_literal_default_expanded_callback_keeps_parameter_context(self):
        _, summaries, _ = self.check("saved_starred_default")
        self.assertTrue(all(not summary.incoming_module for summary in summaries))

    def test_nonliteral_default_retains_its_binding_context(self):
        _, summaries, _ = self.check("nonliteral_default_effect")
        self.assertTrue(all(summary.incoming_module for summary in summaries))
        self.assertTrue(any("default" in summary.reason for summary in summaries))

    def test_real_global_read_retains_its_defining_module(self):
        _, summaries, _ = self.check("real_global_dependency")
        self.assertTrue(all(summary.incoming_module for summary in summaries))

    def test_ordinary_function_accepts_an_exact_class_parameter(self):
        _, summaries, _ = self.check("ordinary_class_parameter")
        self.assertTrue(all(not summary.incoming_module for summary in summaries))

    def test_unimplemented_protocol_boundaries_keep_exact_diagnostics(self):
        for name in ("saved_class_global_rebound", "inherited_classmethod_boundary", "custom_descriptor_boundary", "frame_observer_boundary"):
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(case=name, integer=integer):
                    result, _, _ = convert(name, integer)
                    with patch.object(effects.Registry, "canonical_classmethod", return_value=False), patch.object(effects.Registry, "class_parameter_attribute", return_value=False):
                        baseline, _, _ = convert(name, integer)
                    self.assertFalse(result.success)
                    normalize = lambda values: [(value.message, Path(value.filename).name, value.line,
                                                  value.column, value.code) for value in values]
                    self.assertEqual(normalize(result.diagnostics), normalize(baseline.diagnostics))
                    self.assertTrue(all(diagnostic.code == "E006" for diagnostic in result.diagnostics))


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ClassParameterContextExecution(unittest.TestCase):
    def exercise(self, name):
        with patch.dict(linked.CASES, {name: CASES[name]}):
            linked.ClassBindingContextExecution.exercise(self, name)

    def test_index_errors_and_source_frames(self):
        self.exercise("index_error_frames")

    def test_deleted_attribute_error_is_not_elided(self):
        self.exercise("deleted_attribute_error")

    def test_later_argument_mutates_current_attribute(self):
        self.exercise("argument_mutates_attribute")

    def test_saved_old_and_new_failed_import_class_generations(self):
        self.exercise("failed_import_actual_class_generation")

    def test_saved_starred_default_and_binding_error(self):
        self.exercise("saved_starred_default")

    def test_mixed_callback_family_keeps_other_target_globals(self):
        self.exercise("mixed_callable_family")

    def test_scalar_value_class_direct_payload(self):
        self.exercise("scalar_instance_classmethod")


if __name__ == "__main__":
    unittest.main()
