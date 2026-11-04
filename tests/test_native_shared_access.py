"""Borrowed shared-list indexing preserves effects, identity and checked errors."""
import shutil
import unittest
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeSharedAccessTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_optional_shared_root(self):
        self.exercise("if int(input()):a=[[1,2]]\nprint('before')\nprint(a[0][-1])\n",('0\n', '1\n'))

    def test_nested_index_error_order(self):
        self.exercise("a=[[1],[2,3]]\ni=int(input())\nprint('before')\nprint(a[i//2][1//i])\n",('0\n', '2\n', '6\n', '-2\n'))

    def test_index_mutates_captured_row(self):
        self.exercise('a=[[7,0]]\nprint(a[0][a.pop().pop()],a)\n',('',))

    def test_rhs_mutates_owner_before_store(self):
        self.exercise('a=[[1,2],[3,4]]\na[0][-1]=a.pop().pop()\nprint(a)\n',('',))

    def test_augmented_rhs_mutation(self):
        self.exercise('a=[[10,20,30]]\na[0][-1]+=a[0].pop()\nprint(a)\n',('',))

    def test_pure_augmented_division_failure(self):
        self.exercise("a=[[1,2,3]]\ni=int(input())\nprint('before')\na[0][i]//=i\nprint(a)\n",('0\n', '1\n', '-1\n', '3\n'))
