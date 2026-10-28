"""Canonical set construction and order-insensitive exact-set sorting."""
import re
import shutil
import unittest

import test_native_iterator_reductions as helpers
from py2fastrust import transpile,TranspileOptions
from py2fastrust.aot import rust_mask


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeSetConsumerTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeIteratorReductionTests.tearDownClass.__func__)
    compile=helpers.NativeIteratorReductionTests.compile
    compare=helpers.NativeIteratorReductionTests.compare

    def exercise(self,source,inputs=("",),*,profiles=(True,),modes=("i64","i128","bigint"),unicode=False):
        for mode in modes:
            for release in profiles:
                with self.subTest(mode=mode,release=release):
                    compiled=self.compile(source,mode,release,string_mode="unicode"if unicode else"ascii")
                    for data in inputs:self.compare(compiled,data,mode=mode,trace=True)

    def test_integer_materialization_and_sorting_both_profiles(self):
        self.exercise('''values=list(map(int,input().split()))
print(sorted(set(values)),sorted(iter(set(values)),reverse=True))
''',("3 1 3 -2 1 4\n","\n","0 0 0\n"),profiles=(False,True))

    def test_all_generic_stream_producers_collect_without_intermediate_list(self):
        source='''print(sorted(set(range(8))))
print(sorted(set(x%3 for x in range(10) if x%2)))
print(sorted(set(map(int,input().split()))))
print(sorted(set(filter(None,[0,1,2,1,0]))))
print(sorted(set(enumerate("aba"))))
print(sorted(set(zip(range(4),reversed("abba")))))
'''
        self.exercise(source,("3 1 3 2\n",),profiles=(False,True))

    def test_unicode_string_keys_and_cached_native_values(self):
        self.exercise('''text=input()
print(sorted(set(text)),sorted(iter(set(text))))
print(sorted(set([text,"other",text])))
''',("猫α🦀猫é\n","\n","other\n"),unicode=True,profiles=(False,True))

    def test_bool_integer_key_identity_keeps_the_first_representative(self):
        self.exercise('''a=set([True,1,False,0,2])
b=set([1,True,0,False,2])
print(sorted(a),sorted(b))
print(len(a),True in a,1 in a,False in a,0 in a)
c=set([1])
c.add(True)
print(sorted(c))
''',profiles=(False,True))

    def test_tuple_keys_preserve_recursive_numeric_equality(self):
        self.exercise('''values=[(True,"x"),(1,"x"),(False,"y"),(0,"y"),(2,"z")]
print(sorted(set(values)))
print(sorted(set((x%3,x%2) for x in range(12))))
print(sorted(set(((x%2,"s"),x%3) for x in range(9))))
''')

    def test_set_comprehensions_use_the_same_scope_and_collection_plan(self):
        self.exercise('''x="outside"
print(sorted({x%3 for x in range(10) if x%2}))
print(sorted({(a,b) for a in range(3) for b in "aba" if a!=1}))
print(x)
print(sorted({int(input()) for i in range(3)}))
''',("3\n1\n3\n","3\nbad\n1\n"),profiles=(False,True))

    def test_dictionary_keys_values_and_items_materialize_through_shared_stream(self):
        self.exercise('''d={3:7,1:7,2:9}
print(sorted(set(d)),sorted(set(d.keys())))
print(sorted(set(d.values())),sorted(set(d.items())))
e={(1,"x"):"first",(2,"y"):"last"}
print(sorted(set(e)),sorted(set(e.values())))
''')

    def test_empty_constructors_and_solved_key_epochs(self):
        self.exercise('''print(sorted(set()),sorted(set([])),sorted(set(())))
print(sorted(set(iter(()))),sorted(set(set())))
s=set()
for i in range(int(input())):
 s.add((i%2,"x"))
print(sorted(s),len(s),bool(s))
''',("0\n","4\n"),profiles=(False,True))

    def test_constructor_aliases_and_real_builtin_shadowing(self):
        self.exercise('''build=set
again=build
set=range
print(sorted(build([3,1,3])),sorted(again("caba")))
print(sorted(set(3)))
def count(values):
 return len(build(values))
print(count([1,1,2,3]))
''',profiles=(False,True))

    def test_functions_create_and_return_unique_owned_sets(self):
        self.exercise('''def unique(values):
 return set(values)
def ordered(values):
 return sorted(set(values))
a=unique([3,1,3])
b=set(a)
b.add(7)
print(sorted(a),sorted(b),ordered([5,1,5,3]))
''')

    def test_source_constructor_completes_before_sorted_keyword_evaluation(self):
        self.exercise('''def mark(value):
 print(value,end="|")
 return value
def keynone():
 print("key",end="|")
 return None
print(sorted(set(mark(int(input())) for i in range(3)),reverse=mark(True),key=keynone()))
print(input())
''',("2\n1\n2\nlast\n","2\nbad\n9\nlast\n"),profiles=(False,True))

    def test_key_none_aliases_and_unbound_reads_keep_argument_order(self):
        self.exercise('''if int(input()):
 key=None
print("prefix",end="|")
print(sorted(set([3,1]),key=key))
''',("0\n","1\n"))

    def test_reverse_truth_runs_after_every_argument_is_evaluated(self):
        for value in ('"bad"','None'):
            self.exercise('''def mark(value):
 print(value,end="|")
 return value
def keynone():
 print("key",end="|")
 return None
print(sorted(set([3,1]),reverse=mark('''+value+'''),key=keynone()))
''',profiles=(False,True))

    def test_large_bigint_hashes_and_comparisons_use_exact_values(self):
        self.exercise('''values=[1<<180,-(1<<180),1<<180,1<<129,True,1]
s=set(values)
print(sorted(s),len(s),(1<<180) in s)
''',modes=("bigint",),profiles=(False,True))

    def test_order_permission_does_not_cross_callbacks_or_positional_adapters(self):
        # These remain explicit proof boundaries. They are not accepted as
        # successful conversions or included in feature acceptance counts.
        sources=(
            'def f(x):\n print(x)\n return x\nprint(sorted(map(f,{1,2})))\n',
            'def f(x):\n print(x)\n return x\nprint(sorted(filter(f,{1,2})))\n',
            'print(sorted(enumerate({1,2})))\n',
            'print(sorted(zip({1,2},range(2))))\n',
            'print(sorted((x for x in {1,2})))\n',
            'print(sorted({-1,1},key=abs))\n',
        )
        for mode in("i64","i128","bigint"):
            for source in sources:
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")

    def test_mutable_aliases_are_never_implemented_as_silent_copies(self):
        source='s=set([1,2])\nt=s\nt.add(3)\nprint(len(s))\n'
        for mode in("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")

    def test_constructor_identity_and_arity_cannot_reenter_spelling_dispatch(self):
        for mode in("i64","i128","bigint"):
            for source in(
                'set=range\nprint(set())\n',
                'build=set\nprint(build(1,2))\n',
                'build=set\nprint(build(iterable=[1,2]))\n',
                'if int(input()):\n build=set\nprint(build([1]))\n',
                'build=int(input())\nprint(build([1]))\n',
            ):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
