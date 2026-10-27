"""Stable general-runtime sorting, callback rooting, and comparison bounds."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class RuntimeSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="pytors-runtime-sort-")
        path=Path(cls.tmp.name)/'main.rs'
        result=transpile(WRAPPER,TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        path.write_text(result.rust_source);cls.binary=path.with_suffix('')
        built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(cls.binary)],
                             capture_output=True,text=True,timeout=120)
        if built.returncode:raise AssertionError(built.stderr)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def compare(self,source):
        source=textwrap.dedent(source)
        reference=subprocess.run([sys.executable,'-I','-c',WRAPPER],input=source,
                                 capture_output=True,text=True,timeout=30)
        actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=30)
        self.assertEqual(reference.returncode,0,reference.stderr)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,reference.stdout,actual.stderr)

    def test_reverse_uses_less_than_and_preserves_equal_key_order(self):
        self.compare('''
            class Item:
                def __init__(self,key,label):self.key=key;self.label=label
                def __lt__(self,other):return self.key<other.key
                def __gt__(self,other):raise AssertionError('sorting must use less-than')
            for reverse in (False,True):
                values=[Item(2,'a'),Item(1,'b'),Item(2,'c'),Item(1,'d')]
                print([v.label for v in sorted(values,reverse=reverse)])
                values.sort(reverse=reverse)
                print([v.label for v in values])
                print(sorted([(2,'a'),(1,'b'),(2,'c'),(1,'d')],key=lambda x:x[0],reverse=reverse))
        ''')

    def test_general_runtime_comparisons_remain_below_quadratic_growth(self):
        self.compare('''
            calls=0
            class Item:
                def __init__(self,value):self.value=value
                def __lt__(self,other):
                    global calls
                    calls+=1
                    if calls>100000:raise RuntimeError('quadratic sort')
                    return self.value<other.value
            values=[Item((i*2053)%4096) for i in range(4096)]
            result=sorted(values)
            print([v.value for v in result]==list(range(4096)),calls<100000)
        ''')

    def test_originals_and_derived_keys_survive_collection_during_callbacks(self):
        self.compare('''
            import gc
            released=[]
            class Key:
                def __init__(self,value):self.value=value
                def __lt__(self,other):
                    gc.collect()
                    return self.value<other.value
                def __del__(self):released.append(self.value)
            class Item:
                def __init__(self,value):self.value=value
            def items():
                for value in range(15,-1,-1):yield Item(value)
            def key(item):
                gc.collect()
                return Key(item.value)
            result=sorted(items(),key=key)
            print([item.value for item in result])
            gc.collect();print(sorted(released))
        ''')

    def test_key_order_and_existing_values_survive_callback_errors(self):
        self.compare('''
            events=[]
            values=[4,1,3,2]
            def key(value):
                events.append(value)
                if value==3:raise LookupError('key failure')
                return value
            try:sorted(values,key=key)
            except Exception as error:print(type(error).__name__,events,values)
            print(sorted([],key=lambda value:1/0))
            print(sorted([5],key=lambda value:-value))
        ''')
