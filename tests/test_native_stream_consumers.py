"""Equivalent iterator syntax shares construction and consumer semantics."""
import unittest
import shutil
import test_native_iterator_reductions as _helpers


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeNormalizedConsumerTests(unittest.TestCase):
    setUpClass=classmethod(_helpers.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass=classmethod(_helpers.NativeIteratorReductionTests.tearDownClass.__func__)
    compile=_helpers.NativeIteratorReductionTests.compile
    compare=_helpers.NativeIteratorReductionTests.compare
    differential=_helpers.NativeIteratorReductionTests.differential

    def test_captured_core_producer_consumer_and_scalar_aliases(self):
        self.differential('''
            seq=range
            mapper=map
            parse=int
            read=input
            consume=sum
            make=list
            order=sorted
            first=next
            pairs=zip
            numbered=enumerate
            rev=reversed
            truth=bool
            text=str
            print(consume(mapper(parse,read().split())))
            values=make(seq(5))
            print(consume(parse(v) for v in values),first(rev(values)))
            print(order(mapper(text,seq(3))))
            for i,v in numbered(mapper(truth,values),start=4):
                print(i,v)
            a,b=first(pairs(values,seq(7,20)))
            print(a,b)
        ''',("1 2 3 4\n",),modes=("i64","i128","bigint"))

    def test_equivalent_integer_word_producers_and_consumers(self):
        for producer in ("map(parse,read().split())","(parse(word) for word in read().split())"):
            with self.subTest(producer=producer):
                self.differential('''parse=int
read=input
print(sum(PRODUCER))
print(list(PRODUCER))
print(sorted(PRODUCER))
print(next(PRODUCER,-10))
a,b=PRODUCER
print(a,b)
for value in PRODUCER:
 print(value)
'''.replace("PRODUCER",producer),("1 2 3\n4 5\n9 7 8\n10 invalid\n11 12\n13 14\n",),modes=("i64","i128","bigint"),trace=True)

    def test_lazy_word_unpacked_extra_item_error_order(self):
        for producer in ("map(parse,read().split())","(parse(word) for word in read().split())"):
            self.differential('parse=int\nread=input\na,b='+producer+'\nprint(a,b)\n',
                              ("1 2 3 invalid\n","1 2 invalid 4\n","1\n","\n"),modes=("i64","i128","bigint"),trace=True)

    def test_eager_comprehension_parses_before_unpack_consumer(self):
        self.differential('''parse=int
read=input
a,b=[parse(word) for word in read().split()]
print(a,b)
''',("1 2 3 invalid\n","1 2\n","\n"),modes=("i64","i128","bigint"),trace=True)

    def test_split_receiver_arguments_and_consumer_defaults_order(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print(next(map(int,mark("1:2").split(mark(":"),mark(1))),mark(8)))
            print(sorted(map(int,mark("3 2 1").split(maxsplit=mark(4))),reverse=mark(True)))
            print("-".join(str(x) for x in range(3)))
        ''',modes=("i64","i128","bigint"),trace=True)

    def test_split_materialization_and_laziness_unicode_and_bytes(self):
        self.differential('''
            import sys
            print(" a  b  ".split(maxsplit=0))
            print("a::b::".split("::",1))
            print("α\\u001cβ\\u2003γ".split())
            print(b" a\\tb ".split())
            print(next(map(int,sys.stdin.buffer.readline().split())))
        ''',("12 invalid\n",),modes=("i64","i128","bigint"))

    def test_definitely_bound_aliases_survive_branches_and_function_capture(self):
        self.differential('''
            if int(input()):
                sequence=range
            else:
                sequence=range
            consume=sum
            def total(n):
                make=sequence
                return consume(make(n))
            print(total(7))
            for _ in range(0):
                sequence=range
            print(total(4))
        ''',("0\n","1\n"),modes=("i64","i128","bigint"))

    def test_aliases_missing_on_a_control_flow_edge_are_rejected(self):
        from py2fastrust import transpile
        for source in ("if int(input()):\n seq=range\nprint(sum(seq(4)))\n",
                       "for _ in range(0):\n seq=range\nprint(sum(seq(4)))\n",
                       "def f():\n print(sum(seq(4)))\n seq=range\nf()\n",
                       "int=filter\nprint(int(1))\n"):
            with self.subTest(source=source):
                result=transpile(source)
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")

    def test_invalid_call_binding_is_positioned_diagnostic(self):
        from py2fastrust import transpile
        for source in ("print(input(prompt='x'))", "print(sum(range()))", "values=[1]\nvalues.sort(unknown=True)",
                       "a,b=map(int,input().split(unknown=1))"):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")
            self.assertGreater(result.diagnostics[0].line,0)
