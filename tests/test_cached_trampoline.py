"""Cached Python functions share the heap-frame call trampoline."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = '''\
import sys
from functools import cache
@cache
def static_descend(n):
    return 0 if n == 0 else static_descend(n-1)+1
static_events=[]
@cache
def static_count(n):
    static_events.append(n)
    return static_count(n+1)
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class CachedTrampolineTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-cache-trampoline-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        built = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                             expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_deep_cached_aot_and_dynamic_frames(self):
        self.compare('''
            from functools import lru_cache
            sys.setrecursionlimit(10000)
            print(static_descend(5000), static_descend.cache_info().currsize)
            print(static_descend(5000), static_descend.cache_info().hits)
            @lru_cache(16)
            def dynamic_descend(n):
                return 0 if n == 0 else dynamic_descend(n-1)+1
            print(dynamic_descend(2500), dynamic_descend.cache_info())
        ''')

    def test_exceptions_caught_inside_the_call_chain_and_retry(self):
        self.compare('''
            from functools import cache
            calls=[]
            @cache
            def f(n):
                calls.append(n)
                if n==0:raise ValueError('leaf')
                try:return f(n-1)+1
                except ValueError:
                    if n==1:raise
                    return 40
            print(f(4),f.cache_info(),calls)
            print(f(4),f.cache_info(),calls)
            for i in range(2):
                try:f(0)
                except ValueError as error:print(type(error).__name__,str(error))
            print(f.cache_info(),calls)
            @cache
            def invalid(x):return x
            for action in [lambda:invalid(),lambda:invalid(1,2),lambda:invalid([])]:
                try:action()
                except TypeError:print('invalid')
            print(invalid.cache_info())
        ''')

    def test_clear_during_recursion_and_reentrant_same_key(self):
        self.compare('''
            from functools import lru_cache
            for maximum in [None,0,1,3]:
                @lru_cache(maximum)
                def descend(n):
                    if n==0:descend.cache_clear()
                    return n if n==0 else descend(n-1)+1
                print(maximum,descend(4),descend.cache_info(),descend(4),descend.cache_info())
                entered=False
                @lru_cache(maximum)
                def same(x):
                    global entered
                    if not entered:
                        entered=True
                        same(x)
                        return 'outer'
                    return 'inner'
                print(maximum,same(1),same(1),same.cache_info())
        ''')

    def test_nested_bound_and_generic_fallback_callables(self):
        self.compare('''
            from functools import cache,lru_cache,partial
            @cache
            @lru_cache(4)
            def nested(n):
                return 0 if n==0 else nested(n-1)+1
            print(nested(300),nested.cache_info(),nested.__wrapped__.cache_info())
            class Counter:
                @cache
                def descend(self,n):
                    return n if n==0 else self.descend(n-1)+1
            counter=Counter()
            print(counter.descend(300),Counter.descend.cache_info())
            print(counter.descend.cache_info(),counter.descend.__wrapped__ is Counter.descend.__wrapped__)
            print(counter.descend.__dict__ is Counter.descend.__dict__)
            print(Counter.descend.__get__(counter,Counter).__self__ is counter)
            class BoundTarget:
                def run(self,n):
                    return n if n==0 else bound(n-1)+1
            bound=cache(BoundTarget().run)
            print(bound(300),bound.cache_info())
            def body(first,second,*,scale=1):return (first+second)*scale
            f=cache(partial(body,3,scale=2))
            print(f(4),f(4),f.cache_info())
            class Callable:
                def __call__(self,x):return x+9
            f=cache(Callable())
            print(f(1),f(1),f.cache_info())
            @cache
            def generator(x):yield x
            first=generator(7)
            print(first is generator(7),list(first),list(generator(7)))
        ''')

    def test_kwargs_lru_metadata_and_cache_hits(self):
        self.compare('''
            from functools import lru_cache
            events=[]
            @lru_cache(2,typed=True)
            def f(a=0,*,b=1):
                events.append((a,b))
                return a+b
            for action in [lambda:f(1,b=2),lambda:f(1,b=2),lambda:f(a=1,b=2),
                           lambda:f(b=2,a=1),lambda:f(1,b=2),lambda:f(1.0,b=2)]:
                print(action())
            print(events,f.cache_info(),f.cache_parameters(),f.__name__)
            print(f.__wrapped__(5,b=7),f.cache_info())
            f.cache_clear()
            print(f.cache_info())
        ''')

    def test_continuation_keys_and_wrappers_are_gc_roots(self):
        self.compare('''
            import gc
            from functools import cache
            events=[]
            class Key:
                def __del__(self):events.append('deleted')
            @cache
            def f(key,n):
                if n:
                    value=f(key,n-1)
                else:
                    f.cache_clear()
                    value=42
                del key
                gc.collect()
                return value
            print(f(Key(),120),events,f.cache_info().currsize)
            f.cache_clear()
            gc.collect()
            print(events)
            holder={}
            def body(x):
                holder.clear()
                gc.collect()
                return x+1
            holder['f']=cache(body)
            print(holder['f'](4),holder)
        ''')

    def test_recursion_limit_raises_python_exception_without_host_overflow(self):
        self.compare('''
            from functools import cache
            sys.setrecursionlimit(200)
            @cache
            def f(n):
                if n==0:return 0
                try:return f(n-1)+1
                except RecursionError:return 1000
            value=f(1000)
            print(value>=1000, f.cache_info().currsize>100)
            print(f(0),f(0),f.cache_info().hits>0)
        ''')

    def test_reentrant_key_comparison_clear_and_collection(self):
        self.compare('''
            import gc
            from functools import lru_cache
            for maximum in [None,2]:
                events=[]
                active=False
                class Key:
                    def __init__(self,n):self.n=n
                    def __hash__(self):return 9
                    def __eq__(self,other):
                        events.append(('eq',self.n,other.n))
                        if active:
                            f.cache_clear()
                            gc.collect()
                        return self.n==other.n
                @lru_cache(maximum)
                def f(key):
                    events.append(('body',key.n))
                    return key.n
                f(Key(1))
                active=True
                print(maximum,f(Key(1)),f.cache_info(),events)
        ''')

    def test_exact_recursion_budget_and_side_effect_boundary(self):
        self.compare('''
            from functools import cache,lru_cache
            for limit in [60,100]:
                sys.setrecursionlimit(limit)
                static_events.clear()
                static_count.cache_clear()
                try:static_count(0)
                except RecursionError:pass
                print('aot',limit,len(static_events),static_events[-1],static_count.cache_info())
                for kind in ['plain','cache','bounded','nested','bound']:
                    events=[]
                    def body(n):
                        events.append(n)
                        return target(n+1)
                    if kind=='plain':target=body
                    elif kind=='cache':target=cache(body)
                    elif kind=='bounded':target=lru_cache(2)(body)
                    elif kind=='nested':target=cache(lru_cache(2)(body))
                    else:
                        class C:
                            @cache
                            def method(self,n):
                                events.append(n)
                                return self.method(n+1)
                        obj=C()
                        target=obj.method
                    try:target(0)
                    except RecursionError:pass
                    print(kind,limit,len(events),events[-1])
                    if kind in ['cache','bounded','nested']:print(target.cache_info())
        ''')
