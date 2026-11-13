"""Original source comparison callbacks share the fallible stable sorter."""
import shutil,unittest
import test_native_stdio as stdio_tests


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeRichSortingTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_comparison_trace_reverse_and_equal_key_stability(self):
        source='''class Item:
    def __init__(self,value,label):self.value=value;self.label=label
    def __lt__(self,other):
        print(self.label,other.label)
        return self.value<other.value
values=list(map(int,input().split()))
items=[Item(value,i) for i,value in enumerate(values)]
result=sorted(items,reverse=bool(int(input())))
print([item.label for item in result])
print([item.label for item in items])
'''
        values=[5,1,3,1,2,5,0,2,4,3]
        larger=[(i*17)%11 for i in range(100)]
        self.differential(source,[(' '.join(map(str,x))+'\n'+str(reverse)+'\n').encode()
                                  for x in [values,larger]for reverse in [0,1]],profiles=(False,True))

    def test_key_function_can_return_source_ordering_object(self):
        source='''class Rank:
    def __init__(self,value):self.value=value
    def __lt__(self,other):
        print(self.value,other.value)
        return self.value<other.value

def key(value):
    print('key',value)
    return Rank(value%3)

values=list(map(int,input().split()))
print(sorted(values,key=key,reverse=True))
values.sort(key=key)
print(values)
'''
        self.differential(source,[b'4 0 6 8 2 3 5 1\n',b'\n',b'9\n'],profiles=(False,True))

    def test_reflected_comparison_and_integer_truth_results(self):
        source='''class Item:
    def __init__(self,value):self.value=value
    def __lt__(self,other):
        print('lt',self.value,other.value)
        return NotImplemented
    def __gt__(self,other):
        print('gt',self.value,other.value)
        return int(self.value>other.value)
items=[Item(value) for value in list(map(int,input().split()))]
items.sort(reverse=True)
print([item.value for item in items])
'''
        self.differential(source,[b'7 2 8 1 2 4\n',b'\n'],profiles=(False,True))

    def test_comparator_errors_keep_prior_observable_effects(self):
        source='''class Item:
    def __init__(self,value):self.value=value
    def __lt__(self,other):
        print('compare',self.value,other.value)
        if self.value==0:return 1//0
        return self.value<other.value
items=[Item(value) for value in list(map(int,input().split()))]
print('start')
items.sort()
print([item.value for item in items])
'''
        self.differential(source,[b'4 3 0 1\n',b'4 2 1\n'],profiles=(False,True))

    def test_sort_detaches_list_and_detects_callback_modification(self):
        source='''class Item:
    def __init__(self,value):self.value=value
    def __lt__(self,other):
        print('length',len(items))
        items.append(Item(100))
        return self.value<other.value
items=[Item(value) for value in list(map(int,input().split()))]
items.sort()
print([item.value for item in items])
'''
        self.differential(source,[b'4 1 3 2\n',b'7\n'],profiles=(False,True))

    def test_heterogeneous_source_types_keep_generic_notimplemented_schedule(self):
        source='''class First:
    def __init__(self,value):self.value=value
    def __lt__(self,other):
        print('first lt',self.value,other.value)
        return NotImplemented
    def __gt__(self,other):
        print('first gt',self.value,other.value)
        return self.value>other.value
class Second:
    def __init__(self,value):self.value=value
    def __lt__(self,other):
        print('second lt',self.value,other.value)
        return NotImplemented
    def __gt__(self,other):
        print('second gt',self.value,other.value)
        return self.value>other.value
items=[First(value) if value%2 else Second(value) for value in list(map(int,input().split()))]
print([item.value for item in sorted(items)])
'''
        self.differential(source,[b'7 2 5 8 4 1\n',b'9 7 1 3\n',b'8 6 2 4\n'],profiles=(False,True))

    def test_sorted_output_widening_does_not_change_original_cursor_payload(self):
        source='''class Item:
    def __init__(self,value):self.value=value
    def __lt__(self,other):return self.value<other.value
original=[Item(value) for value in list(map(int,input().split()))]
result=sorted(original)
result[0]=None
print([item.value for item in original])
print(result[0] is None,len(result),len(original))
'''
        self.differential(source,[b'4 1 3 2\n',b'5\n'],profiles=(False,True))
