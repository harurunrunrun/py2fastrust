"""Common typed list searches preserve bounds, equality, and evaluation order."""
from pathlib import Path
import itertools
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeListSearchTests(unittest.TestCase):
    def compare(self,source,inputs=("",),modes=("i64","i128","bigint"),profiles=(False,True)):
        expected=[subprocess.run([sys.executable,"-I","-c",source],input=data,text=True,
                                 capture_output=True,timeout=5)for data in inputs]
        with tempfile.TemporaryDirectory(prefix="pytors-list-search-")as directory:
            root=Path(directory)
            for mode,release in itertools.product(modes,profiles):
                with self.subTest(integer=mode,release=release):
                    result=transpile(source,TranspileOptions(integer=mode,string_mode="unicode"))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,"native")
                    for marker in ("enum Value","enum Op","struct Runtime","fn step("):
                        self.assertNotIn(marker,result.rust_source)
                    rust=root/'main.rs';rust.write_text(result.rust_source)
                    binary=root/'main'
                    build=subprocess.run(["rustc","--edition=2021",*(["-O"]if release else []),
                                          str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(build.returncode,0,build.stderr)
                    for data,reference in zip(inputs,expected):
                        actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=5,
                                              env={"PATH":"/unavailable","PYTHONPATH":"/unavailable"})
                        self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),
                                         actual.stderr+reference.stderr+data)
                        if reference.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1],reference.stderr.splitlines()[-1])

    def test_first_index_and_count_and_disjoint_primitive_types(self):
        self.compare('''a=[7,2,7,3,7]
print(a.index(7),a.index(7,1),a.index(7,-2),a.count(7),a.count(0))
print(a.count("7"),a.count(None),a.count(True))
print([True,1,False,0,True].count(1),[True,1,False,0,True].index(0))
print(["猫","海","猫"].count("猫"),["猫","海","猫"].index("海"))
print([b"ab",b"x",b"ab"].count(b"ab"),[b"ab",b"x"].index(b"x"))
print([].count(3))
''')

    def test_bounds_and_value_error(self):
        source='''a=[3,1,3,2,3]
start,stop=map(int,input().split())
print("before")
print(a.index(3,start,stop))
print("after")
'''
        bounds=[-2**63,-100,-5,-1,0,1,3,5,100,2**63-1]
        self.compare(source,[f"{start} {stop}\n"for start,stop in itertools.product(bounds,bounds)])

    def test_empty_missing_and_reversed_ranges(self):
        for source in ('print([].index(1))\n','print([1,2].index(9))\n',
                       'print([1,2].index(1,2,0))\n'):
            self.compare(source)

    def test_argument_effects_and_receiver_snapshot(self):
        self.compare('''def make():
    print("receiver")
    return [2,7,2,9]
def mark(value):
    print(value)
    return value
print(make().index(mark(2),mark(1),mark(4)))
print(make().count(mark(2)))
a=[3,2,3]
print(a.index(a.pop()),a)
print(a.count(a.pop()),a)
''')

    def test_argument_failure_precedes_search(self):
        source='''def mark(value):
    print(value)
    return value
a=[]
print(a.index(mark(1),mark(2)OPint(input()),mark(3)))
'''
        for operator in ("//","%"):
            self.compare(source.replace("OP",operator),("0\n","1\n"))

    def test_tuples_nullable_values_and_structural_numeric_equality(self):
        self.compare('''a=[(True,"x"),(1,"x"),(False,"y"),(0,"y")]
print(a.index((1,"x")),a.count((True,"x")))
print(a.index((False,"y")),a.count((0,"y")))
b=[None,"a",None,"a"]
print(b.index(None),b.count(None),b.index("a"),b.count("a"))
c=[(b"a",1),(b"b",2),(b"a",True)]
print(c.count((b"a",1)),c.index((b"b",2)))
print((b"a",1)<(b"b",0),(b"a",1)==(b"a",True))
''')

    def test_specialized_function_consumers(self):
        self.compare('''def locate(values,needle,start=0):
    return values.index(needle,start)
def copies(values,needle):
    return values.count(needle)
print(locate([2,3,2],2,1),copies(["a","b","a"],"a"))
''')

    def test_arbitrary_precision_bounds(self):
        self.compare('''a=[1,2,1]
print(a.index(1,-10**200,10**200),a.count(10**200))
''',modes=("bigint",))

    def test_pop_bounds_types_and_stack_loop(self):
        self.compare('''a=[1,2,3]
out=[]
while a:
    out.append(a.pop())
print(out,a)
words=["a","猫","海"]
print(words.pop(1),words.pop(),words)
pairs=[(1,"a"),(2,"b")]
print(pairs.pop(0),pairs)
values=[None,"x",None]
print(values.pop(),values)
''')
        for source in ('print([].pop())\n','print([1].pop(2))\n','print([1].pop(-2))\n'):
            self.compare(source)

    def test_pop_overflow_is_checked_before_empty_list(self):
        for source in ('print([].pop(10**100))\n','print([1].pop(-10**100))\n'):
            self.compare(source,modes=("i128","bigint"))

    def test_maybe_unbound_receiver_is_checked_before_arguments(self):
        self.compare('''if int(input()):
    a=[2,4]
print(a.pop(),a.count(2))
''',("0\n","1\n"))

    def test_invalid_binding_is_diagnosed_at_the_call(self):
        for expression in ('a.index()','a.index(1,2,3,4)','a.index(value=1)','a.count(1,2)',
                           'a.count(value=1)','a.pop(1,2)','a.pop(index=0)'):
            result=transpile('a=[1]\nprint('+expression+')\n')
            self.assertFalse(result.success)
            self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].line),("E006",2))


if __name__=="__main__":unittest.main()
