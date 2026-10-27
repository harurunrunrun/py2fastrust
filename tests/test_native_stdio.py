"""Faithful trusted stdin aliases, bytes parsing and shared text look-ahead."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native import try_generate_native
from test_streaming_io import PipeSession


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeStdioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="pytors-native-stdio-")
        cls.serial=0
        cls.environment={**os.environ,"PYTHONIOENCODING":"utf-8:strict"}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self,source,mode,release=True,string_mode="ascii"):
        result=transpile(source,TranspileOptions(integer=mode,filename="stdio.py",string_mode=string_mode))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,"native")
        self.assertLess(len(result.rust_source.encode()),512*1024)
        for forbidden in ["enum Value","enum Op","struct Runtime","fn step("]:
            self.assertNotIn(forbidden,result.rust_source)
        type(self).serial+=1
        path=Path(self.tmp.name,f"program{self.serial}.rs")
        path.write_text(result.rust_source,encoding="utf-8")
        binary=path.with_suffix("")
        build=subprocess.run(["rustc","--edition=2021",*(["-O"] if release else []),str(path),"-o",str(binary)],
                             capture_output=True,text=True,timeout=120)
        self.assertEqual(build.returncode,0,build.stderr+"\n"+source)
        return binary

    def differential(self,source,inputs=(b"",),modes=("i64","i128","bigint"),profiles=(True,),string_mode="ascii"):
        expected=[subprocess.run([sys.executable,"-c",source],input=data,capture_output=True,
                                 env=self.environment,timeout=5) for data in inputs]
        for mode in modes:
            for release in profiles:
                binary=self.compile(source,mode,release,string_mode=string_mode)
                for data,reference in zip(inputs,expected):
                    with self.subTest(mode=mode,release=release,data=data):
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,timeout=5,
                                              env={**self.environment,"PATH":"/unavailable","PYTHONPATH":"/unavailable"})
                        self.assertEqual(actual.stdout,reference.stdout)
                        self.assertEqual(actual.returncode,reference.returncode,(actual.stderr,reference.stderr))
                        if actual.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(b":")[0],
                                             reference.stderr.splitlines()[-1].split(b":")[0])

    def test_binary_readline_alias_map_and_lazy_unpack(self):
        source='''import sys
input=sys.stdin.buffer.readline
n=int(input())
A=list(map(int,input().split()))
a,b=map(int,input().split())
print(n,len(A),sum(A),a,b)
print(input())
'''
        self.differential(source,[b"3\n1 2 3\n7 8\n",b"0\n\n1 2\nx\r\n",b"1\n1\n1 2 invalid\n",
                                  b"1\n1\n1 2 3 invalid\n",b"1\n1\n1\n",b""],profiles=(False,True))

    def test_text_readline_retains_newlines_eof_and_unicode_split(self):
        source='''from sys import stdin as stream
reader=stream.readline
first=reader()
print(len(first),first,end='|')
A=list(map(int,reader().split()))
print(len(A),sum(A))
print(reader(),end='!')
'''
        self.differential(source,[b"hello\r\n1 2 3\nlast",b"\n\n", "é𝄞\n١\u20032\u00853\n".encode(),
                                  b"x\n1\x1c2\n",b""],profiles=(False,True),string_mode="unicode")

    def test_module_stream_callable_alias_chains_capture_originals(self):
        source='''import sys as module
original=module
stream=original.stdin
buffer=stream.buffer
read=other=buffer.readline
module=7
original=9
buffer=11
print(read(),other(),stream.readline(),end='|')
'''
        self.differential(source,[b"a\nb\nc\nd\n",b"",b"\xff\n\xfe\nx\n"])

    def test_ordinary_main_and_function_local_imports(self):
        source='''import sys
def main():
    input=sys.stdin.buffer.readline
    n=int(input())
    values=list(map(int,input().split()))
    total=0
    for value in values:
        total+=value*value
    print(n,len(values),total)
if __name__=='__main__':
    main()
'''
        local='''def main():
    import sys as module
    read=module.stdin.readline
    print(int(read()),int(read()))
main()
'''
        self.differential(source,[b"3\n1 -2 3\n",b"0\n\n",b""],profiles=(False,True))
        self.differential(local,[b"1\n2\n",b"1\n",b"invalid\n2\n"])

    def test_mixed_text_binary_reads_share_decoded_lookahead(self):
        programs=['''import sys
text=sys.stdin.readline
raw=sys.stdin.buffer.read
print(text(),end='|')
print(raw())
print(sys.stdin.read(),end='!')
''','''import sys
print(sys.stdin.buffer.readline())
print(sys.stdin.readline(),end='|')
print(sys.stdin.buffer.read())
print(sys.stdin.read(),end='!')
''','''import sys
print(sys.stdin.readline(0),end='|')
print(sys.stdin.buffer.read())
print(sys.stdin.read(),end='!')
''','''import sys
print(sys.stdin.read(0),end='|')
print(sys.stdin.buffer.read())
print(sys.stdin.read(),end='!')
''']
        for source in programs:
            self.differential(source,[b"a\r\nb\r\nc\r",b"1\n2\n3\n", "é𝄞\nx\n".encode(),b""])

    def test_sized_reads_characters_bytes_none_and_negative(self):
        source='''import sys
text=sys.stdin.read
line=sys.stdin.readline
raw=sys.stdin.buffer.readline
print(text(2),end='|')
print(line(1),end='|')
print(line(None),end='!')
'''
        binary='''import sys
read=sys.stdin.buffer.read
line=sys.stdin.buffer.readline
print(read(2),line(2),line(None),read(-3))
'''
        self.differential(source,["é𝄞a\nbc\n".encode(),b"abcdef\n",b""])
        self.differential(binary,[b"abcdef\ngh\nijk",b"",b"\xff\x00\n"])
        self.differential("import sys\nprint(sys.stdin.read(None),end='!')\n",[b"hello\n",b""])

    def test_binary_and_text_integer_rules_are_distinct(self):
        text="import sys\nread=sys.stdin.readline\nprint(int(read()))\n"
        binary="import sys\nread=sys.stdin.buffer.readline\nprint(int(read()))\n"
        values=[b"12\n",b"\v\f+1_234\t\r\n",b"\x1c1\n",b"\x1f1\n",b"1__2\n",b"\xff\n",b"",
                "\u200312\u0085\n".encode(),"١٢\n".encode(),b"1\x001\n"]
        self.differential(text,values)
        self.differential(binary,values)
        self.differential("import sys\nA=list(map(int,sys.stdin.buffer.read().split()))\nprint(len(A),sum(A))\n",
                          [b"1\t2\v3\f4\r5\n6 ",b"1\x1c2",b"1\xc2\xa02",b""])

    def test_binary_values_repr_index_strip_and_decode(self):
        source='''import sys
read=sys.stdin.buffer.readline
a=read()
b=a
print(a,b,len(a),bool(a))
if len(a):
    print(a[0],a[-1])
print(a.strip(),a.lstrip(),a.rstrip())
print(read().decode(),end='!')
'''
        self.differential(source,[b"\t'abc'\r\nhello\n",b'"a\x00b"\n\xff\n',b"\xff\x1c\x7f\n",b"\n\n",b""],profiles=(False,True))

    def test_stdin_alias_eof_is_not_builtin_input(self):
        self.differential("import sys\ninput=sys.stdin.readline\nprint(input(),end='|')\nprint(int(input()))\n",[b"",b"\n",b"x\n"])
        self.differential("print(int(input()))\n",[b""])

    def test_typed_function_returns_and_immutable_bytes_arguments(self):
        source='''import sys
def fetch():
    return sys.stdin.buffer.readline()
def number(value):
    return int(value)
def identity(value):
    return value
read=fetch
A=[1,2]
data=read()
print(number(data),identity(data),data,data==A,data!=A)
print(*A)
'''
        self.differential(source,[b"123\n",b"\t-7\r\n",b"invalid\n"],profiles=(False,True))

    def test_sized_count_validation_is_checked_before_read(self):
        source="import sys\nsize=int(input())\nprint(sys.stdin.buffer.read(size))\n"
        self.differential(source,[b"-1\nabc",b"-2\nabc",b"0\nabc",b"1\nabc"])
        self.differential(source,[f"{10**100}\nabc".encode(),f"{-10**100}\nabc".encode()],modes=("bigint",))
        self.differential(source,[f"{2**63}\nabc".encode(),f"{-2**63-1}\nabc".encode()],modes=("i128","bigint"))

    def test_readline_returns_before_eof_and_sized_read_waits(self):
        source="import sys\nr=sys.stdin.buffer.readline\nprint(r(),flush=True)\nprint(sys.stdin.buffer.read(2),flush=True)\n"
        commands=[[sys.executable,"-c",source]]
        commands += [[str(self.compile(source,mode))] for mode in ("i64","i128","bigint")]
        outputs=[]
        for command in commands:
            session=PipeSession(command,self.environment)
            try:
                session.send(b"a\n")
                session.expect(b"b'a\\n'\n")
                session.send(b"x")
                session.quiet()
                session.send(b"y")
                session.expect(b"b'xy'\n")
                outputs.append(session.finish())
            finally:
                session.close()
        self.assertTrue(all(output==outputs[0] for output in outputs))

    def test_trust_mutation_unknown_streams_and_unbound_local_aliases_reject(self):
        source="import sys\nread=sys.stdin.buffer.readline\nprint(int(read()))\n"
        for mode in ("i64","i128","bigint"):
            diagnostics=[]
            self.assertIsNone(try_generate_native(source,"untrusted.py",mode,diagnostic_out=diagnostics))
            self.assertEqual(diagnostics[0].code,"E006")
        programs=["import sys\nsys.stdin=7\nprint(sys.stdin.readline())\n",
                  "import sys\nread=sys.stdin.readline\nsys.stdin.readline=read\nprint(read())\n",
                  "import sys\nread=sys.stdin.readline\nread=7\nprint(read())\n",
                  "import sys\ninput=sys.stdin\nprint(input())\n",
                  "import sys\ndef main():\n print(int(input()))\n input=sys.stdin.readline\nmain()\n",
                  "def main():\n import sys\n a,b=map(int,input().split())\n input=sys.stdin.readline\nmain()\n",
                  "import sys\nread=getattr(sys.stdin,'readline')\nprint(read())\n",
                  "import sys\nprint(sys.stdin.buffer.readline(1,2))\n"]
        for source in programs:
            for mode in ("i64","i128","bigint"):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename="missing.py"))
                    self.assertFalse(result.success)
                    self.assertIsNone(result.rust_source)
                    self.assertEqual(result.diagnostics[0].code,"E006")
                    self.assertEqual(result.diagnostics[0].filename,"missing.py")


if __name__ == "__main__":
    unittest.main()
