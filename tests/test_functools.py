"""Bundled functools helpers and their native callable primitives."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys\nimport functools\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class FunctoolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-functools-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="functools_wrapper.py"))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0], expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_exports_and_wrapper_metadata(self):
        self.compare('''
            print(functools.__all__)
            print(functools.WRAPPER_ASSIGNMENTS,functools.WRAPPER_UPDATES)
            def original(value):
                "function documentation"
                return value+1
            original.custom="custom value"
            @functools.wraps(original)
            def wrapper(*args,**kwargs):
                return original(*args,**kwargs)
            print(wrapper(4),wrapper.__name__,wrapper.__qualname__,wrapper.__module__)
            print(wrapper.__doc__,wrapper.custom,wrapper.__wrapped__ is original)
            def another(): pass
            print(functools.update_wrapper(another,original) is another,another.custom)
        ''')

    def test_total_ordering(self):
        self.compare('''
            @functools.total_ordering
            class Number:
                def __init__(self,value): self.value=value
                def __lt__(self,other): return self.value<other.value
                def __eq__(self,other): return isinstance(other,Number) and self.value==other.value
            a,b,c=Number(1),Number(2),Number(1)
            print(a<b,a<=b,a>b,a>=b,a<=c,a>=c,a==c)
            @functools.total_ordering
            class Reversed:
                def __init__(self,value): self.value=value
                def __ge__(self,other): return self.value>=other.value
                def __eq__(self,other): return self.value==other.value
            a,b=Reversed(1),Reversed(2)
            print(a<b,a<=b,a>b,a>=b)
            try:
                @functools.total_ordering
                class Missing: pass
            except ValueError:
                print("missing ordering")
        ''')

    def test_cmp_to_key(self):
        self.compare('''
            key=functools.cmp_to_key(lambda a,b:len(a)-len(b))
            print(sorted(["bbb","a","cc","d"],key=key))
            a,b=key("a"),key("bb")
            print(a<b,a<=b,a>b,a>=b,a==b,a!=b,a.obj)
        ''')

    def test_cached_property_descriptor(self):
        self.compare('''
            class Counter:
                def __init__(self): self.calls=0
                @functools.cached_property
                def value(self):
                    "cached documentation"
                    self.calls+=1
                    return self.calls*10
            counter=Counter()
            print(counter.value,counter.value,counter.calls,Counter.value.__doc__)
            counter.value=99
            print(counter.value,counter.calls)
            del counter.value
            print(counter.value,counter.calls)
            descriptor=functools.cached_property(lambda obj:1)
            try:
                descriptor.__get__(counter)
            except TypeError:
                print("set_name required")
        ''')

    def test_partialmethod_binding(self):
        self.compare('''
            class Cell:
                def change(self,first,second=0):
                    self.value=first+second
                    return self.value
                fixed=functools.partialmethod(change,10,second=2)
                @staticmethod
                def static(first,second): return first+second
                static_fixed=functools.partialmethod(static,3)
                @classmethod
                def class_value(cls,first,second): return cls.__name__,first+second
                class_fixed=functools.partialmethod(class_value,5)
            cell=Cell()
            print(cell.fixed(),cell.fixed(second=4),Cell.fixed(cell))
            print(cell.static_fixed(7),Cell.static_fixed(8))
            print(cell.class_fixed(6),Cell.class_fixed(7))
        ''')

    def test_partialmethod_placeholders_and_flattening(self):
        self.compare('''
            hole=functools.Placeholder
            class Cell:
                def combine(self,a,b,c,d): return a,b,c,d
                first=functools.partialmethod(combine,hole,2,hole,4)
                second=functools.partialmethod(first,1)
            cell=Cell()
            print(cell.first(1,3),cell.second(3),Cell.second(cell,3))
            try:
                functools.partialmethod(Cell.combine,hole)
            except TypeError:
                print("trailing placeholder")
            try:
                functools.partialmethod(Cell.combine,a=hole)
            except TypeError:
                print("keyword placeholder")
        ''')

    def test_partial_placeholder_and_reduce(self):
        self.compare('''
            def combine(a,b,c,d): return a,b,c,d
            hole=functools.Placeholder
            first=functools.partial(combine,hole,2,hole,4)
            print(first(1,3),functools.partial(first,4)(5))
            try:
                first(1)
            except TypeError:
                print("unfilled")
            try:
                functools.partial(combine,a=hole)
            except TypeError:
                print("keyword placeholder")
            try:
                functools.partial(combine,hole,2,hole)
            except TypeError:
                print("trailing placeholder")
            print(functools.reduce(lambda a,b:a+b,[1,2,3]))
            print(functools.reduce(lambda a,b:a+b,[1,2],initial=10))
        ''')

    def test_native_cache_metadata_and_control(self):
        self.compare('''
            calls=[]
            @functools.lru_cache(maxsize=2)
            def square(value):
                calls.append(value)
                return value*value
            print(square(2),square(2),square(3),square(4),square(2),calls)
            info=square.cache_info()
            print(info.hits,info.misses,info.maxsize,info.currsize)
            print(square.__name__,square.__wrapped__(5))
            square.cache_clear()
            print(square.cache_info().currsize,square.cache_parameters())
            @functools.cache
            def plus(value): return value+1
            print(plus(3),plus(3),plus.cache_info().hits)
        ''')

    def test_partial_attributes_and_reduce_consumption_order(self):
        self.compare('''
            def combine(a,b,c=0): return a+b+c
            first=functools.partial(combine,1,c=2)
            second=functools.partial(first,3,c=4)
            print(second.func is combine,second.args,second.keywords,second())
            second.keywords["c"]=5
            print(second())
            second.custom="metadata"
            print(second.__dict__["custom"])
            seen=[]
            def values():
                for value in [1,2,3]:
                    seen.append(("yield",value))
                    yield value
            def add(a,b):
                seen.append(("add",a,b))
                return a+b
            print(functools.reduce(add,values()),seen)
        ''')

    def test_singledispatch_registration_and_mro(self):
        self.compare('''
            @functools.singledispatch
            def describe(value): return "object"
            @describe.register(int)
            def integer(value): return "integer"
            @describe.register(str)
            def string(value): return "string"
            class Base: pass
            class Child(Base): pass
            def base(value): return "base"
            print(describe.register(Base,base) is base)
            print(describe(1),describe(True),describe("x"),describe([]),describe(Child()))
            print(describe.dispatch(int) is integer,describe.registry[object] is describe.__wrapped__)
            try:
                describe.registry[int]=base
            except TypeError:
                print("read only")
            @describe.register(int)
            def replacement(value): return "replacement"
            print(describe(1))
        ''')

    def test_singledispatchmethod_and_abstract_flag(self):
        self.compare('''
            class Visitor:
                @functools.singledispatchmethod
                def visit(self,value): return "object"
                @visit.register(int)
                def integer(self,value): return value+1
                @visit.register(str)
                def string(self,value): return value.upper()
            visitor=Visitor()
            print(visitor.visit(3),visitor.visit("hi"),visitor.visit([]))
            print(Visitor.visit(visitor,3))
            def abstract(self,value): pass
            abstract.__isabstractmethod__=True
            print(functools.partialmethod(abstract,3).__isabstractmethod__)
            print(functools.singledispatchmethod(abstract).__isabstractmethod__)
        ''')

    def test_singledispatch_registration_from_annotations(self):
        self.compare('''
            @functools.singledispatch
            def describe(value): return "object"
            @describe.register
            def integer(value:int): return "integer"
            print(describe(1),describe(True),describe("s"))
            print(integer.__annotations__["value"] is int)
        ''')


if __name__ == "__main__":
    unittest.main()
