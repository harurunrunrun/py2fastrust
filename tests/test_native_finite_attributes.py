"""Finite instance data attributes preserve lookup/store errors and owner capture."""
import shutil
import unittest
import test_native_union_ordering as helpers
from py2fastrust import transpile


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FiniteAttributeExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_optional_read(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\na=choose(int(input()))\nprint(a.n)\n',('0\n', '1\n'))

    def test_optional_write(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\na=choose(int(input()))\na.n=9\nprint(a.n)\n',('0\n', '1\n'))

    def test_optional_augmented(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\na=choose(int(input()))\na.n+=3\nprint(a.n)\n',('0\n', '1\n'))

    def test_nested_optional_field(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\nclass Owner:\n def __init__(self,x):self.x=x\no=Owner(Box(7))\nprint(o.x.n)\no=Owner(None)\nprint(o.x.n)\n',('',))

    def test_two_instance_kinds(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\nclass Label:\n def __init__(self,n):self.n=n\ndef f(flag):\n if flag:return Box(7)\n return Label("abc")\nprint(f(True).n,f(False).n)\n',('',))

    def test_write_two_instance_kinds(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\nclass Label:\n def __init__(self,n):self.n=n\ndef f(flag):\n if flag:return Box(7)\n return Label(3)\na=f(int(input()))\na.n=9\nprint(a.n)\n',('0\n', '1\n'))

    def test_none_read_retains_prior_effects(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\nprint("before",end="|")\na=choose(0)\nprint(a.n)\n',('',))

    def test_store_rhs_precedes_attribute_error(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\ndef rhs():\n print("rhs",end="|")\n return 9\na=choose(0)\na.n=rhs()\n',('',))

    def test_augmented_lookup_precedes_rhs(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\ndef rhs():\n print("rhs",end="|")\n return 9\na=choose(int(input()))\na.n+=rhs()\nprint(a.n)\n',('0\n', '1\n'))

    def test_augmented_owner_is_captured(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\na=choose(1)\nold=a\ndef rhs():\n global a\n a=Box(9)\n return 2\na.n+=rhs()\nprint(a.n,old.n)\n',('',))

    def test_assignment_owner_follows_rhs(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return None\na=choose(0)\ndef rhs():\n global a\n a=Box(9)\n return 2\na.n=rhs()\nprint(a.n)\n',('',))

    def test_list_payload_identity(self):
        self.exercise('class Box:\n def __init__(self):self.items=[]\ndef choose(flag):\n if flag:return Box()\n return None\na=choose(1)\nb=a.items\nb.append(3)\nprint(a.items,b is a.items)\n',('',))

    def test_missing_instance_attribute(self):
        self.exercise('class Box:\n def __init__(self):self.n=3\ndef choose(flag):\n if flag:return Box()\n return None\na=choose(int(input()))\nprint(a.missing)\n',('0\n', '1\n'))

    def test_primitive_absent_attribute(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef choose(flag):\n if flag:return Box(7)\n return 3\nprint(choose(int(input())).n)\n',('0\n', '1\n'))


class FiniteAttributeCapabilityTests(unittest.TestCase):
    def test_existing_builtin_attribute_is_never_fabricated_as_missing(self):
        result=transpile('class Box:\n def __init__(self):self.real=3\ndef choose(flag):\n if flag:return Box()\n return 5\nprint(choose(int(input())).real)\n')
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('real',str(result.diagnostics[0]))
        self.assertIn('builtin descriptor',str(result.diagnostics[0]))
