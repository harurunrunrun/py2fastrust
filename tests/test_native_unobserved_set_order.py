"""Set order is hidden by proved typed consumers rather than exposed publicly."""
import shutil,unittest
import test_native_stdio as stdio_tests
from py2fastrust import transpile,TranspileOptions

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class UnobservedSetOrderTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_canonical_constructor_aliases_and_shared_set_owner(self):
        self.differential('''collect=list
make_unique=set
source=make_unique(map(int,input().split()))
other=source
values=collect(other)
values.sort()
other.add(11)
print(values,sorted(source),source is other)
''',[b'5 1 5 -3 7 1\n',b'\n'],profiles=(False,True))

    def test_chained_and_saved_list_aliases_keep_identity(self):
        self.differential('''def normalize(source):
    a=b=list(set(source))
    saved=b
    saved.sort(reverse=True)
    print(a is b,b is saved)
    return a
print(normalize([5,1,3,1]))
''',profiles=(False,True))

    def test_source_forwarding_and_sorted_builtin_alias(self):
        self.differential('''def forward(items): return items
sort_values=sorted
def run():
    values=list(set([5,2,1,5]))
    forwarded=forward(values)
    ordered=sort_values(forwarded)
    forwarded.sort()
    print(ordered,values,forwarded is values)
run()
''',profiles=(False,True))

    def test_only_sorted_results_escape_the_local_frame(self):
        self.differential('''order=sorted
def normalize(values):
    result=list(set(values))
    count=len(result)
    print(count)
    return order(result,reverse=True)
print(normalize([4,1,9,1]))
''',profiles=(False,True))

    def test_comprehension_reads_follow_order_erasure(self):
        self.differential('''def ranks(values):
    unique=list(set(values))
    unique.sort()
    return {value:index for index,value in enumerate(unique)}
print(ranks([4,1,9,4]))
''',profiles=(False,True))

    def test_source_helper_performs_in_place_order_erasure(self):
        self.differential('''def normalize(items,reverse=False):
    alias=items
    alias.sort(reverse=reverse)
    return alias
def run():
    values=list(set([8,-1,4,8]))
    ordered=normalize(values,reverse=True)
    print(values,ordered,values is ordered)
run()
''',profiles=(False,True))

    def test_all_conditional_paths_erase_order(self):
        self.differential('''flag=int(input())
a=list(set([5,2,7,2]))
b=a
if flag:
    b.sort(reverse=True)
else:
    a.sort()
print(a,b)
''',[b'0\n',b'1\n'],profiles=(False,True))

    def test_later_sort_covers_paths_previously_sorted(self):
        self.differential('''flag=int(input())
a=list(set([5,2,7,2]))
if flag:
    a.sort(reverse=True)
a.sort()
print(a)
''',[b'0\n',b'1\n'],profiles=(False,True))

    def test_finite_set_and_list_sources_keep_duplicate_and_alias_semantics(self):
        self.differential('''flag=int(input())
source={8,1,8} if flag else [8,1,8]
values=list(source)
saved=values
values=[]
saved.sort()
print(values,saved)
''',[b'0\n',b'1\n'],profiles=(False,True))

    def test_first_bool_integer_representatives_and_tuple_keys(self):
        self.differential('''a=list(set([True,1,False,0,3]))
a.sort()
print(a)
b=list(set([(True,'x'),(1,'x'),(False,'y'),(0,'y'),(2,'z')]))
b.sort(reverse=True)
print(b)
''',profiles=(False,True))

    def test_empty_and_unicode_key_tables(self):
        self.differential('''def run(text):
    a=list(set(text))
    a.sort()
    return a
print(run(input()))
''',[b'\n','猫α🦀猫é\n'.encode()],profiles=(False,True),string_mode='unicode')


class UnobservedSetOrderGuards(unittest.TestCase):
    def reject(self,source):
        for mode in ('i64','i128','bigint'):
            with self.subTest(integer=mode,source=source):
                result=transpile(source,TranspileOptions(integer=mode,filename='order.py'))
                self.assertFalse(result.success)
                self.assertTrue(result.diagnostics)
                self.assertIn('unobserved set traversal',result.diagnostics[0].message)
                self.assertGreater(result.diagnostics[0].line,0)

    def test_direct_and_alias_order_observers_are_rejected(self):
        for continuation in ['print(a)','saved=a\nprint(saved)','print(a[0])','other=[a]','return a']:
            source='def run():\n    a=list(set([4,1,9,1]))\n'+''.join('    '+line+'\n'for line in continuation.splitlines())+'    a.sort()\nrun()\n'
            self.reject(source)

    def test_published_namespace_abrupt_paths_do_not_hide_order(self):
        self.reject('''def fail(items):
    1//0
    items.sort()
values=list(set([4,1,9]))
fail(values)
''')
        self.reject('''if int(input()): reverse=True
values=list(set([4,1,9]))
values.sort(reverse=reverse)
''')
        self.reject('''values=list(set([4,1,9]))
1//0
values.sort()
''')
        self.reject('''values=list(set([4,1,9]))
print('before')
values.sort()
''')

    def test_class_publication_and_generator_captures_do_not_hide_escapes(self):
        self.reject('''class Published:
    values=list(set([4,1,9]))
print(Published.values)
''')

    def test_original_allocation_must_be_erased_not_only_a_copy(self):
        self.reject('a=list(set([4,1,9]))\nb=sorted(a)\nprint(a,b)\n')

    def test_conditional_rebinding_does_not_prove_the_wrong_allocation(self):
        self.reject('flag=int(input())\na=list(set([4,1,9]))\nold=a\nif flag:\n    a=[]\na.sort()\nprint(old)\n')

    def test_short_circuit_sort_does_not_dominate_an_observer(self):
        self.reject('flag=int(input())\na=list(set([4,1,9]))\nflag and a.sort()\nprint(a)\n')
        self.reject('flag=int(input())\na=list(set([4,1,9]))\nflag < 0 < (a.sort() or 3)\nprint(a)\n')

    def test_unknown_callbacks_and_captured_aliases_are_rejected(self):
        self.reject('''def inspect(): print(a)
a=list(set([4,1,9]))
inspect()
a.sort()
''')
        self.reject('''def identity(items,flag):
    if flag: return []
    return items
flag=int(input())
a=list(set([4,1,9]))
b=identity(a,flag)
b.sort()
print(a)
''')

    def test_key_and_reverse_callbacks_cannot_observe_unsorted_storage(self):
        self.reject('''a=list(set([4,1,9]))
a.sort(key=lambda x:x)
print(a)
''')
        self.reject('''def inspect(items):
    print(items)
    return False
a=list(set([4,1,9]))
a.sort(reverse=inspect(a))
print(a)
''')

    def test_cleanup_handlers_and_zero_iteration_paths_are_rejected(self):
        self.reject('''class Cleanup:
    def __enter__(self): return self
    def __exit__(self,a,b,c): return False
a=list(set([4,1,9]))
with Cleanup():
    a.sort()
''')
        self.reject('''a=list(set([4,1,9]))
for _ in range(int(input())):
    a.sort()
print(a)
''')

    def test_existing_custom_finalizer_and_float_key_boundaries_remain_specific(self):
        for source,part in [('''class Finalizer:
    def __del__(self): print('finalizer')
a=list(set([1,3]))
a.sort()
''','__del__'),('a=list(set([1.0,2.0]))\na.sort()\n','key'),('''def make():
    captured=(values for _ in range(1))
    values=list(set([4,1,9]))
    return captured
print(list(make()))
''','generator expression')]:
            result=transpile(source,TranspileOptions(filename='boundary.py'))
            self.assertFalse(result.success)
            self.assertIn(part,result.diagnostics[0].message)

