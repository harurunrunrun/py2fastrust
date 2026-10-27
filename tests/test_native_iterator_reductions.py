"""Typed iterator consumers preserve construction, laziness and scope."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.aot import rust_mask
from py2fastrust.native import try_generate_native
from wrapping_reference import execute


REPORTED = '''N=int(input())
A=list(map(int,input().split()))
ans=sum(a%2==1 for a in A)
print(ans)
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeIteratorReductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-native-reductions-")
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compile(self, source, mode="i64", release=True, prune=True):
        source = textwrap.dedent(source)
        result = transpile(source, TranspileOptions(integer=mode, filename="case.py", optimize=prune))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, "native", source)
        rust = result.rust_source
        self.assertLess(len(rust.encode()), 512*1024)
        self.assertIsNone(re.search(r"\benum\s+(?:Value|Op)\b|\bstruct\s+(?:Runtime|PegParser)\b|\bfn\s+step\b", rust_mask(rust)))
        type(self).counter += 1
        target = Path(self.directory.name, f"program{self.counter}.rs")
        target.write_text(rust)
        binary = target.with_suffix("")
        compiled = subprocess.run(["rustc", "--edition=2021", *(["-O"] if release else []),
                                   str(target), "-o", str(binary)], capture_output=True, text=True, timeout=120)
        self.assertEqual(compiled.returncode, 0, compiled.stderr + "\n" + source)
        return source, binary, rust

    def compare(self, compiled, data="", *, mode="i64", wrapping=False, trace=False):
        source, binary, _ = compiled
        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=10)
        expected = (execute(source, mode, data) if wrapping else
                    subprocess.run([sys.executable, "-I", "-c", source], input=data,
                                   capture_output=True, text=True, timeout=10))
        self.assertEqual(actual.stdout, expected.stdout, source + "\n" + data)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
        if actual.returncode:
            kind = expected.exception_type if wrapping else expected.stderr.splitlines()[-1].split(":")[0]
            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0], kind)
            if trace:
                pattern = r'File "[^"]+", line (\d+), in ([^\n]+)'
                self.assertEqual(re.findall(pattern, actual.stderr), re.findall(pattern, expected.stderr))

    def differential(self, source, inputs=("",), modes=("i64", "i128"), **options):
        for mode in modes:
            compiled = self.compile(source, mode)
            for data in inputs:
                with self.subTest(mode=mode, data=data):
                    self.compare(compiled, data, mode=mode, **options)

    def test_reported_predicate_count_is_compact_in_both_profiles(self):
        for mode in ("i64", "i128"):
            for release in (False, True):
                compiled = self.compile(REPORTED, mode, release)
                main = compiled[2][compiled[2].rfind("fn main()"):]
                # The one source list is input; the generator itself creates no list.
                self.assertNotIn("Vec::new()", main)
                self.assertNotIn(".collect", main)
                for data in ("0\n\n", "6\n1 2 3 4 5 6\n", "3\n-3 0 -2\n", "1\n1_001\n"):
                    self.compare(compiled, data)

    def test_nested_clauses_filters_and_generator_scope(self):
        self.differential('''
            i=99
            values=[1,2,3,4]
            print(sum(i*j+k for i in values if i%2 for j in range(i+1) if j%2==0 for k in (True,False)))
            print(i, sum(x+y for x in [1,2] for y in (3,4)))
            print(sum(x for x in (y*y for y in range(5) if y%2)))
        ''')

    def test_outer_construction_then_start_then_lazy_body(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print(sum((mark(x) for x in range(mark(3))),mark(10)))
            print(sum((mark(x) for x in [mark(1),mark(2)]),start=mark(20)))
            print(min((mark(x) for x in range(mark(2))),default=mark(30)))
        ''')

    def test_short_circuit_any_all_and_empty_identities(self):
        self.differential('''
            print(any(int(input()) for i in range(3)),int(input()))
            print(all(int(input()) for i in range(3)),int(input()))
            print(any(int(input()) for i in range(0)),all(int(input()) for i in range(0)))
            print(any(()),all([]),any(range(2)),all(range(2)))
        ''', ("0\n1\n91\n1\n0\n92\n", "1\n71\n0\n72\n"))

    def test_nested_short_circuit_does_not_visit_later_sources(self):
        self.differential('''
            def item(value):
                print(value,end="|")
                return value
            print(any(item(x+y) for x in range(2) for y in range(3)))
            print(all(item(x+y) for x in range(2) for y in range(3)))
            print(any(x for x in (item(y) for y in range(3))))
        ''')

    def test_dictionary_views_items_and_owned_temporary_sources(self):
        self.differential('''
            d={1:2,3:4,5:6}
            print(sum(k*v for k,v in d.items()))
            print(sum(d),sum(d.values()),any(v>4 for v in d.values()),all(k%2 for k in d.keys()))
            print(max(k-v for k,v in {1:7,2:4}.items()))
            print(sum(sum(row) for row in [[1,2],[],[3]]))
        ''')

    def test_deques_and_plain_container_start_mutation_order(self):
        self.differential('''
            from collections import deque
            q=deque([1,2,3])
            print(sum(x for x in q),min(x for x in q),max(x for x in q))
            print(sum(q,q.popleft()),len(q),sum(q))
            print(any(x>1 for x in q),all(x for x in q))
        ''')

    def test_bool_integer_ties_and_empty_bool_start(self):
        self.differential('''
            print(min(x for x in (True,1)),min(x for x in (1,True)))
            print(max(x for x in (False,0)),max(x for x in (0,False)))
            print(sum((x for x in []),True),sum((x for x in [False]),True),sum((x for x in [1]),False))
            print(min((x for x in []),default=True),max((x for x in ()),default=7))
        ''')

    def test_defaults_are_eager_and_generator_values_are_lazy(self):
        source = '''n=int(input())
print(min((int(input()) for i in range(n)),default=int(input())))
print(int(input()))
'''
        self.differential(source, ("0\n90\n91\n", "2\n90\n7\n3\n91\n"))

    def test_range_construction_errors_precede_later_arguments(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print("ready")
            print(sum((x for x in range(mark(0),mark(3),mark(0))),mark(99)))
        ''', trace=True)

    def test_map_filter_and_enumerate_feed_typed_consumers(self):
        self.differential('''
            def square(value):
                return value*value
            def odd(value):
                return value%2==1
            a=[0,1,2,3,4]
            print(sum(map(square,a)),sum(filter(odd,a)),sum(filter(None,a)))
            print(sum(i*x for i,x in enumerate(a,7)))
            print(any(map(odd,a)),all(map(square,a)),max(map(square,a)))
        ''')

    def test_zip_leaf_iterators_unpack_and_stop_at_shortest(self):
        self.differential('''
            a=[1,2,3]
            b=[4,5]
            print(sum(x*y for x,y in zip(a,b)))
            print(sum(x+y+z for x,y,z in zip(a,b,range(5))))
            print(sum(x+y for x,y in filter(None,zip(a,b))))
            print(any(zip([0])),all(zip([0])))
            print(any((x,) for x in [0]),all(() for x in [1]))
        ''')

    def test_zip_evaluates_arguments_before_creating_container_iterators(self):
        self.differential('''
            from collections import deque
            q=deque([2,3,4])
            print(sum(x+y for x,y in zip(q,range(q.popleft()))),len(q))
            print(sum(int(x)+int(y) for x,y in zip(input().split(),input().split())))
            print(int(input()))
        ''', ("1 2 3\n4 5\n99\n", "\n4 5\n77\n"))

    def test_input_split_map_conversion_is_deferred_until_consumed(self):
        self.differential('''
            def start():
                print("start",end="|")
                return int(input())
            print(sum(map(int,input().split()),start()))
            print(any(map(int,input().split())),int(input()))
        ''', ("1 2 3\n10\n0 1 invalid\n91\n", "bad 2\n10\n", "\n7\n0 0\n92\n"))

    def test_generator_input_words_and_scalar_extrema(self):
        self.differential('''
            print(sum(int(word) for word in input().split()))
            print(max(str(i) for i in range(12)))
            print(min(float(i)/3 for i in range(4)))
            print(any(word for word in input().split()))
        ''', ("１２ 4 -3\nhi there\n", "\n\n"))

    def test_reduction_function_specialization_and_full_error_frames(self):
        self.differential('''
            def divide(value):
                return 10//value
            def total(values):
                return sum(divide(x) for x in values)
            print("before")
            print(total([-1,0,1]))
        ''', trace=True)

    def test_nested_generator_and_map_callback_error_frames(self):
        self.differential('''
            values=[1,0]
            print(sum(
                x for x in (
                    10//y for y in values
                )
            ))
        ''', trace=True)

    def test_suspended_producer_does_not_enter_consumer_callback_traceback(self):
        for expression in (
            "sum(map(divide,(x for x in [1,0])))",
            "sum(x for x in map(divide,[1,0]))",
            "sum(filter(divide,(x for x in [1,0])))",
            "sum(x for x in filter(divide,(y for y in [1,0])))",
        ):
            self.differential("def divide(value):\n return 10//value\nprint("+expression+")\n", trace=True)

    def test_generator_errors_in_main_wrapper_preserve_both_scopes(self):
        self.differential('''
            def main():
                print("before")
                print(sum(10//x for x in [1,0]))
            if __name__ == "__main__":
                main()
        ''', trace=True)
        self.differential('''
            def divide(value):
                return 10//value
            print(sum(map(divide,[1,0])))
        ''', trace=True)

    def test_explicit_eager_sequences_still_evaluate_all_elements(self):
        self.differential('''
            print(any(["nonempty",input()]),input())
            print(all(("",input())),input())
        ''', ("first\nsecond\nthird\nfourth\n",))

    def test_wrapping_each_sum_step_and_boolean_results(self):
        source = '''a=int(input())
print(sum(a+i for i in range(5)))
print(sum((a-i for i in range(5)),start=a))
print(any(a+i==0 for i in range(3)),max(a+i for i in range(3)))
'''
        for mode in ("i64", "i128", "bigint"):
            compiled = self.compile(source, mode)
            for a in (0, -1, 2**63-1, 2**127-1, -2**127):
                self.compare(compiled, f"{a}\n", mode=mode, wrapping=True)

    def test_bigint_range_generator_reductions_share_owned_scalar_hooks(self):
        self.differential('''
            print(sum((1<<i) for i in range(140)))
            print(max(i*i for i in range(9)),min(i*i for i in range(-4,5)))
            print(any(i>3 for i in range(5)),all(i for i in range(1,5)))
            print(sum((i for i in range(0)),True),sum((i for i in range(2)),True))
        ''', modes=("bigint",))

    def test_unproved_binding_mutation_and_escaped_generators_are_rejected(self):
        for source in (
            "sum=lambda xs:77\nprint(sum(x for x in [1]))",
            "any=lambda xs:77\nprint(any(x for x in [1]))",
            "all=lambda xs:77\nprint(all(x for x in [1]))",
            "g=(x for x in range(3))\nprint(sum(g))",
            "print(sum(x for x in [1]));print(x)",
            "from collections import deque\nq=deque([1,2])\nprint(sum((x for x in q),q.popleft()))",
            "s={1,2}\nprint(sum(1//x for x in s))",
            "print(sum(float(x) for x in range(3)))",
            "print(max((x for x in [1]),key=lambda x:x))",
            "print(sum(x for (x,) in [1]))",
            "print(sum(x for x in zip([1])))",
        ):
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source,"case.py","i64"))
