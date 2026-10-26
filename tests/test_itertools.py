"""Lazy itertools behavior, including shared cursors and input consumption."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys\nimport itertools\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ItertoolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-itertools-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="itertools_wrapper.py"))
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

    def test_infinite_iterators_are_lazy(self):
        self.compare('''
            print(list(itertools.islice(itertools.count(), 6)))
            print(list(itertools.islice(itertools.count(2, -3), 6)))
            print(list(itertools.islice(itertools.count(0.5,0.25), 5)))
            print(list(itertools.islice(itertools.cycle([1,2,3]), 8)))
            print(list(itertools.cycle([])))
            print(list(itertools.islice(itertools.repeat("x"), 4)))
            print(list(itertools.repeat("x",3)), list(itertools.repeat("x",-2)))
            print(list(itertools.islice(itertools.count(True),3)))
            print(list(itertools.islice(itertools.count(True,2),3)))
        ''')

    def test_combinatorial_iterators(self):
        self.compare('''
            print(list(itertools.combinations("ABCD",2)))
            print(list(itertools.combinations_with_replacement("ABC",2)))
            print(list(itertools.permutations("ABC",2)))
            print(list(itertools.product("AB",range(2),repeat=2)))
            for make in [itertools.combinations,itertools.combinations_with_replacement,itertools.permutations]:
                print(list(make([],0)),list(make([],1)),list(make([1],3)))
            print(list(itertools.product()),list(itertools.product([],repeat=0)),list(itertools.product([])))
        ''')

    def test_transform_predicate_and_accumulation(self):
        self.compare('''
            print(list(itertools.accumulate([1,2,3,4])))
            print(list(itertools.accumulate([1,2,3],lambda a,b:a*b,initial=2)))
            print(list(itertools.accumulate([],initial=3)))
            print(list(itertools.accumulate([1,2],initial=None)))
            print(list(itertools.compress("ABCDEF",[1,0,1,0,1])))
            print(list(itertools.dropwhile(lambda x:x<3,[1,2,3,1])))
            print(list(itertools.takewhile(lambda x:x<3,[1,2,3,1])))
            print(list(itertools.filterfalse(None,[0,1,None,[],[1]])))
            print(list(itertools.filterfalse(lambda x:x%2,range(6))))
            print(list(itertools.starmap(pow,[(2,3),(3,2)])))
            print(list(itertools.pairwise("ABCD")))
        ''')

    def test_chain_and_zip_longest(self):
        self.compare('''
            print(list(itertools.chain([1,2],[],(3,4))))
            print(list(itertools.chain.from_iterable([[1,2],[],[3]])))
            print(list(itertools.zip_longest("AB",[1],fillvalue="missing")))
            print(list(itertools.zip_longest()),list(itertools.zip_longest([],[])))
            print(list(itertools.islice(itertools.zip_longest(itertools.count(),[1]),4)))
        ''')

    def test_batched_and_strict(self):
        self.compare('''
            print(list(itertools.batched("ABCDEFG",3)))
            print(list(itertools.batched([],2,strict=True)))
            print(list(itertools.batched(range(4),2,strict=True)))
            try:
                print(list(itertools.batched(range(5),2,strict=True)))
            except ValueError:
                print("incomplete")
        ''')

    def test_groupby_shared_group_lifetimes(self):
        self.compare('''
            print([(key,list(group)) for key,group in itertools.groupby("AAAABBBCCDAABBB")])
            print([(key,list(group)) for key,group in itertools.groupby([1,3,2,4,5],lambda x:x%2)])
            groups = itertools.groupby("AABBCC")
            key,first = next(groups)
            print(key,next(first))
            key,second = next(groups)
            print(key,list(first),list(second))
            key,third = next(groups)
            print(key,list(second),list(third),list(groups))
            groups = itertools.groupby("AABB")
            captured = list(groups)
            print([(key,list(group)) for key,group in captured])
        ''')

    def test_tee_shared_buffer_and_flattening(self):
        self.compare('''
            a,b = itertools.tee(range(6))
            print(next(a),next(a),next(b))
            c,d = itertools.tee(a)
            print(next(c),next(d),next(a))
            print(list(a),list(b),list(c),list(d))
            a,b,c = itertools.tee(itertools.count(10),3)
            print(list(itertools.islice(a,5)),list(itertools.islice(b,3)),list(itertools.islice(c,7)))
            print(itertools.tee([],0))
            source = [[1],[2]]
            a,b = itertools.tee(source)
            item = next(a)
            item.append(3)
            print(next(b) is item,list(b))
        ''')

    def test_input_consumption_order(self):
        self.compare('''
            seen=[]
            def source(label,items):
                for item in items:
                    seen.append((label,item))
                    yield item
            value = itertools.compress(source("d",[1,2,3]),source("s",[0,1]))
            print(list(value),seen)
            seen.clear()
            value = itertools.chain.from_iterable(source("outer",[source("a",[1,2]),source("b",[3])]))
            print(next(value),[(label, str(item) if label!="outer" else "iterable") for label,item in seen])
            seen.clear()
            values=iter(range(10))
            print(list(itertools.islice(values,5,2)),next(values))
            values=iter(range(10))
            print(list(itertools.islice(values,0,5,10)),next(values))
            value=itertools.groupby(source("g",[1,1,2]))
            key,group=next(value)
            print(key,seen)
            print(next(group),seen)
            print(next(group),seen)
            key,group=next(value)
            print(key,seen,list(group))
        ''')

    def test_argument_validation_and_keywords(self):
        self.compare('''
            print(list(itertools.accumulate(iterable=[1,2],func=None,initial=4)))
            print(list(itertools.batched(iterable=[1,2,3],n=2)))
            print(list(itertools.combinations(iterable=[1,2],r=1)))
            print(list(itertools.repeat(object=1,times=2)))
            print(list(itertools.islice([1,2],None,None,None)))
            bad=[lambda:itertools.batched([],0),lambda:itertools.combinations([], -1),lambda:itertools.tee([], -1),lambda:itertools.islice([],0,2,0),lambda:itertools.islice([], -1),lambda:itertools.product([],repeat=-1)]
            for call in bad:
                try:
                    call()
                except ValueError:
                    print("value")
            bad=[lambda:itertools.cycle(iterable=[]),lambda:itertools.tee([],n=2),lambda:itertools.repeat(1,None),lambda:itertools.count("x"),lambda:itertools.chain(x=[])]
            for call in bad:
                try:
                    call()
                except TypeError:
                    print("type")
        ''')

    def test_gc_keeps_shared_and_buffered_values(self):
        self.compare('''
            def source():
                for i in range(3000):
                    yield [i]
            a,b=itertools.tee(source())
            first=list(a)
            second=list(b)
            print(len(first),len(second),first[100] is second[100],sum(item[0] for item in second))
            values=list(itertools.islice(itertools.cycle(source()),6001))
            print(len(values),values[0] is values[3000],values[-1])
        ''')

    def test_iterator_state_after_errors(self):
        self.compare('''
            def combine(a,b):
                if b==2:
                    raise ValueError("bad")
                return a+b
            class Flaky:
                def __init__(self): self.i=0
                def __iter__(self): return self
                def __next__(self):
                    self.i+=1
                    if self.i==2: raise ValueError("bad")
                    if self.i==5: raise StopIteration
                    return self.i
            for values in [itertools.accumulate([1,2,3],combine),itertools.chain([1],1,[2]),itertools.zip_longest(Flaky(),range(10))]:
                result=[]
                for i in range(5):
                    try: result.append(next(values))
                    except ValueError: result.append("ValueError")
                    except TypeError: result.append("TypeError")
                    except StopIteration: result.append("StopIteration")
                print(result)
        ''')


if __name__ == "__main__":
    unittest.main()
