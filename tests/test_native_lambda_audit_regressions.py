"""Independent callback regressions; sources were frozen before conversion."""
import shutil
import unittest

import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeLambdaAuditRegressions(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_sorted_default_pop_cardinality(self):
        self.exercise('values=[7,8]\nresult=sorted(values,key=lambda item,discarded=values.pop():item)\nprint(result,values)\nprint(next(iter(range(len(result))),None))\n', ('',))

    def test_unbound_free_binding_error_frame(self):
        self.exercise('if int(input()):\n shift=2\nprint("prefix")\nprint(sorted([2,1],key=lambda item:item+shift))\n', ('0\n', '1\n'))

