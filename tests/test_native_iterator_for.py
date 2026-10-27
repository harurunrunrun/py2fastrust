"""Statement loops reuse typed streams and Python control-flow bindings."""

from py2fastrust.native import try_generate_native
from test_native_iterator_reductions import NativeIteratorReductionTests


class NativeIteratorForTests(NativeIteratorReductionTests):
    def test_enumerate_input_list_and_loop_targets(self):
        self.differential('''
            a=list(map(int,input().split()))
            right=-1
            value=0
            answer=0
            for right,value in enumerate(a):
                answer+=right*value
            print(answer,right,value)
        ''', ("\n", "2 5 1\n", "-3 7 8 4\n"))

    def test_zip_dictionary_views_and_tuple_target_shapes(self):
        self.differential('''
            a=[1,2,3]
            b=[4,5]
            answer=0
            for x,y in zip(a,b):
                answer+=x*y
            d={1:7,3:9}
            for k,v in d.items():
                answer+=k+v
            print(answer,x,y,k,v)
        ''')

    def test_map_filter_enumerate_keyword_start(self):
        self.differential('''
            def square(x):
                return x*x
            def odd(x):
                return x%2==1
            answer=0
            for i,x in enumerate(filter(odd,map(square,range(6))),start=7):
                answer+=i*x
            print(answer)
            for i,x in enumerate([4],True):
                print(i,x)
        ''')

    def test_generator_break_continue_advance_the_yielding_loop(self):
        self.differential('''
            answer=0
            for value in (x+y for x in range(3) for y in range(4) if y%2):
                if value==1:
                    continue
                if value==4:
                    break
                answer+=value
            print(answer,value)
            answer=0
            for value in (x for x in (y*y for y in range(5))):
                if value==1:
                    continue
                if value==9:
                    break
                answer+=value
            print(answer,value)
        ''')

    def test_for_else_break_and_normal_exhaustion_keep_types(self):
        self.differential('''
            answer=False
            for i,value in enumerate([2,3,4]):
                if value==int(input()):
                    answer=i
                    break
            else:
                answer=True
            print(answer)
        ''', ("2\n", "0\n3\n", "0\n0\n0\n"))

    def test_nested_loop_else_only_uses_its_own_breaks(self):
        self.differential('''
            answer=0
            for x in range(3):
                for y in range(3):
                    if y==1:
                        break
                else:
                    answer+=100
                answer+=x
            else:
                answer+=10
            print(answer)
        ''')

    def test_empty_stream_preserves_prior_loop_targets_and_runs_else(self):
        self.differential('''
            i=77
            value=False
            for i,value in enumerate([]):
                value=99
                break
            else:
                print(i,value)
            print(i,value)
        ''')

    def test_known_nonempty_stream_proves_new_targets(self):
        self.differential('''
            for i,value in enumerate([7]):
                print(i,value)
            print(i,value)
            for x,y in zip([1,2],[3]):
                print(x,y)
            print(x,y)
        ''')

    def test_return_from_iterator_loop_returns_from_user_function(self):
        self.differential('''
            def find(values):
                for i,x in enumerate(values):
                    if x>2:
                        return i
                return -1
            print(find([0,3,5]),find([]))
            def choose():
                for x in (i*i for i in range(4)):
                    if x>2:
                        return x
                else:
                    return -1
            print(choose())
        ''')

    def test_callback_and_generator_failures_keep_correct_caller_frames(self):
        for iterator in ("map(divide,(x for x in [1,0]))", "(divide(x) for x in [1,0])"):
            self.differential("def divide(x):\n return 10//x\nfor value in "+iterator+":\n print(value)\n", trace=True)

    def test_unicode_string_iteration_and_reversal(self):
        self.differential('''
            text=input()
            answer=0
            last="?"
            for ch in text:
                if ch in "猫é":
                    answer+=1
                last=ch
            print(answer,last)
            for i,ch in enumerate("猫🙂"):
                print(i,ch)
            print(i,ch)
            for ch in reversed("猫é"):
                print(ch)
        ''', ("猫🙂é\n", "\n", "abc\n"), modes=("i64","i128","bigint"))

    def test_string_rebinding_keeps_original_iterator_snapshot(self):
        self.differential('''
            text="ab"
            answer=""
            for ch in text:
                text+="x"
                answer+=ch
            print(text,answer)
            text="海猫"
            for text in text:
                print(text)
            print(text)
        ''', modes=("i64","i128","bigint"))

    def test_reversed_lists_ranges_and_dictionary_items(self):
        self.differential('''
            answer=0
            for x in reversed([1,2,3]):
                answer=answer*10+x
            for x in reversed(range(-2,3)):
                answer+=x
            for x in reversed(range(3,-3,-1)):
                answer+=x
            d={1:7,2:8}
            for k,v in reversed(d.items()):
                print(k,v)
            print(answer)
        ''')

    def test_input_words_convert_at_each_iteration(self):
        self.differential('''
            answer=0
            for word in input().split():
                answer+=int(word)
            print(answer)
            for x in map(int,input().split()):
                if x>2:
                    break
                print(x)
            print(int(input()))
        ''', ("１２ -3 5\n1 2 3 invalid\n91\n", "\n4 invalid\n92\n"))

    def test_deque_mutation_expressions_do_not_leave_stale_cardinality(self):
        self.differential('''
            from collections import deque
            q=deque([1])
            old=q.popleft()
            item=True
            for item in q:
                item=99
            print(item)
            q=deque([1])
            unused=bool(int(input())) and q.popleft()
            item=False
            for item in q:
                item=True
            print(item)
        ''', ("0\n", "1\n"))

    def test_deferred_mutations_invalidate_the_callers_container_facts(self):
        self.differential('''
            from collections import deque
            q=deque([1])
            unused=sum(q.popleft() for _ in range(1))
            item=True
            for item in q:
                item=99
            print(item)
            q=deque([1])
            unused=sum(q.popleft() for _ in range(0))
            for item in q:
                item=False
            print(item)
        ''')

    def test_zip_argument_mutation_invalidates_nonempty_proof(self):
        self.differential('''
            from collections import deque
            q=deque([1])
            first=True
            second=True
            for first,second in zip(q,[q.popleft()]):
                first=7
            else:
                print(first,second)
        ''')

    def test_loop_target_may_replace_its_own_iterable_name(self):
        self.differential('''
            a=[1,2,3]
            for a in a:
                print(a)
                a+=5
            print(a)
            d={1:7,2:8}
            for d in d:
                print(d)
            print(d)
        ''')

    def test_bigint_range_adapters_break_continue_and_else(self):
        self.differential('''
            answer=0
            for i,x in enumerate(range(10**100,10**100+4),start=10**120):
                if i%2:
                    continue
                answer+=i*x
            else:
                answer+=1
            print(answer,i,x)
            for value in (i*i for i in range(10)):
                if value>8:
                    break
            print(value)
        ''', modes=("bigint",))

    def test_maybe_empty_targets_have_python_unbound_errors(self):
        self.differential('''
            a=list(map(int,input().split()))
            for i,value in enumerate(a):
                pass
            print(i,value)
        ''', ("\n", "3 7\n"), trace=True)
        self.differential('''
            for value in (x for x in range(int(input())) if x%2):
                pass
            print(value)
        ''', ("0\n", "1\n", "4\n"), trace=True)
        self.differential('''
            for value in range(0):
                pass
            print(value)
        ''', modes=("i64","i128","bigint"), trace=True)
        self.differential('''
            for value in (b"value" for _ in range(int(input()))):
                if value==b"value":
                    value=b"changed"
            for value in (b"last" for _ in range(int(input()))):
                pass
            print(value)
        ''', ("0\n0\n", "1\n0\n", "0\n1\n"), modes=("i64","i128","bigint"), trace=True)

    def test_optional_loop_targets_in_functions_and_generators(self):
        self.differential('''
            def last(n):
                for value in range(n):
                    pass
                return value
            print(last(int(input())))
        ''', ("0\n", "3\n"), modes=("i64","i128","bigint"), trace=True)
        self.differential('''
            def compute(n):
                for value in range(n):
                    pass
                return sum(value+x for x in range(2))
            print(compute(int(input())))
        ''', ("0\n", "3\n"), modes=("i64","i128","bigint"), trace=True)

    def test_optional_slots_survive_reassignment_and_bool_int_join(self):
        self.differential('''
            for value in range(int(input())):
                if value%2:
                    value=True
            for value in range(int(input())):
                if value%2:
                    continue
                value=False
            print(value)
        ''', ("0\n0\n", "2\n0\n", "0\n3\n", "3\n4\n"),
            modes=("i64","i128","bigint"), trace=True)

    def test_optional_string_float_targets_and_branch_bindings(self):
        self.differential('''
            for letter in input():
                if letter=="!":
                    break
            print(letter)
        ''', ("\n", "abc\n", "a!c\n"), modes=("i64","i128","bigint"), trace=True)
        self.differential('''
            for value in (1.5*x for x in range(int(input()))):
                pass
            print(value)
        ''', ("0\n", "3\n"), trace=True)
        self.differential('''
            if int(input()):
                value=7
            print(value)
        ''', ("0\n", "1\n"), modes=("i64","i128","bigint"), trace=True)
        self.differential('''
            if int(input()):
                value=b"bytes"
            print(value)
        ''', ("0\n", "1\n"), modes=("i64","i128","bigint"), trace=True)
        self.differential('''
            for letter in input():
                pass
            for character in letter:
                print(character)
        ''', ("\n", "日本語\n"), modes=("i64","i128","bigint"), trace=True)

    def test_optional_target_in_main_wrapper_retains_local_scope(self):
        self.differential('''
            def main():
                for value in range(int(input())):
                    pass
                print(value)
            if __name__=="__main__":
                main()
        ''', ("0\n", "2\n"), trace=True)

    def test_unproved_alias_mutation_and_tuple_bindings_are_rejected(self):
        for source in (
            "a=[1,2]\nfor x in a:a.append(x)",
            "for (x,) in [1]:pass",
            "a=[[1]]\nfor row in a:row.append(2)",
        ):
            with self.subTest(source=source):
                self.assertIsNone(try_generate_native(source,"case.py","i64"))
        self.differential("for x in zip([1]):print(x)",modes=("i64","i128","bigint"))


for _name in dir(NativeIteratorReductionTests):
    if _name.startswith("test_") and _name not in NativeIteratorForTests.__dict__:
        setattr(NativeIteratorForTests, _name, None)
del NativeIteratorReductionTests
