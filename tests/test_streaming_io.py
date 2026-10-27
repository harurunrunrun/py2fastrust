"""Paired CPython/Rust pipe protocols keep stdin open until explicitly closed."""

from pathlib import Path
import os
import random
import selectors
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from py2fastrust import TranspileOptions, transpile


class PipeSession:
    def __init__(self, command, environment):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, bufsize=0, env=environment)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.pending = b""
        self.observed = b""

    def expect(self, expected, timeout=5):
        deadline = time.monotonic() + timeout
        while len(self.pending) < len(expected):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise AssertionError(f"timed out before stdin EOF: wanted {expected!r}, got {self.pending!r}")
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise AssertionError(f"child closed stdout: wanted {expected!r}, got {self.pending!r}")
            self.pending += data
            self.observed += data
        if not self.pending.startswith(expected):
            raise AssertionError((expected, self.pending))
        self.pending = self.pending[len(expected):]

    def quiet(self):
        if self.pending:
            raise AssertionError(f"unexpected early output {self.pending!r}")
        if self.selector.select(0.1):
            data = os.read(self.process.stdout.fileno(), 65536)
            if data:
                raise AssertionError(f"sized read returned too early: {data!r}")
            raise AssertionError("child closed stdout before remaining input")

    def send(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def close_input(self):
        if self.process.stdin is not None:
            self.process.stdin.close()
            self.process.stdin = None

    def finish(self):
        self.close_input()
        out, error = self.process.communicate(timeout=10)
        self.observed += out
        if self.process.returncode:
            raise AssertionError((self.process.returncode, error))
        return self.observed, error

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate(timeout=5)
        self.selector.close()
        self.process.stdout.close()
        self.process.stderr.close()


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StreamingIOTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-streaming-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.binaries = {}
        for integer in ["i64", "i128", "bigint"]:
            result = transpile("import sys\nexec(sys.argv[1])\n",
                               TranspileOptions(optimize=False, integer=integer))
            if not result.success:
                raise AssertionError(result.diagnostics)
            rust = cls.root / f"{integer}.rs"
            rust.write_text(result.rust_source)
            binary = cls.root / integer
            built = subprocess.run(["rustc", "--edition=2021", str(rust), "-o", str(binary)],
                                   capture_output=True, text=True, timeout=120)
            if built.returncode:
                raise AssertionError(built.stderr)
            cls.binaries[integer] = binary
        cls.environment = {**os.environ, "PYTHONIOENCODING": "utf-8:strict", "PATH": ""}

    def protocol(self, source, action):
        source = textwrap.dedent(source)
        results = []
        commands = [[sys.executable, "-c", source]]
        commands += [[str(binary), source] for binary in self.binaries.values()]
        for command in commands:
            session = PipeSession(command, self.environment)
            try:
                action(session)
                results.append(session.finish())
            finally:
                session.close()
        self.assertTrue(all(result == results[0] for result in results[1:]), results)

    def batch(self, source, data):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-c", source], input=data,
                                  capture_output=True, env=self.environment, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        for integer, binary in self.binaries.items():
            with self.subTest(integer=integer):
                actual = subprocess.run([str(binary), source], input=data,
                                        capture_output=True, env=self.environment, timeout=20)
                self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_prompt_flush_blank_lines_and_caught_eof_without_initial_eof(self):
        source = '''
            print('boot',flush=True)
            first=input('A?>')
            print('got',repr(first),sep=':',end='|',flush=True)
            second=input('B?>')
            print('got',repr(second),sep=':',end='|',flush=True)
            try:input('EOF?>')
            except EOFError:print('end',flush=True)
        '''
        def action(session):
            session.expect(b"boot\nA?>")
            session.send("é\r\n".encode())
            session.expect("got:'é\\r'|B?>".encode())
            session.send(b"\n")
            session.expect(b"got:''|EOF?>")
            session.close_input()
            session.expect(b"end\n")
        self.protocol(source, action)

    def test_binary_flush_exact_sized_read_and_line_boundaries(self):
        source = '''
            import sys
            sys.stdout.buffer.write(b'raw>')
            sys.stdout.buffer.flush()
            print(repr(sys.stdin.buffer.read(4)),flush=True)
            print(repr(sys.stdin.buffer.readline()),flush=True)
        '''
        def action(session):
            session.expect(b"raw>")
            session.send(b"ab")
            session.quiet()
            session.send(b"cd")
            session.expect(b"b'abcd'\n")
            session.send(b"raw\xff\n")
            session.expect(b"b'raw\\xff\\n'\n")
        self.protocol(source, action)

    def test_fragmented_unicode_sized_text_and_determinate_mixed_reads(self):
        source = '''
            import sys
            print('ready',flush=True)
            print(repr(sys.stdin.read(2)),flush=True)
            print(repr(sys.stdin.readline(2)),flush=True)
            print(repr(sys.stdin.buffer.read(1)),flush=True)
            print(repr(sys.stdin.readline()),flush=True)
        '''
        def action(session):
            session.expect(b"ready\n")
            session.send(b"\xc3")
            session.quiet()
            session.send(b"\xa9Z")
            session.expect("'éZ'\n".encode())
            session.send(b"\r\n")
            session.expect(b"'\\r\\n'\n")
            session.send(b"\xff")
            session.expect(b"b'\\xff'\n")
            session.send("日本\n".encode())
            session.expect("'日本\\n'\n".encode())
        self.protocol(source, action)

    def test_zero_size_reads_return_before_any_input_and_hints_do_not_need_eof(self):
        source = '''
            import sys
            print(repr(sys.stdin.read(0)),repr(sys.stdin.buffer.read(0)),flush=True)
            print(sys.stdin.readlines(1),flush=True)
            print(sys.stdin.buffer.readlines(1),flush=True)
        '''
        def action(session):
            session.expect(b"'' b''\n")
            session.send(b"first\n")
            session.expect(b"['first\\n']\n")
            session.send(b"raw\n")
            session.expect(b"[b'raw\\n']\n")
        self.protocol(source, action)

    def test_decoding_errors_are_catchable_and_stream_does_not_restart(self):
        source = '''
            import sys
            print('ready',flush=True)
            try:sys.stdin.readline()
            except UnicodeDecodeError as error:
                print(error.encoding,error.start,error.end,error.reason,repr(error.object),flush=True)
            print(repr(sys.stdin.read()),flush=True)
        '''
        def action(session):
            session.expect(b"ready\n")
            session.send(b"a\xff\n")
            session.expect(b"utf-8 1 2 invalid start byte b'a\\xff\\n'\n")
            session.close_input()
            session.expect(b"''\n")
        self.protocol(source, action)

    def test_text_decoder_read_ahead_and_binary_reader_share_raw_stream(self):
        self.batch('''
            import sys
            print(repr(sys.stdin.read(1)))
            print(repr(sys.stdin.buffer.read(1)))
            print(repr(sys.stdin.readline()))
            print(repr(sys.stdin.buffer.readline()))
            print(repr(sys.stdin.read()))
        ''', b"abc\nDEF\n")
        self.batch('''
            import sys
            print(repr(sys.stdin.buffer.read(1)))
            print(repr(sys.stdin.read(1)))
            print(repr(sys.stdin.buffer.read()))
            print(repr(sys.stdin.read()))
        ''', b"abc\r\nDEF\n")

    def test_utf8_chunk_boundaries_cr_and_final_line(self):
        source = '''
            import sys
            for size in [0,8191,1,2,8193,7]:
                value=sys.stdin.read(size)
                print(len(value),repr(value[:3]),repr(value[-3:]))
            print(repr(sys.stdin.read()))
        '''
        self.batch(source, ("a"*8191+"é"+"日本"*4098+"\r\n\nlast").encode())
        self.batch('''
            import sys
            for line in sys.stdin:print(repr(line))
            for action in [input,lambda:sys.stdin.readline(),lambda:sys.stdin.buffer.read(2)]:
                try:print(repr(action()))
                except EOFError:print('EOF')
        ''', b"first\r\nsecond\rlast")

    def test_size_validation_none_and_keyword_names(self):
        self.batch('''
            import sys
            for operation in [lambda:sys.stdin.read(0,1),lambda:sys.stdin.readline(None),
                              lambda:sys.stdin.read(1.5),lambda:sys.stdin.buffer.read(1.5),
                              lambda:sys.stdin.flush(1),lambda:sys.stdout.write('x','y'),
                              lambda:input(1,2),lambda:input(prompt='x'),
                              lambda:sys.stdin.read(size=1),lambda:sys.stdin.readline(size=1),
                              lambda:sys.stdin.readlines(hint=1),lambda:sys.stdin.buffer.read(size=1)]:
                try:operation()
                except Exception as error:print(type(error).__name__)
            print(repr(sys.stdin.read(1)),repr(sys.stdin.readline(2)))
            print(repr(sys.stdin.read(None)),sys.stdin.readlines(None))
        ''', b"abcd\n")

    def test_print_conversion_write_flush_order_and_partial_errors(self):
        self.batch('''
            events=[]
            class Value:
                def __init__(self,name):self.name=name
                def __str__(self):events.append(('str',self.name));return self.name
            class Separator(str):
                def __str__(self):events.append(('separator',str.__str__(self)));return '!'
            class Flag:
                def __bool__(self):events.append('bool');return True
            class File:
                def __getattribute__(self,name):
                    if name in ['write','flush']:events.append(('get',name))
                    return object.__getattribute__(self,name)
                def write(self,text):events.append(('write',text,type(text).__name__))
                def flush(self):events.append('flush')
            print(Value('a'),Value('b'),sep=Separator('s'),end=Separator('e'),file=File(),flush=Flag())
            print(events)
            events.clear()
            try:print(Value('x'),sep=1,flush=Flag())
            except Exception as error:print(type(error).__name__,events)
            class Bad:
                def __str__(self):raise ValueError('bad')
            try:print('prefix',Bad(),end='!')
            except ValueError:print('caught')
        ''', b"")

    def test_native_flush_and_input_work_before_eof(self):
        source = '''print(17,end="",flush=True)
x=int(input())
print(x+1,end=":",flush=True)
y=int(input())
print(y+2,flush=True)
'''
        for integer in ["i64", "i128", "bigint"]:
            result = transpile(source, TranspileOptions(integer=integer))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "vm" if integer == "bigint" else "native")
            rust = self.root / f"native-{integer}.rs"
            rust.write_text(result.rust_source)
            binary = self.root / f"native-{integer}"
            built = subprocess.run(["rustc", "--edition=2021", str(rust), "-o", str(binary)],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stderr)
            for command in [[sys.executable, "-c", source], [str(binary)]]:
                session = PipeSession(command, self.environment)
                try:
                    session.expect(b"17")
                    session.send(b"10\n")
                    session.expect(b"11:")
                    session.send(b"20\n")
                    session.expect(b"22\n")
                    self.assertEqual(session.process.wait(timeout=5), 0)
                    session.finish()
                finally:
                    session.close()

    def test_native_helper_functions_flush_pending_output_before_input(self):
        source = '''def ask(prompt):
 print(prompt,end=">")
 return int(input())
first=ask(7)
print(first,flush=True)
second=ask(8)
print(second,flush=True)
'''
        for integer in ["i64", "i128"]:
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            rust=self.root/f"helper-{integer}.rs"
            rust.write_text(result.rust_source)
            binary=self.root/f"helper-{integer}"
            built=subprocess.run(["rustc","--edition=2021",str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            for command in [[sys.executable,"-c",source],[str(binary)]]:
                session=PipeSession(command,self.environment)
                try:
                    session.expect(b"7>")
                    session.send(b"10\n")
                    session.expect(b"10\n8>")
                    session.send(b"20\n")
                    session.expect(b"20\n")
                    self.assertEqual(session.process.wait(timeout=5),0)
                    session.finish()
                finally:session.close()

    def test_text_zero_size_readline_keeps_its_observable_decoded_lookahead(self):
        source='''
            import sys
            print('ready',flush=True)
            print(repr(sys.stdin.readline(0)),flush=True)
            print(repr(sys.stdin.read(1)),flush=True)
            print(repr(sys.stdin.buffer.read(1)),flush=True)
        '''
        def action(session):
            session.expect(b"ready\n")
            session.quiet()
            session.send(b"a")
            session.expect(b"''\n'a'\n")
            session.send(b"b")
            session.expect(b"b'b'\n")
        self.protocol(source,action)
        self.batch('''
            import sys
            print(repr(sys.stdin.buffer.readline(0)))
            print(repr(sys.stdin.readline(0)))
            print(repr(sys.stdin.buffer.readline(2)))
            print(repr(sys.stdin.read(2)))
            print(repr(sys.stdin.read()))
        ''',"日a日b\n".encode())

    def test_mixed_read_sequence_corpus_matches_after_decoding_errors(self):
        randomizer=random.Random(31415)
        for case in range(80):
            data=''.join(randomizer.choice(['a','b','\n','\r','é','日']) for _ in range(70)).encode()
            operations=[]
            for _ in range(12):
                reader=randomizer.choice(['sys.stdin','sys.stdin.buffer'])
                method=randomizer.choice(['read','readline'])
                size=randomizer.choice([0,1,2,3,8,-1])
                operations.append(f"try:print(repr({reader}.{method}({size})))\nexcept Exception as error:print(type(error).__name__)\n")
            with self.subTest(case=case):self.batch('import sys\n'+''.join(operations),data)
