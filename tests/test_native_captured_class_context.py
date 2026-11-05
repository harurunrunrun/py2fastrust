"""Reuse actual source operator lookup captures without replaying metadata."""
import unittest
from unittest.mock import patch
import test_native_class_binding_contexts as binding_tests
from py2fastrust import native_class_binding_contexts as contexts

CASES = {'linked_arithmetic_factory': ({'main.py': 'from amounts import Amount\n'
                                           'import sys\n'
                                           'def main():\n'
                                           '    a, b = map(int, sys.stdin.readline().split())\n'
                                           '    left, right = Amount(a), Amount(b)\n'
                                           '    print((left - right).value, (left - 3).value, '
                                           '(-left).value, left < right)\n'
                                           'main()\n',
                                'amounts.py': 'class Amount:\n'
                                              '    def __init__(self, value):\n'
                                              '        self.value = value\n'
                                              '    def __sub__(self, other):\n'
                                              '        if isinstance(other, Amount):\n'
                                              '            return create(self.value - '
                                              'other.value)\n'
                                              '        return create(self.value - other)\n'
                                              '    def __neg__(self):\n'
                                              '        return create(-self.value)\n'
                                              '    def __lt__(self, other):\n'
                                              '        return self.value < other.value\n'
                                              'def create(value):\n'
                                              '    result = Amount(0)\n'
                                              '    result.value = value\n'
                                              '    return result\n'},
                               ['9 4\n', '-3 5\n']),
 'operand_and_method_events': ({'main.py': 'class Count:\n'
                                           '    def __init__(self, value):\n'
                                           '        self.value = value\n'
                                           '    def __sub__(self, other, fee=2):\n'
                                           '        print("sub", self.value, other.value, fee)\n'
                                           '        return Count(self.value - other.value - fee)\n'
                                           '    def __neg__(self):\n'
                                           '        print("neg", self.value)\n'
                                           '        return Count(-self.value)\n'
                                           '    def __lt__(self, other):\n'
                                           '        print("less", self.value, other.value)\n'
                                           '        return self.value < other.value\n'
                                           'def read(label):\n'
                                           '    print(label)\n'
                                           '    return Count(int(input()))\n'
                                           'def main():\n'
                                           '    result = read("left") - read("right")\n'
                                           '    print((-result).value, result < Count(0))\n'
                                           'main()\n'},
                               ['9\n3\n', 'bad\n3\n']),
 'reflected_and_not_implemented': ({'main.py': 'class Left:\n'
                                               '    def __init__(self, value):\n'
                                               '        self.value = value\n'
                                               '    def __sub__(self, other):\n'
                                               '        print("left-sub", self.value)\n'
                                               '        return NotImplemented\n'
                                               'class Right:\n'
                                               '    def __init__(self, value):\n'
                                               '        self.value = value\n'
                                               '    def __rsub__(self, other):\n'
                                               '        print("right-rsub", self.value)\n'
                                               '        return other.value - self.value\n'
                                               'def main():\n'
                                               '    value = int(input())\n'
                                               '    print(Left(value) - Right(4))\n'
                                               'main()\n'},
                                   ['13\n']),
 'linked_numeric_error_order': ({'main.py': 'from quotient import Quotient\n'
                                            'def operand(label):\n'
                                            '    print(label)\n'
                                            '    return Quotient(int(input()))\n'
                                            'def main():\n'
                                            '    print((operand("numerator") // '
                                            'operand("denominator")).value)\n'
                                            'main()\n',
                                 'quotient.py': 'class Quotient:\n'
                                                '    def __init__(self, value):\n'
                                                '        self.value = value\n'
                                                '    def __floordiv__(self, other):\n'
                                                '        print("divide", self.value, other.value)\n'
                                                '        return Quotient(self.value // '
                                                'other.value)\n'},
                                ['11\n3\n', '11\n0\n', '11\nbad\n']),
 'rebound_export_saved_instances': ({'main.py': 'import measures\n'
                                                'from measures import Measure as Original\n'
                                                'def main():\n'
                                                '    first, second = Original(17), Original(5)\n'
                                                '    measures.Measure = 0\n'
                                                '    print(first - second)\n'
                                                'main()\n',
                                     'measures.py': 'class Measure:\n'
                                                    '    def __init__(self, value):\n'
                                                    '        self.value = value\n'
                                                    '    def __sub__(self, other):\n'
                                                    '        print("saved", self.value, '
                                                    'other.value)\n'
                                                    '        return self.value - other.value\n'},
                                    [''])}


class CapturedClassContextProofs(unittest.TestCase):
    def observe(self, name, integer="i64", files=None):
        seen = []
        original = contexts.CapturedClassContext.argument
        def observe(capture, model, plan, owner):
            result = original(capture, model, plan, owner)
            seen.append((model.class_binding_contexts.source(plan).node.name, result))
            return result
        with patch.object(contexts.CapturedClassContext, "argument", new=observe):
            result, facts = binding_tests.convert_project(CASES[name][0] if files is None else files, integer)
        self.assertTrue(result.success, result.diagnostics)
        return result, seen

    def test_original_linked_numeric_method_reuses_actual_capture(self):
        for integer in ("i64", "i128"):
            with self.subTest(integer=integer):
                result, seen = self.observe("linked_numeric_error_order", integer)
                self.assertTrue({"__floordiv__"} <=
                                {name for name, argument in seen if argument is not None}, seen)
                self.assertIn("class_defining_class:&ClassClassRef", result.rust_source)

    def test_existing_operator_and_factory_entry_reuses_actual_capture(self):
        for integer in ("i64", "i128"):
            with self.subTest(integer=integer):
                result, seen = self.observe("existing_factory", integer,
                                           binding_tests.CASES["linked_factory_forward"][0])
                self.assertIn("__sub__", {name for name, argument in seen if argument is not None}, seen)

    def test_rebound_export_does_not_gain_a_static_class_context(self):
        result, seen = self.observe("rebound_export_saved_instances")
        self.assertFalse([argument for _, argument in seen if argument is not None], seen)

    def test_direct_constructor_choice_tracks_current_callable_alternatives(self):
        import ast
        from py2fastrust.native_classes import shape
        from py2fastrust.native_types import UnionType
        original = contexts.prepare
        observed = []
        def observe(model):
            original(model)
            nodes = {id(node): node for node in model.iter_nodes()}
            for point in model.callable_cells.sites:
                plan, identity = point
                node = nodes.get(identity)
                if not isinstance(node, ast.Call):
                    continue
                cell = model.records.get((plan, id(node.func)))
                if cell is not None and isinstance(shape(cell), UnionType):
                    observed.append(point)
                    self.assertNotIn(point, model.module_linker.class_calls)
        with patch.object(contexts, "prepare", side_effect=observe):
            result, _ = binding_tests.convert_project(CASES["rebound_export_saved_instances"][0])
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(observed)


@unittest.skipUnless(binding_tests.shutil.which("rustc"), "rustc is required")
class CapturedClassContextExecution(unittest.TestCase):
    def exercise(self, name):
        # Reuse the established strict stdout/status/original-frame harness.
        with patch.dict(binding_tests.CASES, CASES):
            binding_tests.ClassBindingContextExecution.exercise(self, name)

    def test_binary_unary_comparison_and_forwarded_factory(self):
        self.exercise("linked_arithmetic_factory")

    def test_operand_order_method_effects_and_original_defaults(self):
        self.exercise("operand_and_method_events")

    def test_reflected_not_implemented_phase(self):
        self.exercise("reflected_and_not_implemented")

    def test_linked_division_and_input_errors(self):
        self.exercise("linked_numeric_error_order")

    def test_saved_instances_after_export_rebinding(self):
        self.exercise("rebound_export_saved_instances")


if __name__ == "__main__":
    unittest.main()
