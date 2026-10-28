"""Canonical deque element types reuse ordinary sequence and scalar semantics."""
import shutil
import unittest
import test_native_union_ordering as helpers

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeTypedDequeTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_pair_queue(self):
        self.exercise('from collections import deque\nqueue=deque([(1,2),(3,4)])\nqueue.append((5,6))\nprint(queue.popleft(),queue.pop(),queue[0],len(queue))\n',('',))

    def test_widths_and_empty_inference(self):
        self.exercise('from collections import deque\nqueue=deque()\nqueue.append((int(input()),True,"x"))\nprint(queue,queue.popleft(),queue)\n',('3\n', '-3\n'))

    def test_strings_bytes_none(self):
        self.exercise('from collections import deque\nqueue=deque(["a","b"])\nqueue.appendleft("x")\nprint(queue,queue[1],list(queue),queue.count("a"),queue.index("b"),"x"in queue)\nother=deque([b"a",None,b"z"])\nprint(other,other.popleft(),other.pop())\n',('',))

    def test_bool_numeric_comparison(self):
        self.exercise('from collections import deque\na=deque([True,False])\nb=deque([1,0])\nc=deque([True,2])\nprint(a==b,a<=b,a>b,a<c,c.count(1),1 in c)\n',('',))

    def test_bounded_tuple_operations(self):
        self.exercise('from collections import deque\nq=deque([(1,2),(3,4)],maxlen=2)\nq.append((5,6))\nq.appendleft((7,8))\nq.rotate(-3)\nprint(q,q.maxlen,q.copy())\nq.reverse()\nq.remove((7,8))\nprint(q)\n',('',))

    def test_extend_self_and_generator(self):
        self.exercise('from collections import deque\nq=deque([(1,2),(3,4)],maxlen=5)\nq.extend(q)\nq.extendleft((i,i+1)for i in range(3))\nprint(q,list(reversed(q)))\n',('',))

    def test_index_set_delete(self):
        self.exercise('from collections import deque\nq=deque([(1,2),(3,4),(5,6)])\nq[-1]=(7,8)\ndel q[0]\nprint(q,q[-2],q[-1])\n',('',))

    def test_evaluation_order(self):
        self.exercise('from collections import deque\nq=deque([(1,2),(3,4)])\nq[q.popleft()[0]-1]=(8,9)\nprint(q)\n',('',))

    def test_search_errors_and_boundaries(self):
        self.exercise('from collections import deque\nq=deque([(1,2)])\nprint("before",end="|")\nprint(q.index((3,4)))\n',('',))

    def test_pop_empty(self):
        self.exercise('from collections import deque\nq=deque()\nq.append((1,2))\nq.clear()\nprint(q.popleft())\n',('',))

    def test_unbound_receiver_order(self):
        self.exercise('from collections import deque\ndef mark():\n print("later",end="|")\n return (3,4)\nif int(input()):q=deque([(1,2)])\nq.append(mark())\nprint(q)\n',('0\n', '1\n'))

    def test_nested_tuple_payload(self):
        self.exercise('from collections import deque\nq=deque([((1,2),"x"),((3,4),"y")])\nprint(q.popleft(),q[0],list(q))\n',('',))

    def test_varying_tuple_arities(self):
        self.exercise('from collections import deque\nq=deque([(1,),(2,3)])\nq.append((4,5,6,7))\nprint(q,list(q),q.count((1,)),(2,3)in q)\n',('',))

    def test_arbitrary_tuple_arity(self):
        self.exercise('from collections import deque\nq=deque([(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)])\nprint(q,q[0],q.popleft())\n',('',))

    def test_constructor_alias_and_nested_scope(self):
        self.exercise('def work():\n from collections import deque as fifo\n construct=fifo\n q=construct([("a",1)])\n q.append(("b",2))\n print(q.popleft(),q)\nwork()\n',('',))

    def test_iteration_unpack(self):
        self.exercise('from collections import deque\nq=deque([(1,2),(3,4)])\nfor a,b in q:\n print(a,b,end="|")\nprint()\nprint(sum(a+b for a,b in q))\n',('',))

    def test_clear_then_different_element(self):
        self.exercise('from collections import deque\nq=deque([(1,2)],maxlen=3)\nq.clear()\nq.append("x")\nprint(q,q.maxlen)\n',('',))

    def test_comparison_later_mutates_middle(self):
        self.exercise('from collections import deque\na=deque([(1,2)])\nb=deque([(1,2)])\nprint(a==b==b.popleft())\nprint(a,b)\n',('',))

    def test_comparison_later_empty_error(self):
        self.exercise('from collections import deque\na=deque()\nb=deque()\nprint("before",end="|")\nprint(a==b==b.popleft())\n',('',))

    def test_rhs_before_target_index(self):
        self.exercise('from collections import deque\nq=deque([(0,0),(1,1)])\nprint("before",end="|")\nq[q.popleft()[0]]=q.pop()\nprint(q)\n',('',))

    def test_numeric_augassign(self):
        self.exercise('from collections import deque\nq=deque([True,False])\nq[-1]+=1\nq[0]+=q.pop()\nprint(q,q[0])\n',('',))

    def test_maxlen_zero_preserves_generator_effects(self):
        self.exercise('from collections import deque\ndef mark(i):\n print(i,end="|")\n return i\nq=deque(((mark(i),"x")for i in range(3)),maxlen=0)\nprint(q)\n',('',))

    def test_str_and_repr(self):
        self.exercise('from collections import deque\nq=deque([(1,2)])\nprint(str(q),repr(q))\nr=deque([1,2])\nprint(str(r),repr(r))\n',('',))

    def test_wide_tuple_copy_and_extend(self):
        self.exercise('from collections import deque\nq=deque([(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)])\nq.extend(q)\nr=q.copy()\nprint(len(q),r,q[1]==r[0])\n',('',))

    def test_bounded_insert_error(self):
        self.exercise('from collections import deque\nq=deque([(1,2)],maxlen=1)\nprint("before",end="|")\nq.insert(0,(3,4))\n',('',))

    def test_unproved_mutable_payloads_and_aliases_remain_explicit(self):
        from py2fastrust import transpile,TranspileOptions
        sources=('from collections import deque\nq=deque([[1]])\nprint(q)\n',
                 'from collections import deque\nq=deque([(1,2)])\nalias=q\nq.append((3,4))\nprint(alias)\n',
                 'from collections import deque\ndef take(q):return q.popleft()\nq=deque([(1,2)])\nprint(take(q),q)\n')
        for source in sources:
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')

    def test_homogeneous_tuple_payload(self):
        self.exercise('from collections import deque\nq=deque([tuple(map(int,input().split())),tuple(range(3))])\nprint(q,q[0],q.count(tuple(range(3))))\nq.extend([tuple(range(2))])\nprint(q.popleft(),list(q))\n',('\n','0 1 2\n','8 9\n'))

    def test_unbound_copy_and_star(self):
        self.exercise('from collections import deque\nif int(input()):q=deque([(1,2)])\nprint(q.copy(),*q)\n',('0\n','1\n'))
