"""Integer deques share native storage, calls and iteration across all widths."""
import shutil
import unittest

from py2fastrust import TranspileOptions,transpile
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeDequeTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_ordinary_endpoints_copy_and_integer_projection(self):
        self.exercise('''from collections import deque
q=deque([1,2])
q.append(3)
q.appendleft(0)
r=q.copy()
print(q.popleft(),q.pop(),len(q),q,bool(q),q.maxlen)
print(r,q[0],q[-1],str(q),repr(q))
''',('',))

    def test_bounded_constructor_extend_rotate_reverse_search_and_insert(self):
        self.exercise('''from collections import deque
q=deque(range(8),maxlen=3)
print(q,q.maxlen)
q.extendleft([9,10])
q.rotate(-1)
q.reverse()
print(q,q.count(9),q.index(9))
q.remove(9)
q.insert(-1,77)
print(q)
''',('',))

    def test_import_aliases_module_members_and_function_local_import(self):
        self.exercise('''import collections as co
D=co.deque
def make(n):
 from collections import deque as Local
 return Local(range(n))
q=D(iterable=[1,2],maxlen=3)
r=make(4)
print(q,r,list(r),sum(r))
''',('',))

    def test_self_extension_snapshots_only_the_exact_container(self):
        self.exercise('''from collections import deque
q=deque([1,2,3])
q.extend(q)
print(q)
q=deque([1,2,3],maxlen=4)
q.extendleft(q)
print(q)
r=q.copy()
q.clear()
print(q,r,q.maxlen,r.maxlen)
''',('',))

    def test_constructor_arguments_run_before_deferred_container_iteration(self):
        self.exercise('''from collections import deque
q=deque([1,2,3])
r=deque(q,maxlen=q.popleft())
print(q,r)
q=deque([2,3,4])
r=deque(q.copy(),maxlen=q.popleft())
print(q,r)
def mark(tag,value):
 print(tag,end="|")
 return value
q=deque(maxlen=mark("bound",2),iterable=range(mark("source",4)))
print(q)
''',('',))

    def test_zero_bound_consumes_generator_effects_and_append_values(self):
        self.exercise('''from collections import deque
def mark(value):
 print(value,end="|")
 return value
q=deque((mark(value)for value in range(4)),maxlen=0)
print(q,q.append(mark(7)),q.appendleft(mark(8)))
q.extend(mark(value)for value in range(3))
q.extendleft(mark(value)for value in range(2))
print(q)
''',('',))

    def test_print_preserves_mutable_identity_and_star_expansion_order(self):
        self.exercise('''from collections import deque
q=deque([1,2,3])
print(q,q.pop(),q)
q=deque([1,2,3])
print(q,*q,q.pop(),q)
values=[1,2]
print(values,values.pop(),values)
values=[1,2]
print(*values,values.pop(),values)
''',('',))

    def test_dynamic_maxlen_and_mutating_method_arguments(self):
        self.exercise('''from collections import deque
q=deque([1,2,3],maxlen=int(input()))
print(q)
q.append(q.popleft())
print(q)
''',('-1\n','0\n','1\n','3\n'))

    def test_big_integer_items_survive_native_iteration_and_copies(self):
        self.exercise('''from collections import deque
large=10**120
q=deque([large,-large,large+7])
r=deque(q)
print(q[0],q[-1],sum(q),min(q),max(q))
print(list(reversed(q)),sorted(q),r)
print(q.pop(),q.popleft(),q)
''',('',),modes=('bigint',))

    def test_empty_pop_missing_search_and_out_of_range_errors(self):
        for action in('q.pop()','q.popleft()','q.index(9)','q.remove(9)','q[0]'):
            self.exercise('from collections import deque\nq=deque()\nprint("prefix")\nprint('+action+')\n',('',))

    def test_full_deque_insert_retains_prefix_and_index_error(self):
        self.exercise('''from collections import deque
q=deque([1,2],maxlen=2)
print(q)
q.insert(0,9)
''',('',))

    def test_maxlen_and_rotate_ssize_overflow_on_wider_engines(self):
        for expression in('deque([1],2**100)','deque([1]).rotate(2**100)'):
            self.exercise('from collections import deque\nprint("prefix")\nprint('+expression+')\n',('',),modes=('i128','bigint'))

    def test_nullable_maxlen_uses_shared_finite_value_projection(self):
        self.exercise('''from collections import deque
n=int(input())
bound=None if n<0 else n
q=deque(range(5),maxlen=bound)
print(q,q.maxlen)
''',('-1\n','0\n','1\n','3\n'))

    def test_membership_and_chained_content_comparisons(self):
        self.exercise('''from collections import deque
a=deque([1,2],maxlen=2)
b=deque([1,2])
c=deque([1,3])
print(a==b,a<b,a<=b,a<c,a!=c,a==[1,2])
print(1 in a,True in a,3 not in a,"x"in a,None in a,(1,)in a)
print(a==b<c,a!=b<c)
''',('',))

    def test_item_assignment_delete_and_augmented_mutating_rhs(self):
        self.exercise('''from collections import deque
q=deque([1,2,3,4])
q[-1]=q.popleft()
print(q)
q[-1]+=q.popleft()
print(q)
del q[-1]
print(q)
''',('',))

    def test_huge_item_index_is_an_index_error_on_wider_engines(self):
        self.exercise('from collections import deque\nq=deque([1])\nprint("prefix")\nprint(q[2**100])\n',('',),modes=('i128','bigint'))

    def test_synthetic_sort_key_operand_has_no_source_name_requirement(self):
        self.exercise('words=["long","x","abc"]\nwords.sort(key=len)\nprint(words)\n',('',))

    def test_default_ascii_output_omits_unicode_data_and_vm(self):
        source='from collections import deque\nq=deque([1,2],maxlen=3)\nprint(q)\n'
        for mode in('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertLess(len(result.rust_source.encode()),512*1024)
            self.assertNotIn('UNICODE LICENSE V3',result.rust_source)
            for marker in('enum Value','enum Op','struct Runtime','fn step('):
                self.assertNotIn(marker,result.rust_source)

    def test_existing_alias_and_iteration_mutation_boundaries_stay_explicit(self):
        for source in(
            'from collections import deque\nq=deque([1])\nr=q\nr.append(2)\n',
            'from collections import deque\nq=deque([1,2])\nfor x in q:\n q.append(3)\n',
            'from collections import deque\nq=deque([1,2])\nq.extend(iter(q))\n',
            'from collections import deque\nq=deque([1,2])\nprint(q.count(1.0))\n',
        ):
            for mode in('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success,source)
                self.assertEqual(result.diagnostics[0].code,'E006')


if __name__=='__main__':unittest.main()
