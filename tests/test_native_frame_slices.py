"""Shared sequence slices keep source evaluation order and shallow identity."""
import shutil
import unittest
import test_native_union_ordering as helpers
from py2fastrust import transpile


class FrameSliceProofTests(unittest.TestCase):
    def test_custom_index_protocol_is_named_in_diagnostic(self):
        source="class Index:\n def __index__(self):return 1\nclass Box:\n def __init__(self):self.a=[1,2]\n def f(self):return self.a[Index():]\nprint(Box().f())\n"
        result=transpile(source)
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('__index__',str(result.diagnostics[0]))

    def test_unused_slice_support_is_not_emitted(self):
        result=transpile('a=[1,2,3]\nprint(sum(a))\n')
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('NativeSlice',result.rust_source)
        self.assertNotIn('native_slice_indices',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrameSliceExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_global_list_reverse(self):
        self.exercise('a=[1,2,3,4]\ndef f():return a[::-1]\nprint(f(),a)\n',("",))

    def test_global_list_stride(self):
        self.exercise('a=[1,2,3,4,5]\ndef f():return a[-100:100:2]\nprint(f())\n',("",))

    def test_global_list_empty(self):
        self.exercise('a=[]\ndef f():return a[::-1]\nprint(f())\n',("",))

    def test_global_string_reverse(self):
        self.exercise('s="abcdef"\ndef f():return s[::-1]\nprint(f())\n',("",))

    def test_global_bytes_reverse(self):
        self.exercise('s=b"abcdef"\ndef f():return s[4:0:-2]\nprint(f())\n',("",))

    def test_bound_effect_order(self):
        self.exercise('a=[1,2,3,4]\ndef bound(tag,x):\n print(tag,end="|")\n return x\ndef owner():\n print("owner",end="|")\n return a\ndef f():return owner()[bound("start",1):bound("stop",4):bound("step",2)]\nprint(f())\n',("",))

    def test_shallow_list_identity(self):
        self.exercise('a=[[1],[2],[3]]\ndef f():return a[::-1]\nb=f()\nb[0].append(9)\nprint(a,b,a is b,a[2] is b[0])\n',("",))

    def test_slice_before_mutation(self):
        self.exercise('a=[1,2,3,4]\ndef bound():\n a.append(5)\n return 5\ndef f():return a[0:bound()]\nprint(f(),a)\n',("",))

    def test_slice_before_rebinding(self):
        self.exercise('a=[1,2,3]\ndef bound():\n global a\n a=[8,9]\n return 3\ndef f():return a[:bound()]\nprint(f(),a)\n',("",))

    def test_invalid_list_bound(self):
        self.exercise('a=[1,2]\ndef f():return a["x":]\nprint(f())\n',("",))

    def test_invalid_string_bound(self):
        self.exercise('a="abc"\ndef f():return a[1.5:]\nprint(f())\n',("",))

    def test_invalid_bytes_bound(self):
        self.exercise('a=b"abc"\ndef f():return a[[]:]\nprint(f())\n',("",))

    def test_zero_step(self):
        self.exercise('a=[1,2,3]\ndef f():return a[1:3:0]\nprint(f())\n',("",))

    def test_bounds_none_bool(self):
        self.exercise('a=[1,2,3,4]\ndef f():return a[True:None:True]\nprint(f())\n',("",))

    def test_wide_bounds(self):
        self.exercise('a=[1,2,3,4]\ndef f():return a[-(1<<60):1<<60:-(1<<60)]\nprint(f())\n',("",))

    def test_class_list_slice(self):
        self.exercise('class Box:\n def __init__(self):self.a=[2,4,6,8]\n def selected(self):return self.a[1::2]\nb=Box()\nprint(b.selected(),b.a)\n',("",))

    def test_class_bytes_slice(self):
        self.exercise('class Box:\n def __init__(self):self.a=b"banana"\n def selected(self):return self.a[::2]\nprint(Box().selected())\n',("",))

    def test_union_sequence_slice(self):
        self.exercise('def selected(flag):\n if flag:a=[1,2,3]\n else:a="abc"\n return a[::-1]\nprint(selected(True),selected(False))\n',("",))

    def test_nonsequence_slice(self):
        self.exercise('a=3\ndef f():return a[:]\nprint(f())\n',("",))

    def test_pending_sort_key(self):
        self.exercise('def order(s):return sorted(range(len(s)),key=lambda i:s[i:])\ndef values(s,positions):\n if isinstance(s,str):s=[ord(c) for c in s]\n return [s[i] for i in positions]\ns="banana"\nprint(values(s,order(s)))\n',("",))

    def test_runtime_tuple_reverse(self):
        self.exercise('def f(*a):return a[::-1]\nprint(f(1,2,3),f())\n',("",))

    def test_runtime_tuple_identity(self):
        self.exercise('def f(*a):return a[1:]\na=[2]\nb=f([1],a)\nb[0].append(7)\nprint(a,b[0] is a)\n',("",))

    def test_empty_full_slice(self):
        self.exercise('s=""\ndef f():return s[::-1]\nprint(f())\n',("",))

    def test_bound_union(self):
        self.exercise('a=[1,2,3,4]\ndef f(flag):\n if flag:b=1\n else:b=None\n return a[b:]\nprint(f(True),f(False))\n',("",))

    def test_bound_noniterable(self):
        self.exercise('a=[1,2]\ndef f(flag):\n if flag:b=None\n else:b="x"\n return a[b:]\nprint(f(True))\nprint(f(False))\n',("",))

    def test_unicode_reverse(self):
        self.exercise('s="α😀β日"\ndef f():return s[::-1]\nprint(f(),len(f()))\n',("",), string_mode='unicode')

    def test_unicode_stride(self):
        self.exercise('s="α😀β日"\ndef f():return s[1::2]\nprint(f(),len(f()))\n',("",), string_mode='unicode')

    def test_unicode_negative(self):
        self.exercise('s="α😀β日"\ndef f():return s[-1:-5:-2]\nprint(f())\n',("",), string_mode='unicode')

    def test_bytes_high_values(self):
        self.exercise('s=b"\\x00\\x80\\xffA"\ndef f():return s[::-1]\nprint(f())\n',("",), string_mode='unicode')

    def test_huge_bounds(self):
        self.exercise('a=[1,2,3]\ndef f():return a[-10**100:10**100]\nprint(f())\n',("",), modes=('bigint',))

    def test_huge_positive_step(self):
        self.exercise('a=[1,2,3]\ndef f():return a[::10**100]\nprint(f())\n',("",), modes=('bigint',))

    def test_huge_negative_step(self):
        self.exercise('a=[1,2,3]\ndef f():return a[::-10**100]\nprint(f())\n',("",), modes=('bigint',))
