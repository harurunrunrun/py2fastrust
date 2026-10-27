"""input() stream callbacks resume in the initiating heap frame."""
from pathlib import Path
import os
import select
import time
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
from test_streaming_io import PipeSession

WRAPPER = "import sys,gc,functools\nexec(sys.argv[1])\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ProtocolInputTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-input-protocol-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=150)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def compare(self, source, data=""):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER, source], input=data,
                                  capture_output=True, text=True, timeout=45)
        actual = subprocess.run([str(self.binary), source], input=data,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_redirected_stream_order_errors_and_result_validation(self):
        self.compare('''
            saved=(sys.stdin,sys.stdout,sys.stderr)
            results=[]
            class Stream:
                def __init__(self,name,options):self.name=name;self.options=options
                def __getattribute__(self,key):
                    if key in ['name','options']:return object.__getattribute__(self,key)
                    name=self.name;options=self.options;events.append((name,'get',key))
                    if key in options.get('missing',[]):raise AttributeError(key)
                    return object.__getattribute__(self,key)
                def fileno(self):events.append((self.name,'fileno'));raise OSError('no fd')
                def write(self,text):
                    events.append((self.name,'write',type(text).__name__,text))
                    if self.options.get('write_error'):raise ValueError('write')
                def flush(self):
                    events.append((self.name,'flush'))
                    if self.options.get('flush_error'):raise KeyboardInterrupt('flush')
                def readline(self):
                    events.append((self.name,'readline'))
                    if self.options.get('read_error'):raise ValueError('read')
                    return self.options.get('line','value\\r\\n')
            class Prompt:
                def __str__(self):events.append('prompt str');return 'prompt>'
            for name,options,prompt in [
                ('normal',{},True),('no prompt',{},False),
                ('stderr flush',{'err':{'flush_error':True}},True),
                ('stdout flush',{'out':{'flush_error':True}},True),
                ('write error',{'out':{'write_error':True}},True),
                ('read error',{'in':{'read_error':True}},True),
                ('missing flush',{'out':{'missing':['flush']},'err':{'missing':['flush']}},True),
                ('missing write',{'out':{'missing':['write']}},True),
                ('missing fileno',{'in':{'missing':['fileno']}},True),
                ('missing readline',{'in':{'missing':['readline']}},True),
                ('empty str',{'in':{'line':''}},False),('empty bytes',{'in':{'line':b''}},False),
                ('bytes',{'in':{'line':b'value\\r\\n'}},False),
                ('wrong type',{'in':{'line':42}},False),('bare CR',{'in':{'line':'value\\r'}},False),
                ('None prompt',{},None),
            ]:
                events=[]
                sys.stdin=Stream('in',options.get('in',{}))
                sys.stdout=Stream('out',options.get('out',{}))
                sys.stderr=Stream('err',options.get('err',{}))
                try:
                    value=input(Prompt()) if prompt is True else (input(None) if prompt is None else input())
                    outcome=(type(value).__name__,repr(value))
                except BaseException as error:outcome=(type(error).__name__,str(error))
                finally:sys.stdin,sys.stdout,sys.stderr=saved
                results.append((name,outcome,events))
            for value in results:print(value)
        ''')

    def test_arguments_and_lost_streams_precede_callbacks(self):
        self.compare('''
            saved=(sys.stdin,sys.stdout,sys.stderr)
            class Prompt:
                def __str__(self):events.append('str');return 'prompt'
            class Stream:
                def __getattribute__(self,name):events.append(name);raise AssertionError('callback')
            for operation in ['many','keyword','stdin','stdout','stderr','stdin none','stdout none','stderr none']:
                events=[];sys.stdin=Stream();sys.stdout=Stream();sys.stderr=Stream()
                try:
                    if operation=='many':input(1,2)
                    elif operation=='keyword':input(prompt='value')
                    else:
                        name=operation.split()[0]
                        if operation.endswith('none'):setattr(sys,name,None)
                        else:delattr(sys,name)
                        input(Prompt())
                except BaseException as error:result=(type(error).__name__,str(error))
                finally:sys.stdin,sys.stdout,sys.stderr=saved
                print(operation,result,events)
        ''')

    def test_captured_streams_prompt_identity_and_live_method_lookups(self):
        self.compare('''
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Text(str):pass
            returned=Text('prompt')
            class Prompt:
                def __str__(self):events.append('str');sys.stdout=second;gc.collect();return returned
            class Reader:
                def readline(self):events.append('readline');return 'result\\n'
            first_reader=Reader()
            class Writer:
                def __init__(self,name):self.name=name
                def write(self,text):events.append((self.name,'write',text is returned));sys.stdin=None
                def flush(self):events.append((self.name,'flush'))
            first=Writer('first');second=Writer('second')
            class Error:
                def flush(self):events.append('error flush');sys.stdin=None;sys.stdout=second;sys.stderr=None;gc.collect()
            try:
                sys.stdin=first_reader;sys.stdout=first;sys.stderr=Error()
                value=input(Prompt())
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(value,events)
            class Missing:
                def __getattr__(self,name):
                    events.append(('fallback',name))
                    if name=='readline':return lambda:'fallback\\n'
                    if name in ['write','flush']:return lambda *args:events.append((name,args))
                    raise AttributeError(name)
            events.clear()
            try:
                sys.stdin=Missing();sys.stdout=Missing();sys.stderr=Missing()
                value=input('hello')
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(value,events)
        ''')

    def test_readline_subclasses_keep_identity_without_lf(self):
        self.compare('''
            original=sys.stdin
            class Text(str):
                def __len__(self):raise AssertionError('length override')
                def __getitem__(self,key):raise AssertionError('getitem override')
            class Bytes(bytes):
                def __len__(self):raise AssertionError('length override')
                def __getitem__(self,key):raise AssertionError('getitem override')
            class Reader:
                def readline(self):return line
            try:
                sys.stdin=Reader()
                for line in [Text('same'),Text('line\\n'),Bytes(b'same'),Bytes(b'line\\n')]:
                    result=input();print(type(result).__name__,repr(result),result is line)
            finally:sys.stdin=original
        ''')

    def test_prompt_failures_and_suppressed_callback_cleanup(self):
        self.compare('''
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Reader:
                def readline(self):events.append('read');return 'ok\\n'
            class Prompt:
                def __str__(self):
                    events.append('str')
                    if mode=='bad return':return 7
                    if mode=='str error':raise LookupError('prompt')
                    return 'prompt'
            class Writer:
                def __getattribute__(self,name):
                    if name=='write' and mode=='write lookup':events.append('write lookup');raise LookupError('write')
                    return object.__getattribute__(self,name)
                def write(self,text):events.append(('write',text))
                def flush(self):events.append('flush')
            for mode in ['bad return','str error','write lookup']:
                events.clear()
                try:
                    sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Writer()
                    try:input(Prompt())
                    except BaseException as error:outcome=(type(error).__name__,str(error))
                finally:sys.stdin,sys.stdout,sys.stderr=saved
                print(mode,outcome,events)
            class Bad:
                def __repr__(self):raise LookupError('repr error')
            bad=Bad()
            class ErrorFlush:
                def flush(self):repr(bad)
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=ErrorFlush()
                value=input()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            gc.collect()
            try:repr(bad)
            except LookupError:print('repr cleanup',value)
        ''')

    def test_fileno_result_index_conversion_and_errors(self):
        self.compare('''
            original=sys.stdin;events=[]
            class Index:
                def __index__(self):events.append('index');return 9
            class BadIndex:
                def __index__(self):events.append('bad index');return 'wrong'
            class ErrorIndex:
                def __index__(self):events.append('error index');raise LookupError('index failed')
            class Reader:
                def fileno(self):events.append('fileno');return descriptor
                def readline(self):events.append('readline');return 'ok\\n'
            try:
                sys.stdin=Reader()
                for descriptor in [0,-1,True,9,1.0,'0',None,Index(),BadIndex(),ErrorIndex()]:
                    events.clear()
                    try:result=input();outcome=('ok',result)
                    except BaseException as error:outcome=(type(error).__name__,str(error))
                    print(outcome,events)
            finally:sys.stdin=original
        ''')

    def test_recursive_prompt_readline_lookup_and_flush_heap_frames(self):
        self.compare('''
            saved=(sys.stdin,sys.stdout,sys.stderr)
            class Sink:
                def write(self,text):pass
                def flush(self):pass
            sink=Sink()
            class Prompt:
                def __str__(self):input(self);return 'unreachable'
            class Reader:
                def readline(self):return input()
            class Lookup:
                def __getattribute__(self,name):
                    if name=='readline':return input()
                    return object.__getattribute__(self,name)
            class Flush:
                def flush(self):input()
                def readline(self):return 'done\\n'
                def write(self,text):pass
            class Finite:
                def __init__(self):self.depth=0
                def readline(self):
                    self.depth+=1
                    if self.depth==300:gc.collect();return 'done\\n'
                    return input()
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,reader,prompt in [('readline',Reader(),None),('lookup',Lookup(),None),('prompt',Reader(),Prompt())]:
                    result='unexpected return'
                    try:
                        sys.stdin=reader;sys.stdout=sink;sys.stderr=sink
                        if prompt is None:input()
                        else:input(prompt)
                    except RecursionError:result='caught'
                    finally:sys.stdin,sys.stdout,sys.stderr=saved
                    print(limit,label,result)
            sys.setrecursionlimit(3000)
            try:
                sys.stdin=Finite();sys.stdout=sink;sys.stderr=sink
                result=input()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print('finite',result)
            try:
                stream=Flush();sys.stdin=stream;sys.stdout=stream;sys.stderr=sink
                result=input()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print('ignored recursive flush',result)
        ''')

    def test_aot_call_aliases_partial_and_gc_roots(self):
        source = textwrap.dedent('''
            import sys,gc,functools
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Stream:
                def write(self,text):events.append(('write',text));gc.collect()
                def flush(self):gc.collect()
                def readline(self):gc.collect();return 'value\\n'
            class Prompt:
                def __str__(self):gc.collect();return 'prompt>'
            stream=Stream()
            try:
                sys.stdin=stream;sys.stdout=stream;sys.stderr=stream
                read=input
                first=read(Prompt())
                second=functools.partial(input,Prompt())()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(first,second,events)
        ''')
        result=transpile(source,TranspileOptions(optimize=False))
        self.assertTrue(result.success,result.diagnostics)
        rust=Path(self.directory.name)/'aot.rs';rust.write_text(result.rust_source,encoding='utf-8')
        binary=rust.with_suffix('')
        compiled=subprocess.run(['rustc','--edition=2021',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=150)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=15)
        actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
        self.assertEqual(expected.returncode,0,expected.stderr)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout)

    def test_native_callback_error_boundaries_remain_inside_input(self):
        self.compare('''
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Reader:
                def readline(self):events.append('readline');return 'ok\\n'
            class Writer:
                def write(self,text):events.append(('write',text))
                def flush(self):events.append('stdout flush')
            class Error:
                pass
            marker=object()
            class Source:
                def __iter__(self):return iter([1])
                __len__=staticmethod(input)
                def __length_hint__(self):events.append('length hint');return 1
            class Item:
                __repr__=staticmethod(input)
            operations=[
                ('iterator',lambda:next(map(input,['prompt']),marker),functools.partial(next,iter([]))),
                ('length',lambda:list(Source()),functools.partial(len,42)),
                ('representation',lambda:repr(Item()),functools.partial(getattr,42,'missing')),
            ]
            for name,operation,flush in operations:
                Error.flush=staticmethod(flush);events.clear()
                try:
                    sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                    value=operation()
                finally:sys.stdin,sys.stdout,sys.stderr=saved
                print(name,value is marker,value if value is not marker else None,events)
            class Missing:
                def __getattr__(self,name):events.append(('fallback',name));return 7
            Error.flush=staticmethod(functools.partial(getattr,Missing(),'value'))
            events.clear()
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                value=input()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(value,events)
        ''')

    def test_native_prompt_and_line_before_pipe_eof(self):
        source="first=input('prompt>');print(repr(first),flush=True)\ntry:input('end>')\nexcept EOFError:print('eof',flush=True)\n"
        environment={**os.environ,"PYTHONIOENCODING":"utf-8:strict","PATH":""}
        outputs=[]
        for command in [[sys.executable,"-I","-c",source],[str(self.binary),source]]:
            session=PipeSession(command,environment)
            try:
                session.expect(b'prompt>');session.send('é\r\n'.encode())
                session.expect("'é\\r'\nend>".encode());session.close_input();session.expect(b'eof\n')
                outputs.append(session.finish())
            finally:session.close()
        self.assertEqual(outputs[0],outputs[1])

    @unittest.skipUnless(os.name == "posix", "terminal test requires POSIX pty")
    def test_terminal_stream_probes_and_native_read_path(self):
        import pty
        import termios
        source = textwrap.dedent(r'''
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Reader:
                def fileno(self):events.append('input fd');return 0
                @property
                def encoding(self):events.append('input encoding');return 'utf-8'
                @property
                def errors(self):events.append('input errors');return 'strict'
                def readline(self):raise AssertionError('replacement readline')
            class Writer:
                def fileno(self):events.append('output fd');return 1
                @property
                def encoding(self):events.append('output encoding');return 'utf-8'
                @property
                def errors(self):events.append('output errors');return 'strict'
                def write(self,text):raise AssertionError('replacement write')
                def flush(self):events.append('output flush')
            class Error:
                def flush(self):events.append('error flush')
            class Prompt:
                def __str__(self):events.append('prompt str');gc.collect();return 'terminal>'
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                result=input(Prompt())
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(repr(result),events,flush=True)
        ''')
        results=[]
        for command in [[sys.executable,"-I","-c",WRAPPER,source],[str(self.binary),source]]:
            master,slave=pty.openpty()
            attrs=termios.tcgetattr(slave);attrs[3] &= ~termios.ECHO;attrs[1] &= ~termios.ONLCR
            termios.tcsetattr(slave,termios.TCSANOW,attrs)
            process=subprocess.Popen(command,stdin=slave,stdout=slave,stderr=subprocess.PIPE)
            os.close(slave);out=b'';error=b''
            try:
                deadline=time.monotonic()+8
                while b'terminal>' not in error:
                    remaining=deadline-time.monotonic()
                    self.assertGreater(remaining,0,'terminal prompt was not flushed')
                    ready,_,_=select.select([master,process.stderr],[],[],remaining)
                    self.assertTrue(ready,'terminal prompt was not visible')
                    for stream in ready:
                        chunk=os.read(stream if isinstance(stream,int) else stream.fileno(),65536)
                        self.assertTrue(chunk,('early terminal EOF',out,error))
                        if isinstance(stream,int):out+=chunk
                        else:error+=chunk
                os.write(master,'é\n'.encode())
                process.wait(timeout=10)
                while True:
                    try:chunk=os.read(master,65536)
                    except OSError:break
                    if not chunk:break
                    out+=chunk
                error+=process.stderr.read()
                self.assertEqual(process.returncode,0,error)
                results.append((out,error))
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=5)
                process.stderr.close();os.close(master)
        self.assertEqual(results[0],results[1])

    @unittest.skipUnless(os.name == "posix", "terminal test requires POSIX pty")
    def test_terminal_metadata_fallbacks_and_prompt_errors(self):
        import pty
        import termios
        program=textwrap.dedent(r'''
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Reader:
                def fileno(self):events.append('input fd');return 0
                @property
                def encoding(self):
                    events.append('input encoding')
                    if case=='input missing':raise LookupError('encoding')
                    return None if case=='input bad type' else 'utf-8'
                @property
                def errors(self):events.append('input errors');return 'strict'
                def readline(self):events.append('readline');return 'fallback\n'
            class Writer:
                def fileno(self):events.append('output fd');return 1.5 if case=='output bad fd' else 1
                @property
                def encoding(self):
                    events.append('output encoding')
                    if case=='output missing':raise LookupError('encoding')
                    return None if case=='output bad type' else 'utf-8'
                @property
                def errors(self):events.append('output errors');return 'strict'
                def write(self,text):events.append(('write',text))
                def flush(self):events.append('output flush');raise ValueError('ignored')
            class Error:
                def flush(self):events.append('error flush')
            class Prompt:
                def __str__(self):events.append('prompt str');return 'null\0prompt' if case=='null prompt' else 'prompt>'
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                try:result=('ok',input(Prompt()))
                except BaseException as error:result=(type(error).__name__,str(error))
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(result,events,flush=True)
        ''')
        for case in ['input missing','input bad type','output missing','output bad type','output bad fd','null prompt']:
            source='case='+repr(case)+'\n'+program
            outputs=[]
            for command in [[sys.executable,'-I','-c',WRAPPER,source],[str(self.binary),source]]:
                master,slave=pty.openpty()
                attrs=termios.tcgetattr(slave);attrs[3]&=~termios.ECHO;attrs[1]&=~termios.ONLCR
                termios.tcsetattr(slave,termios.TCSANOW,attrs)
                process=subprocess.Popen(command,stdin=slave,stdout=slave,stderr=subprocess.PIPE)
                os.close(slave)
                try:
                    process.wait(timeout=10);out=b''
                    while True:
                        try:chunk=os.read(master,65536)
                        except OSError:break
                        if not chunk:break
                        out+=chunk
                    error=process.stderr.read()
                    self.assertEqual(process.returncode,0,error)
                    outputs.append((out,error))
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
                    process.stderr.close();os.close(master)
            self.assertEqual(outputs[0],outputs[1],case)
