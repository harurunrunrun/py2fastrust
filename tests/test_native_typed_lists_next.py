"""Structural native lists and immediate iterator consumers."""

from py2fastrust.native import try_generate_native
from test_native_iterator_reductions import NativeIteratorReductionTests


class NativeTypedListsNextTests(NativeIteratorReductionTests):
    def test_string_literal_lists_append_index_and_len(self):
        self.differential('''
            names=["red","青"]
            names.append("🙂")
            names[-1]="猫"
            print(len(names),names[0],names[-1])
            empty=[]
            empty.append("first")
            empty.append("last")
            print(empty[0],empty[-1],len(empty))
        ''',modes=("i64","i128","bigint"),string_mode="unicode")

    def test_string_comprehension_reads_and_readonly_iteration(self):
        self.differential('''
            n=int(input())
            lines=[input() for _ in range(n)]
            for i,line in enumerate(lines):
                print(i,line)
            print(len(lines))
        ''',("0\n","3\nblue\n\n海猫\n"),modes=("i64","i128","bigint"),string_mode="unicode")

    def test_split_copy_and_unicode_slices(self):
        self.differential('''
            words=input().split()
            copied=words.copy()
            other=list(words)
            for word in copied[::-1]:
                print(word)
            for word in other[1:]:
                print(word)
            words.append("new")
            print(len(words),len(copied),len(other))
        ''',("\n"," A\u3000猫\tB \n"),modes=("i64","i128","bigint"),string_mode="unicode")

    def test_next_generator_is_lazy_and_evaluates_default(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print(next((mark(x) for x in range(mark(3))),mark(99)))
            print(next((mark(x) for x in range(mark(0))),mark(98)))
            print(next((x for x in range(5) if x%2),77))
        ''',modes=("i64","i128","bigint"))

    def test_next_map_filter_and_explicit_iter(self):
        self.differential('''
            def odd(x):
                return x%2
            print(next(map(int,input().split()),91))
            print(next(filter(odd,range(4)),92))
            print(next(iter([3,7]),93))
            print(next(iter(range(0)),94))
        ''',("\n","7 invalid\n"),modes=("i64","i128","bigint"))

    def test_next_exhaustion_and_generator_trace(self):
        self.differential('''
            print("ready")
            print(next((x for x in range(int(input())))))
        ''',("0\n","2\n"),modes=("i64","i128","bigint"),trace=True)

    def test_empty_lists_in_for_while_and_nested_loop_bodies(self):
        self.differential('''
            n=int(input())
            words=[]
            for i in range(n):
                words.append(input())
            print(words)
            more=[]
            i=0
            while i<n:
                more.append(str(i))
                i+=1
            print(more)
            nested=[]
            for i in range(n):
                for j in range(2):
                    nested.append(str(i+j))
            print(nested)
        ''',("0\n","2\n猫\nblue\n"),modes=("i64","i128","bigint"),string_mode="unicode")

    def test_nested_filtered_comprehensions_scope_and_exception_order(self):
        self.differential('''
            x=99
            words=[str(x)+str(y) for x in range(4) if x%2 for y in range(x) if y%2==0]
            print(words,x)
            print([input() for i in range(2) if i<int(input())])
        ''',("1\nfirst\n2\nsecond\n","0\n0\n"),modes=("i64","i128","bigint"))

    def test_string_split_separator_maxsplit_and_argument_order(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            text=input()
            print(text.split(),text.split(maxsplit=0),text.split(None,1))
            print(text.split(mark(","),mark(1)))
            print("a,,b,".split(","),"猫猫海猫".split("猫",2))
            print("  a b  ".split(None,0),"  a b  ".split(None,1))
        ''',(" A\u3000猫\tB \n",",a,,b,\n","\n"),modes=("i64","i128","bigint"),string_mode="unicode")

    def test_string_split_errors_and_slices_evaluate_bounds(self):
        self.differential('''
            words=["a","b"]
            print(words[:int(input()):int(input())])
            print("ready")
            print("a".split(input()))
        ''',("2\n1\n\n","2\n0\nignored\n","-1\n-1\nx\n"),modes=("i64","i128","bigint"),trace=True)

    def test_readonly_list_parameters_and_copy_independence(self):
        self.differential('''
            def first(words):
                return words[0]
            words=["猫","sea"]
            copied=words.copy()
            other=list(words)
            words[0]="changed"
            copied.append("new")
            print(first(words),first(copied),first(other))
            print(words,copied,other)
        ''',modes=("i64","i128","bigint"),string_mode="unicode")

    def test_tuple_elements_named_and_destructured_streams(self):
        self.differential('''
            pairs=[(i,str(i)) for i in range(3)]
            pairs.append((3,"猫"))
            print(pairs,pairs[1],pairs[-1])
            for i,word in pairs:
                print(i,word)
            for pair in pairs:
                print(pair)
            print(list(zip([1,2],["a","b"])))
            for pair in zip([1,2],["a","b"]):
                print(pair)
        ''',modes=("i64","i128","bigint"),string_mode="unicode")

    def test_next_tuple_values_enumerate_nested_zip_and_defaults(self):
        self.differential('''
            print(next(zip([1,2],["a","b"]),(9,"default")))
            print(next(enumerate(["cat"],7),(9,"default")))
            print(next(zip(zip([1],["a"]),[3]),((9,"default"),0)))
            print(next(enumerate(zip([1],["a"])),(9,(0,"default"))))
            print(next(zip(),77))
        ''',modes=("i64","i128","bigint"))

    def test_next_empty_nested_generator_still_executes_producer(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print(next((x for x in range(2) if mark(x)>=0 for y in range(0)),"empty"))
            print(next((x for x in range(mark(0))),True))
        ''',modes=("i64","i128","bigint"))

    def test_native_list_repr_escaping_star_and_mixed_arguments(self):
        self.differential(r'''
            words=["a'b",'c"d',"海\\n猫","\x00","\u3000"]
            pair=(3,"cat")
            print(words,*words,pair,sep="|",end="!\\n")
            print(pair,words)
        ''',modes=("i64","i128","bigint"),string_mode="unicode")

    def test_string_list_unpack_and_index_errors(self):
        self.differential('''
            words=input().split()
            left,right=words
            print(left,right)
            words[int(input())]="changed"
            print(words)
        ''',("a b\n1\n","a\n","a b c\n","a b\n2\n"),modes=("i64","i128","bigint"),trace=True)

    def test_structural_lists_feed_reductions_and_callbacks(self):
        self.differential('''
            def nonempty(word):
                return len(word)>0
            def score(pair):
                return pair[0]+len(pair[1])
            words=["","sea","猫"]
            print(any(words),all(words),min(words),max(words))
            print(sum(map(nonempty,words)))
            pairs=[(1,"a"),(3,"cat"),(2,"sea")]
            print(min(pairs),max(pairs),sum(map(score,pairs)))
            print(next(filter(nonempty,words),"none"))
            print(next(map(score,zip([1,2],["a","bb"])),77))
            print(next(filter(score,zip([0,1],["","cat"])),(9,"none")))
        ''',modes=("i64","i128","bigint"),string_mode="unicode")

    def test_nested_tuple_defaults_comparison_and_repr(self):
        self.differential('''
            def keep(value=((2,"cat"),True)):
                return value
            a=keep()
            b=((2,"cat"),1)
            c=((2,"sea"),False)
            print(a,b,c,a==b,a<c,c>a)
            print(min([a,b,c]),max([a,b,c]))
        ''',modes=("i64","i128","bigint"))

    def test_next_constructor_default_and_producer_exception_order(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print(next((1//x for x in range(mark(int(input())))),mark(99)))
        ''',("0\n","2\n"),modes=("i64","i128","bigint"),trace=True)
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            print(next((mark(x) for x in range(0,3,0)),mark(99)))
        ''',modes=("i64","i128","bigint"),trace=True)

    def test_structural_list_sort_sorted_and_stable_reverse_keys(self):
        self.differential('''
            words=["猫","sea","a","bb"]
            words.sort()
            print(words)
            words.sort(key=len,reverse=True)
            print(words)
            print(sorted(word for word in words),words)
            pairs=[(True,"same"),(1,"same"),(False,"z"),(0,"z")]
            pairs.sort(reverse=True)
            print(pairs)
            print(sorted(pairs,key=str,reverse=True))
            print(sorted(x*x for x in range(4)))
        ''',modes=("i64","i128","bigint"),string_mode="unicode")

    def test_sort_key_once_and_sorted_keyword_order_before_iteration(self):
        self.differential('''
            def key(word):
                print(word,end="|")
                return len(word)
            def flag(value):
                print(value,end="|")
                return value
            def item(value):
                print(value,end="|")
                return str(value)
            words=["aaa","b","cc"]
            words.sort(key=key,reverse=flag(True))
            print(words)
            print(sorted((item(x) for x in range(3)),reverse=flag(False)))
        ''',modes=("i64","i128","bigint"))

    def test_owned_list_function_returns_and_shared_aliases(self):
        self.differential('''
            def make(n):
                words=[]
                for i in range(n):
                    words.append(str(i))
                return words
            def copy(words):
                return words.copy()
            words=make(int(input()))
            other=copy(words)
            other.append("new")
            print(words,other)
        ''',("0\n","3\n"),modes=("i64","i128","bigint"))
        for source in (
            'a=["x"];b=a;b.append("y");print(a)',
            'def identity(a):\n return a\na=["x"];b=identity(a);print(a,b)',
        ):
            self.differential(source,modes=("i64","i128","bigint"))
        for mode in ("i64","i128","bigint"):
            self.assertIsNone(try_generate_native('a=["x"]\nfor x in a:a.append(x)',"case.py",mode))

    def test_nested_default_string_helpers_and_debug_bytes_repr(self):
        self.differential('''
            def keep(value=(("a"+"b",2**3),True)):
                return value
            print(keep())
        ''',modes=("i64","i128","bigint"))
        for mode in ("i64","i128","bigint"):
            compiled=self.compile('print([b"a",b"b"])\n',mode,release=False,prune=False)
            self.compare(compiled,mode=mode)


for _name in dir(NativeIteratorReductionTests):
    if _name.startswith("test_") and _name not in NativeTypedListsNextTests.__dict__:
        setattr(NativeTypedListsNextTests,_name,None)
del NativeIteratorReductionTests
