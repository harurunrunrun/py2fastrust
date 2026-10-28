"""Frozen independent regressions for replayed lowering and result cardinality."""
import shutil
import unittest

from py2fastrust import TranspileOptions,transpile
import test_native_union_ordering as helpers


CASES = {
    'assignment_default_pop_n0': 'values=[]\nprint("before")\nresult=sorted(values,key=lambda item,discarded=values.pop():item)\nprint(result,values)\nprint(next(iter(range(len(result))),None),next(iter(range(len(values))),None))\n',
    'direct_print_default_pop_n0': 'values=[]\nprint("before")\nprint(sorted(values,key=lambda item,discarded=values.pop():item),values)\nprint(next(iter(range(len(values))),None))\n',
    'nested_print_default_pop_n0': 'values=[]\nprint("before")\nprint(next(iter(range(len(sorted(values,key=lambda item,discarded=values.pop():item)))),None))\nprint(values,next(iter(range(len(values))),None))\n',
    'ordinary_pop_assignment_n0': 'values=[]\nprint("before")\nresult=values.pop()\nprint(result,values)\nprint(next(iter(range(len(values))),None))\n',
    'immediate_default_pop_n0': 'values=[]\nprint("before")\nresult=(lambda discarded=values.pop():len(values))()\nprint(result,values)\nprint(next(iter(range(result)),None),next(iter(range(len(values))),None))\n',
    'assignment_default_pop_n1': 'values=[7]\nprint("before")\nresult=sorted(values,key=lambda item,discarded=values.pop():item)\nprint(result,values)\nprint(next(iter(range(len(result))),None),next(iter(range(len(values))),None))\n',
    'direct_print_default_pop_n1': 'values=[7]\nprint("before")\nprint(sorted(values,key=lambda item,discarded=values.pop():item),values)\nprint(next(iter(range(len(values))),None))\n',
    'nested_print_default_pop_n1': 'values=[7]\nprint("before")\nprint(next(iter(range(len(sorted(values,key=lambda item,discarded=values.pop():item)))),None))\nprint(values,next(iter(range(len(values))),None))\n',
    'ordinary_pop_assignment_n1': 'values=[7]\nprint("before")\nresult=values.pop()\nprint(result,values)\nprint(next(iter(range(len(values))),None))\n',
    'immediate_default_pop_n1': 'values=[7]\nprint("before")\nresult=(lambda discarded=values.pop():len(values))()\nprint(result,values)\nprint(next(iter(range(result)),None),next(iter(range(len(values))),None))\n',
    'assignment_default_pop_n2': 'values=[7,8]\nprint("before")\nresult=sorted(values,key=lambda item,discarded=values.pop():item)\nprint(result,values)\nprint(next(iter(range(len(result))),None),next(iter(range(len(values))),None))\n',
    'direct_print_default_pop_n2': 'values=[7,8]\nprint("before")\nprint(sorted(values,key=lambda item,discarded=values.pop():item),values)\nprint(next(iter(range(len(values))),None))\n',
    'nested_print_default_pop_n2': 'values=[7,8]\nprint("before")\nprint(next(iter(range(len(sorted(values,key=lambda item,discarded=values.pop():item)))),None))\nprint(values,next(iter(range(len(values))),None))\n',
    'ordinary_pop_assignment_n2': 'values=[7,8]\nprint("before")\nresult=values.pop()\nprint(result,values)\nprint(next(iter(range(len(values))),None))\n',
    'immediate_default_pop_n2': 'values=[7,8]\nprint("before")\nresult=(lambda discarded=values.pop():len(values))()\nprint(result,values)\nprint(next(iter(range(result)),None),next(iter(range(len(values))),None))\n',
    'row_print_then_parent_clear_literal_index': 'rows=[[1,2],[3]]\nprint(rows[0],rows.clear())\n',
    'row_print_then_parent_clear_dynamic_index': 'rows=[[1,2],[3]]\nindex=0\nprint(rows[index],rows.clear())\n',
}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeLambdaReplayRegressions(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_assignment_and_print_default_effects_keep_both_container_lengths(self):
        for family in ("assignment_default_pop","direct_print_default_pop","nested_print_default_pop"):
            for size in range(3):
                with self.subTest(family=family,size=size):
                    self.exercise(CASES[f"{family}_n{size}"],("",))

    def test_non_sort_assignment_and_immediate_defaults_also_run_once(self):
        for family in ("ordinary_pop_assignment","immediate_default_pop"):
            for size in range(3):
                with self.subTest(family=family,size=size):
                    self.exercise(CASES[f"{family}_n{size}"],("",))

    def test_unique_row_views_reject_later_parent_destruction(self):
        # These remain unfinished object-identity support, not language acceptance.
        for name in ("row_print_then_parent_clear_literal_index","row_print_then_parent_clear_dynamic_index"):
            for mode in ("i64","i128","bigint"):
                result=transpile(CASES[name],TranspileOptions(integer=mode))
                self.assertFalse(result.success,(name,mode))
                self.assertEqual(result.diagnostics[0].code,"E006")
