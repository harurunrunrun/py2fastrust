"""Concrete bytes must not bypass common finite comparison semantics."""
import shutil
import unittest

from py2fastrust import TranspileOptions, transpile
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeFiniteComparisonRoutingTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_nullable_bytes_compare_payload_in_both_orientations(self):
        self.exercise('''n=int(input())
value=b"ab" if n else None
print(value==b"ab",value!=b"ab",b"ab"==value,b"ab"!=value)
print(value==b"ac",value!=b"ac",value==None,value is None)
''',("0\n","1\n"))

    def test_mixed_immutable_alternatives_share_existing_equality_dispatch(self):
        self.exercise('''def choose(n):
 if n==0:return None
 if n==1:return True
 if n==2:return 2
 if n==3:return "ab"
 if n==4:return b"ab"
 return (1,False)
value=choose(int(input()))
print(value==b"ab",value!=b"ab",b"ab"==value,b"ab"!=value)
''',tuple(str(i)+"\n"for i in range(6)))

    def test_container_fields_and_returned_values_keep_their_concrete_tags(self):
        self.exercise('''def maybe(n):
 if n:return b"ab"
 return None
for value in [b"ab",None,b"ac"]:
 print(value==b"ab",value!=b"ab",b"ab"==value)
for n in range(2):
 print(maybe(n)==b"ab",b"ab"!=maybe(n))
''',("",))

    def test_chained_equality_runs_each_operand_once_and_skips_later_calls(self):
        self.exercise('''def mark(tag,value):
 print(tag,end="|")
 return value
value=b"ab" if int(input()) else None
print(mark("first",value)==mark("second",b"ab")==mark("third",b"ab"))
print(mark("fourth",b"ab")!=mark("fifth",value)!=mark("sixth",b"zz"))
''',("0\n","1\n"))

    def test_chained_operand_errors_are_not_replaced_by_early_false(self):
        # This test's contract is operand evaluation, exception type and frames.
        # The inherited text-int parser still omits CPython's base/literal text.
        import test_native_iterator_reductions as reductions
        source='''def mark(tag,value):
 print(tag,end="|")
 return value
value=b"ab" if int(input()) else None
print(mark("left",value)==mark("middle",b"ab")==mark("right",int(input())))
print(input())
'''
        for mode in("i64","i128","bigint"):
            for release in(False,True):
                compiled=self.compile(source,mode,release)
                for data in("0\nbad\ntail\n","1\nbad\ntail\n","1\n7\ntail\n"):
                    reductions.NativeIteratorReductionTests.compare(self,compiled,data,mode=mode,trace=True)

    def test_mutating_operands_do_not_corrupt_later_cardinality_proofs(self):
        self.exercise('''values=[b"ab",None]
print(values.pop()==b"ab")
print(next(iter(range(len(values))),None),len(values),values[0])
values=[b"ab",b"ab",None]
print(values.pop()!=b"ab"==values.pop())
print(next(iter(range(len(values))),None),len(values))
values=[b"ab",None]
print(values.pop()==b"ab"==values.pop())
print(next(iter(range(len(values))),None),len(values))
''',("",))

    def test_numeric_tuple_and_membership_frontends_capture_effects_once(self):
        self.exercise('''values=[1,2]
print(values.pop()>0)
print(next(iter(range(len(values))),None),len(values))
values=[1,2]
print(3<1<values.pop())
print(next(iter(range(len(values))),None),len(values))
values=[1,2]
print((values.pop(),)<(3,))
print(next(iter(range(len(values))),None),len(values))
values=[1,2]
keys={1:7,2:9}
print(values.pop() in keys)
print(next(iter(range(len(values))),None),len(values))
''',("",))

    def test_boolean_and_conditional_clear_pop_effects_join_afterward(self):
        self.exercise('''flag=int(input())
values=[1,2]
print(flag and values.clear())
print(len(values),next(iter(range(len(values))),None))
values=[1,2]
print(flag or values.clear())
print(len(values),next(iter(range(len(values))),None))
values=[1,2]
print(values.clear() if flag else None)
print(len(values),next(iter(range(len(values))),None))
values=[1,2]
print((values.pop()>0) if flag else False)
print(len(values),next(iter(range(len(values))),None))
''',("0\n","1\n"))

    def test_nested_generator_mutation_and_later_clear_keep_observations_sound(self):
        self.exercise('''values=[1,2]
print(next(values.pop() for i in range(1))==2)
print(next(iter(range(len(values))),None),len(values))
values=[1,2]
print(3<1<values.clear())
print(next(iter(range(len(values))),None),len(values))
values=[1,2]
print(0<len(values)<=len(values) is not values.clear())
print(next(iter(range(len(values))),None),len(values))
''',("",))

    def test_clear_expression_keeps_conditional_storage_content_types(self):
        self.exercise('''flag=int(input())
values=[1]
print(flag and values.clear())
values.append("later")
print(values,len(values))
keys=set([1,2])
mapping={1:2}
print(flag or keys.clear(),flag and mapping.clear())
print(len(keys),len(mapping))
''',("0\n","1\n"))

    def test_equality_then_ordering_retains_python_type_errors_and_short_circuit(self):
        self.exercise('''def mark(tag,value):
 print(tag,end="|")
 return value
value=b"ab" if int(input()) else None
print(mark("first",value)==mark("second",b"ab")<mark("third","ab")<mark("fourth",b"zz"))
''',("0\n","1\n"))

    def test_none_identity_uses_the_shared_proof_including_bytes(self):
        self.exercise('''n=int(input())
value=b"ab" if n else None
plain=b"ab"
print(plain is None,plain is not None,None is plain,None is not plain)
print(plain==value is None,plain!=value is not None)
print(value is None,value is not None)
''',("0\n","1\n"))

    def test_unbound_bytes_lookup_precedes_a_proved_unequal_comparison(self):
        self.exercise('''def mark(value):
 print("later",end="|")
 return value
if int(input()):
 payload=b"ab"
print("start",end="|")
print(payload==None==mark(7))
''',("0\n","1\n"))

    def test_nullable_builtin_list_and_bytes_equality_uses_concrete_protocol(self):
        source='value=[1] if int(input()) else None\nprint(value==b"ab")\n'
        self.exercise(source,('0\n','1\n'))

    def test_non_none_scalar_identity_remains_an_explicit_boundary(self):
        source='value=b"ab" if int(input()) else None\nprint(value is b"ab")\n'
        for mode in("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")


if __name__=="__main__":unittest.main()
