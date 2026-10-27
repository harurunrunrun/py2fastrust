"""Canonical extrema over ordinary typed values preserve Python call semantics."""
import shutil
import tempfile
import unittest

import test_native_iterator_reductions as helpers


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativePositionalExtremaTests(unittest.TestCase):
    compile=helpers.NativeIteratorReductionTests.compile
    compare=helpers.NativeIteratorReductionTests.compare

    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="pytors-positional-extrema-")
        cls.counter=0

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def check(self,source,data="",*,debug=False,trace=False,string_mode="ascii",modes=("i64","i128","bigint")):
        for integer in modes:
            for release in ((False,True) if debug else (True,)):
                with self.subTest(integer=integer,release=release):
                    compiled=self.compile(source,integer,release=release,string_mode=string_mode)
                    self.compare(compiled,data,trace=trace)

    def test_nested_tuple_order_and_first_numeric_ties_in_both_profiles(self):
        self.check('''
print(min((2,(3,8)),(2,(3,4)),(5,(0,0))))
print(max((False,),(0,)),max((0,),(False,)))
print(min((True,7),(1,7)),min((1,7),(True,7)))
print(min((b"ab",4),(b"abc",0)),max(("a",2),("z",0)))
''',debug=True)

    def test_proven_aliases_and_shadowed_builtin_names_use_canonical_identity(self):
        self.check('''
choose=min
min=max
print(choose((3,8),(3,2)),min((2,7),(4,0),key=None))
''')

    def test_all_arguments_run_before_comparison_exception(self):
        self.check('''
def mark(tag,value):
 print(tag,end="|")
 return value
print(min(mark("a",(1,None)),mark("b",(1,3)),mark("c",(0,4))))
''',debug=True,trace=True)

    def test_shadowed_extremum_spelling_does_not_invoke_extremum_dispatch(self):
        self.check('''
smallest=min
min=range
print(sum(min(4)))
min=input
print(min())
print(smallest(2,1))
''',"value\n")

    def test_tuple_snapshot_is_captured_before_later_mutation(self):
        self.check('''
items=[(1,9),(1,2),(0,5)]
print(min(items[0],items.pop(),items[0]))
print(items)
''',debug=True)

    def test_string_bytes_and_integer_extrema_share_argument_lowering(self):
        self.check('''
print(min("z","ab","é",key=None),max(b"ab",b"abc"))
print(max(False,0),max(0,False),min(True,1),min(1,True))
''',string_mode="unicode")

    def test_fixed_width_float_and_nan_first_candidate_is_kept(self):
        self.check('''
value=float(input())
print(min(1.5,3.5,0.5),max(1.5,3.5,0.5))
print(min(value,1.0),min(1.0,value))
print(max(value,1.0),max(1.0,value))
''',"nan\n",modes=("i64","i128"))

    def test_argument_exception_follows_preceding_argument_effects(self):
        self.check('''
def mark(value):
 print(value,end="|")
 return (value,value)
print(min(mark(1),(int(input()),0),mark(2)))
''',"invalid\n",trace=True)


if __name__=="__main__":unittest.main()
