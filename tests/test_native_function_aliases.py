"""Definition identities and call-time global proofs for static aliases."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeFunctionAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-native-alias-")
        cls.serial = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def differential(self, source, inputs=("",), modes=("i64", "i128", "bigint"), profiles=(False, True), trace=False):
        expected = [subprocess.run([sys.executable, "-I", "-c", source],input=data,
                                   capture_output=True,text=True,timeout=5) for data in inputs]
        for mode in modes:
            result = transpile(source,TranspileOptions(integer=mode,filename="aliases.py"))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            self.assertLess(len(result.rust_source.encode()),512*1024)
            for forbidden in ["enum Value","enum Op","struct Runtime","fn step("]:
                self.assertNotIn(forbidden,result.rust_source)
            for optimized in profiles:
                type(self).serial += 1
                path = Path(self.tmp.name,f"program{self.serial}.rs")
                path.write_text(result.rust_source,encoding="utf-8")
                binary = path.with_suffix("")
                build = subprocess.run(["rustc","--edition=2021",*(["-O"] if optimized else []),
                                        str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                self.assertEqual(build.returncode,0,build.stderr+"\n"+source)
                for data, reference in zip(inputs,expected):
                    with self.subTest(mode=mode,optimized=optimized,data=data):
                        actual = subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5,
                                                env={"PATH":"/python-unavailable","PYTHONPATH":"/unavailable"})
                        self.assertEqual(actual.stdout,reference.stdout)
                        self.assertEqual(actual.returncode,reference.returncode,actual.stderr)
                        if actual.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                             reference.stderr.splitlines()[-1].split(":")[0])
                            if trace:
                                self.assertEqual(re.findall(r"line (\d+), in ([^\n]+)",actual.stderr),
                                                 re.findall(r"line (\d+), in ([^\n]+)",reference.stderr))

    def test_chained_aliases_defaults_binding_and_scalar_type_variants(self):
        source = '''def identity(x):
    return x
def mix(a,/,b=3,*,c=7):
    return a+b*10+c*100
g=h=identity
other=g
encode=mix
print(g(13),h(True),other(False),identity(-7))
print(encode(1,c=2,b=3),encode(4),mix(5,b=6))
'''
        self.differential(source)

    def test_original_object_survives_rebind_and_redefinition(self):
        source = '''def f(x=3):
    return x+10
old=f
f=99
print(old(),old(7),f)
def f(x=4):
    return x+20
new=f
print(old(),new(),f(8))
f=old
new_alias=f
print(f(1),new_alias(2),new(3))
'''
        self.differential(source)

    def test_call_time_global_alias_helpers_and_specialization_context(self):
        source = '''def left(x):
    return x+11
def right(x):
    return x+29
helper=left
def caller(x):
    local=helper
    return local(x)+helper(x)
saved=caller
print(saved(3))
helper=right
print(saved(3))
left=99
print(saved(3))
helper=caller
print(right(7))
'''
        self.differential(source)

    def test_local_alias_chains_branch_joins_and_loop_calls(self):
        source = '''def step(x):
    return x+5
def run(n):
    a=step
    b=a
    if n:
        chosen=a
    else:
        chosen=b
    total=0
    for i in range(n):
        total+=chosen(i)
    return total+chosen(0)
g=run
print(g(int(input())))
'''
        self.differential(source,["0\n","1\n","7\n"])

    def test_alias_argument_order_and_exception_trace_keeps_definition_name(self):
        source = '''def mark(x):
    print(x)
    return x
def divide(a,/,b=3,*,c=4):
    print(17)
    return (a+c)//b
g=divide
divide=7
print(g(mark(1),c=mark(2),b=mark(int(input()))))
'''
        self.differential(source,["3\n","0\n","invalid\n"],trace=True)

    def test_readonly_list_parameters_and_immediate_callback_alias(self):
        source = '''def total(values,offset=7):
    answer=offset
    for value in values:
        answer+=value*value
    return answer+sum(values)
def increment(x):
    return x+1
g=total
h=g
callback=increment
A=list(map(int,input().split()))
print(h(A),total(A,0),g([1,2],3))
print(sum(map(callback,A)))
print(*A)
'''
        self.differential(source,["\n","1 -2 3\n","1000000000 -1000000000\n"])

    def test_extended_scalar_alias_specializations(self):
        source = '''def identity(x):
    return x
g=identity
print(g('hello'),g(1.25),g(True),g(7))
'''
        self.differential(source,modes=("i64","i128"))

    def test_unknown_callbacks_globals_recursion_and_unstable_loop_targets_reject(self):
        sources = ["def f(x):return x\ndef apply(callback):return callback(1)\nprint(apply(f))\n",
                   "def f(x):return x\ng=f\ng=int(input())\nprint(g(1))\n",
                   "def f(x):return x\ndef h(x):return g(x)\nprint(h(1))\ng=f\n",
                   "def f(x):return x\ng=f\ndef h(x):return g(x)\ng=7\nprint(h(1))\n",
                   "offset=7\ndef f(x):return x+offset\ng=f\nprint(g(1))\n",
                   "def f(x):\n global g\n g=x\n return x\na=f\nprint(a(1))\n",
                   "def f(x):return f(x-1) if x else 1\ng=f\nprint(g(3))\n",
                   "def f(x):return g(x)\ng=f\nprint(g(3))\n",
                   "def f(x):return x\ndef h(x):return x+1\ng=f\nfor i in range(3):\n print(g(i))\n g=h\n",
                   "def f(x):return x\nfor i in range(3):\n print(f(i))\n f=7\n",
                   "def f(x):return x\nif int(input()):\n g=f\nprint(g(1))\n"]
        for source in sources:
            for mode in ("i64","i128","bigint"):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename="unproved.py"))
                    self.assertFalse(result.success)
                    self.assertIsNone(result.rust_source)
                    self.assertEqual(result.diagnostics[0].code,"E006")


if __name__ == "__main__":
    unittest.main()
