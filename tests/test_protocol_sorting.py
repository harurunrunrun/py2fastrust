"""Sorting suspends callbacks and restores its detached list on every exit."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

WRAPPER = "import sys,gc,functools\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc required")
class ProtocolSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-sort-protocol-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        build = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise AssertionError(build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=40)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=40)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_empty_visibility_reverse_timing_and_original_key_order(self):
        self.compare('''
            events=[];values=[3,1,2]
            class Reverse:
                def __bool__(self):events.append(('reverse',list(values)));return True
            def key(value):
                events.append(('key',value,list(values)))
                gc.collect();return value
            print(values.sort(key=key,reverse=Reverse()),values,events)
            events=[]
            class Item:
                def __init__(self,value):self.value=value
                def __lt__(self,other):
                    if values:raise AssertionError('sort exposed original values')
                    gc.collect();return self.value<other.value
                def __gt__(self,other):raise AssertionError('sort must use __lt__')
            values=[Item(3),Item(1),Item(2)]
            values.sort(reverse=True)
            print([item.value for item in values])
        ''')

    def test_mutation_detection_including_zero_net_length_and_nested_sort(self):
        self.compare('''
            for mode in ['append','append_pop','insert_clear','slice','extend','iadd','initialize','nested','empty_extend']:
                values=[3,1,2]
                def key(value):
                    if mode=='append':values.append(7)
                    elif mode=='append_pop':values.append(7);values.pop()
                    elif mode=='insert_clear':values.insert(0,7);values.clear()
                    elif mode=='slice':values[:]=[7];del values[:]
                    elif mode=='extend':values.extend([7]);values.clear()
                    elif mode=='iadd':list.__iadd__(values,[7]);values.clear()
                    elif mode=='initialize':list.__init__(values,[7]);values.clear()
                    elif mode=='nested':values.sort()
                    else:values.extend([])
                    return value
                try:values.sort(key=key)
                except ValueError as error:print(mode,type(error).__name__,str(error),values)
                else:print(mode,'ok',values)
        ''')

    def test_failure_restores_values_and_preserves_original_exception(self):
        self.compare('''
            for mutation in [False,True]:
                values=[4,1,3,2];seen=[]
                def key(value):
                    seen.append(value)
                    if mutation:values.append('temporary')
                    if value==3:raise LookupError('key failure')
                    return value
                try:values.sort(key=key)
                except LookupError as error:print(str(error),seen,values)
                values.sort();print(values)
            class Item:
                def __init__(self,n):self.n=n
                def __lt__(self,other):raise LookupError('comparison failure')
            values=[Item(3),Item(1),Item(2)]
            try:values.sort()
            except LookupError as error:print(str(error),sorted(item.n for item in values))
            def stop(value):raise StopIteration('key stopped')
            values=[2,1]
            print(next(iter(lambda:values.sort(key=stop),None),'default'),values)
        ''')

    def test_sorted_source_consumption_precedes_keyword_and_reverse_checks(self):
        self.compare('''
            events=[]
            class Source:
                def __iter__(self):events.append('iter');return iter([3,1,2])
                def __len__(self):events.append('len');return 3
            class Reverse:
                def __bool__(self):events.append('reverse');gc.collect();return True
            print(sorted(Source(),reverse=Reverse()),events)
            for kwargs in [{'bad':1},{'reverse':Reverse(),'bad':1}]:
                events.clear()
                try:sorted(Source(),**kwargs)
                except TypeError as error:print(type(error).__name__,events)
            values=[2,1]
            for operation in [lambda:values.sort(1),lambda:values.sort(bad=1),lambda:sorted(values,1),lambda:sorted()]:
                try:operation()
                except TypeError:print('bad arguments',values)
        ''')

    def test_recursive_key_comparison_reverse_and_iterable_callbacks(self):
        self.compare('''
            def key(value):return sorted([value],key=key)[0]
            class Item:
                def __lt__(self,other):return sorted([self,other])[0] is self
            class Reverse:
                def __bool__(self):return bool(sorted([1],reverse=self))
            class Source:
                def __iter__(self):return iter(sorted(self))
            class Hint:
                def __iter__(self):return iter([1])
                def __len__(self):return len(sorted(self))
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('key',lambda:sorted([1],key=key)),('lt',lambda:sorted([Item(),Item()])),('reverse',lambda:sorted([1],reverse=Reverse())),('iter',lambda:sorted(Source())),('len',lambda:sorted(Hint()))]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
        ''')

    def test_stability_gc_roots_and_subclass_native_descriptor(self):
        self.compare('''
            released=[]
            class Key:
                def __init__(self,n):self.n=n
                def __lt__(self,other):gc.collect();return self.n<other.n
                def __del__(self):released.append(self.n)
            class L(list):
                def sort(self):raise AssertionError('explicit native descriptor must bypass override')
            for reverse in [False,True]:
                values=L([(2,'a'),(1,'b'),(2,'c'),(1,'d')])
                def key(value):gc.collect();return Key(value[0])
                print(list.sort(values,key=key,reverse=reverse),values)
                gc.collect();print(sorted(released));released.clear()
        ''')

    def test_empty_extension_length_hint_reservation_counts_as_mutation(self):
        self.compare('''
            for mode in ['generator','iterator','empty_list','positive','zero','hint_zero','missing','not_implemented']:
                values=[2,1]
                class Source:
                    def __iter__(self):return iter([])
                    if mode=='positive':
                        def __len__(self):gc.collect();return 3
                    if mode=='zero':
                        def __len__(self):return 0
                    if mode=='hint_zero':
                        def __length_hint__(self):return 0
                    if mode=='not_implemented':
                        def __length_hint__(self):return NotImplemented
                def key(value):
                    if mode=='generator':values.extend(item for item in [])
                    elif mode=='iterator':values.extend(iter([]))
                    elif mode=='empty_list':values.extend([])
                    else:values.extend(Source())
                    return value
                try:values.sort(key=key);print(mode,'ok',values)
                except ValueError:print(mode,'modified',values)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                class Source:
                    def __iter__(self):list.__iadd__([],self);return iter([])
                try:list.__iadd__([],Source())
                except RecursionError:print(limit,'iadd caught')
                def mapped(value):
                    target=[];target+=map(mapped,[value]);return value
                try:mapped(1)
                except RecursionError:print(limit,'iadd map caught')
        ''')
