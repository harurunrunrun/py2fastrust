"""Live builtin list traversal retains identity across source-side effects."""
import shutil
import unittest
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeLiveListTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_scalar_retype(self):
        self.exercise('x=3\ndel x\nx="text"\nprint(x)\n',('',))

    def test_scalar_double_delete(self):
        self.exercise('x=3\ndel x\nprint("before")\ndel x\n',('',))

    def test_list_alias(self):
        self.exercise('x=[1]\ny=x\ndel x\ny.append(2)\nprint(y)\n',('',))

    def test_branch(self):
        self.exercise('x=[1]\nif int(input()):del x\nprint(x)\n',('0\n', '1\n'))

    def test_none_branch(self):
        self.exercise('x=None\nif int(input()):del x\nprint(x)\n',('0\n', '1\n'))

    def test_local_read(self):
        self.exercise('def f():\n x=[1,2]\n del x\n print(x)\nf()\n',('',))

    def test_formal_rebind(self):
        self.exercise('def f(x):\n del x\n x=2\n print(x)\nx=[1]\nf(x)\nprint(x)\n',('',))

    def test_while_rebind(self):
        self.exercise('x=[1]\ni=0\nwhile i<4:\n print(x)\n del x\n x=[i]\n i+=1\nprint(x)\n',('',))

    def test_while_missing(self):
        self.exercise('x=[1]\ni=0\nwhile i<3:\n if i==1:\n  del x\n  i+=1\n  continue\n print(x)\n i+=1\n',('',))

    def test_tuple_order(self):
        self.exercise('a=[1]\nb=[2]\ndel (a,b)\nprint("done")\nprint(b)\n',('',))

    def test_repeated_target(self):
        self.exercise('a=[1]\ndel a,a\n',('',))

    def test_loop_deleted_then_rebound(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n del a\n a=[8]\n print(x,a)\nprint(a)\n',('',))
