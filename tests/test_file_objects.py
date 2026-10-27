"""CPython 3.14 oracle for native file layers, ownership and text decoding."""
from pathlib import Path
import os
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions,transpile


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FileObjectTests(unittest.TestCase):
    maxDiff=None

    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-file-objects-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root=Path(cls.directory.name)
        cls.binaries=[]
        profiles=os.environ.get('PYTORS_FILE_TEST_PROFILES','i64-debug,i64-release,i128-debug,i128-release,bigint-debug,bigint-release').split(',')
        for profile in profiles:
            integer,build=profile.split('-')
            result=transpile('import sys\nexec(sys.argv[1])\n',TranspileOptions(integer=integer,optimize=False))
            if not result.success:raise AssertionError(result.diagnostics)
            source=cls.root/(profile+'.rs');source.write_text(result.rust_source)
            binary=source.with_suffix('')
            completed=subprocess.run(['rustc','--edition=2021',*(['-O']if build=='release' else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=180)
            if completed.returncode:raise AssertionError(completed.stderr)
            cls.binaries.append((profile,binary))
        cls.environment={**os.environ,'PATH':'','PYTHONIOENCODING':'utf-8:strict','PYTHONUTF8':'1'}

    def compare(self,source,files=None):
        source=textwrap.dedent(source)
        outcomes=[]
        commands=[('CPython',[sys.executable,'-I','-c',source])]
        commands.extend((profile,[str(binary),source])for profile,binary in self.binaries)
        for profile,command in commands:
            with self.subTest(profile=profile),tempfile.TemporaryDirectory(prefix='pytors-file-run-')as directory:
                directory=Path(directory)
                for name,data in (files or {}).items():(directory/name).write_bytes(data)
                result=subprocess.run(command,cwd=directory,capture_output=True,env=self.environment,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                effects={path.name:path.read_bytes()for path in directory.iterdir()if path.is_file()}
                outcomes.append((result.stdout,effects))
        for outcome in outcomes[1:]:self.assertEqual(outcome,outcomes[0])

    def test_binary_read_write_alias_iteration_and_context(self):
        self.compare('''
            import io
            with open('data','w+b',buffering=4) as f:
                alias=f
                print(type(f).__name__,isinstance(f,io.BufferedIOBase),f.raw is f.raw)
                print(f.closed,f.readable(),f.writable(),f.seekable(),f.isatty())
                print(f.write(b'ab\\ncd\\nlast'),f.tell())
                print(f.seek(0),f.read(1),f.tell())
                f.flush()
                print(f.raw.tell(),f.tell())
                print(f.readline(),f.readlines(2))
                print(list(f),iter(f) is f)
                f.seek(0);print(f.read1(2),f.peek(1),f.read())
                f.seek(2);print(f.truncate(5));f.seek(0);print(f.read())
            print(alias.closed,alias.raw.closed)
            alias.close()
            for action in [lambda:alias.read(0),lambda:alias.write(b''),lambda:alias.tell(),lambda:iter(alias)]:
                try:action()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_text_unicode_newlines_seek_and_buffer_identity(self):
        self.compare('''
            import io
            for newline in [None,'','\\n','\\r','\\r\\n']:
                f=open('text','r',encoding='utf-8',newline=newline)
                print(type(f).__name__,isinstance(f,io.TextIOBase),f.buffer is f.buffer,f.buffer.raw is f.buffer.raw)
                print(f.encoding,f.errors,f.line_buffering,f.write_through,repr(f.newlines))
                print(repr(f.read(1)),repr(f.newlines))
                position=f.tell();print(repr(f.read(3)))
                f.seek(position);print(repr(f.read(3)))
                f.seek(0);print([repr(line) for line in f])
                f.seek(0);print(repr(f.readline(2)),repr(f.read()))
                f.close()
        ''',{'text':'é\r\n日本\rlast\nend'.encode()})

    def test_text_write_translation_print_and_visible_buffer_flush(self):
        self.compare('''
            for newline in [None,'','\\n','\\r','\\r\\n']:
                f=open('text','w+',encoding='utf-8',newline=newline)
                print(f.write('é\\n日\\r\\n'),f.buffer.tell())
                print('left','right',sep=':',end='!\\n',file=f,flush=True)
                f.writelines(['tail','\\nlast'])
                f.flush();print(f.tell())
                f.seek(0);print(repr(f.read()))
                f.close();print(open('text','rb').read())
            f=open('text','w',buffering=1)
            print(f.line_buffering,f.write_through)
            f.write('one\\n');print(open('text','rb').read());f.close()
        ''')

    def test_raw_descriptors_closefd_opener_and_path_protocol(self):
        self.compare('''
            import io
            events=[]
            class Path:
                def __fspath__(self):events.append('path');return 'raw'
            path=Path()
            raw=io.FileIO(path,'w+')
            print(raw.name is path,raw.mode,raw.closefd,isinstance(raw,io.RawIOBase),events)
            raw.write(b'abcdef');raw.seek(0)
            fd=raw.fileno()
            borrowed=open(fd,'rb',buffering=0,closefd=False)
            print(borrowed.name==fd,borrowed.read(1));borrowed.close()
            print(raw.read(1))
            def opener(path,flags):events.append(('opener',path,flags&3));return fd
            child=open('unused','rb',buffering=0,opener=opener)
            print(child.read(2),events)
            child.close()
            for action in [lambda:raw.read(1),raw.close]:
                try:action()
                except OSError as error:print(type(error).__name__,error.errno)
            raw.close()
            try:open(-1)
            except Exception as error:print(type(error).__name__)
        ''')

    def test_layer_constructors_detach_and_gc_owner_edges(self):
        self.compare('''
            import io,gc
            raw=io.FileIO('layers','w+')
            buffer=io.BufferedRandom(raw,4)
            text=io.TextIOWrapper(buffer,encoding='ascii',newline='\\r\\n')
            print(text.buffer is buffer,buffer.raw is raw)
            text.anchor=raw;raw.anchor=text
            del raw,buffer;gc.collect()
            text.write('a\\nb\\n');text.flush()
            text.seek(0);print(repr(text.read()))
            buffer=text.detach()
            print(buffer is buffer.raw.anchor.buffer if False else buffer.raw.anchor is text)
            try:text.read()
            except Exception as error:print(type(error).__name__)
            raw=buffer.detach();print(raw.closed)
            try:buffer.read()
            except Exception as error:print(type(error).__name__)
            raw.seek(0);print(raw.read());raw.close()
        ''')

    def test_errors_modes_validation_and_exception_hierarchy(self):
        self.compare('''
            import io
            print(io.open is open,issubclass(io.UnsupportedOperation,OSError),issubclass(io.UnsupportedOperation,ValueError))
            actions=[lambda:open('absent'),lambda:open('data','x'),lambda:open('data','rbb'),
                lambda:open('data','rw'),lambda:open('data','rb',encoding='utf-8'),
                lambda:open('data','r',buffering=0),lambda:open('data',closefd=False),
                lambda:open('data',newline='bad'),lambda:open('data',encoding='missing')]
            for action in actions:
                try:action()
                except Exception as error:print(type(error).__name__,isinstance(error,OSError))
            f=open('data','r')
            for action in [lambda:f.write('x'),lambda:f.seek(1,1),lambda:f.seek(1,2)]:
                try:action()
                except Exception as error:print(type(error).__name__,isinstance(error,OSError),isinstance(error,ValueError))
            f.close()
        ''',{'data':b'abc'})

    def test_text_decoding_errors_handlers_and_eager_chunk_validation(self):
        self.compare('''
            for encoding in ['utf-8','ascii','latin-1']:
                for errors in ['strict','ignore','replace','backslashreplace']:
                    f=open('bad','r',encoding=encoding,errors=errors)
                    try:print(encoding,errors,repr(f.read(1)),repr(f.read()))
                    except UnicodeDecodeError as error:print(error.encoding,error.start,error.end,error.reason,repr(error.object))
                    f.close()
            for errors in ['strict','ignore','replace','backslashreplace','xmlcharrefreplace']:
                f=open('out','w',encoding='ascii',errors=errors)
                try:print(f.write('aé日z'))
                except UnicodeEncodeError as error:print(error.encoding,error.start,error.end,error.reason,repr(error.object))
                f.close();print(open('out','rb').read())
        ''',{'bad':b'a\xff\xc3\xa9z'})

    def test_append_exclusive_open_failures_and_constructor_side_effects(self):
        self.compare('''
            for mode in ['ab+','a+b','at+','w+b','wb+']:
                with open('data',mode) as f:
                    print(f.mode,f.raw.mode if hasattr(f,'raw') else f.buffer.raw.mode)
                    f.seek(0);f.write(b'X' if 'b' in mode else 'X');f.flush()
                    f.seek(0);print(repr(f.read()))
            for index,options in enumerate([{'encoding':'missing'},{'newline':'bad'},{'buffering':0}]):
                try:open('failed'+str(index),'w',**options)
                except Exception as error:print(type(error).__name__)
                with open('failed'+str(index),'rb',buffering=0) as f:print(f.read(),f.fileno())
            for index,options in enumerate([{'encoding':1},{'errors':1},{'buffering':1.5}]):
                try:open('absent'+str(index),'w',**options)
                except Exception as error:print(type(error).__name__)
                try:open('absent'+str(index),'rb')
                except FileNotFoundError as error:print(error.filename,error.errno,error.strerror,str(error))
            with open('exclusive','x')as f:f.write('ok')
            try:open('exclusive','x')
            except FileExistsError as error:print(error.filename,error.errno)
        ''',{'data':b'abc'})

    def test_buffer_direction_restrictions_and_text_read_write_position(self):
        self.compare('''
            import io
            for constructor in [io.BufferedReader,io.BufferedWriter,io.BufferedRandom]:
                raw=io.FileIO('mixed','r+')
                f=constructor(raw,4)
                print(type(f).__name__,f.readable(),f.writable())
                for action in [lambda:f.read(1),lambda:f.write(b'X')]:
                    try:print(repr(action()))
                    except Exception as error:print(type(error).__name__)
                f.close()
            f=open('mixed','r+',encoding='utf-8')
            print(repr(f.read(1)),f.tell(),f.buffer.tell())
            f.write('Y');print(f.tell());f.flush();f.seek(0);print(repr(f.read()))
            f.close()
            f=open('mixed','w+',encoding='utf-8')
            f.write('abc');print(f.buffer.tell(),repr(f.read(0)),f.buffer.tell())
            f.close()
        ''',{'mixed':b'abcdef'})

    def test_iteration_tell_and_reentrant_path_size_callbacks_keep_gc_roots(self):
        self.compare('''
            import gc,io
            class Path:
                marker='alive'
                def __fspath__(self):gc.collect();return 'callbacks'
            path=Path()
            f=open(path,encoding='utf-8')
            raw=io.FileIO(path)
            del path;gc.collect();print(f.name,raw.name.marker)
            raw.close()
            print(repr(next(f)))
            try:f.tell()
            except Exception as error:print(type(error).__name__)
            print(repr(f.read()))
            try:f.tell()
            except Exception as error:print(type(error).__name__)
            f.seek(0);print(f.readlines(1))
            try:f.tell()
            except Exception as error:print(type(error).__name__)
            f.seek(0);print(f.readlines(),f.tell());f.close()
            f=open('callbacks','rb',buffering=0)
            class Size:
                def __index__(self):gc.collect();return 2
            print(f.read(Size()))
            class ClosingSize:
                def __index__(self):f.close();gc.collect();return 1
            try:f.read(ClosingSize())
            except Exception as error:print(type(error).__name__)
        ''',{'callbacks':b'a\nb\nlast'})

    def test_reconfigure_codec_newline_and_read_restrictions(self):
        self.compare('''
            f=open('change','w+',encoding='utf-8')
            f.write('é\\n');print(f.reconfigure(encoding='latin-1',newline='\\r\\n',write_through=True))
            print(f.encoding,f.errors,f.write_through)
            f.write('é\\n');f.flush();f.close();print(open('change','rb').read())
            f=open('change','r',encoding='latin-1');print(repr(f.read(1)))
            for options in [{'encoding':None},{'newline':None},{'errors':'ignore'},{'line_buffering':True}]:
                try:print(f.reconfigure(**options))
                except Exception as error:print(type(error).__name__)
            f.close()
            f=open('change','w',encoding='ascii',errors='ignore')
            f.reconfigure(encoding='ascii')
            print(f.errors)
            try:f.write('é')
            except UnicodeEncodeError:print('strict')
            f.close()
        ''')

    def test_native_data_attributes_implicit_methods_and_dynamic_names(self):
        self.compare('''
            import io,gc
            raw=io.FileIO('attrs','w+')
            buffer=io.BufferedRandom(raw,4)
            print(buffer.name)
            raw.name='renamed';print(raw.name,buffer.name)
            raw.__dict__['closed']='shadow';print(raw.closed)
            raw.encoding='extra';print(raw.encoding)
            del raw.encoding;print(hasattr(raw,'encoding'))
            raw.__enter__=lambda:'shadow'
            with raw as entered:print(entered is raw)
            text=open('attrs','r')
            text.mode='extra';print(text.mode)
            text.__dict__['encoding']='shadow';print(text.encoding)
            try:text.name='bad'
            except Exception as error:print(type(error).__name__)
            text.close()
            events=[]
            class Path:
                def __fspath__(self):return 'attrs'
                def __del__(self):events.append('final')
            path=Path();raw=io.FileIO(path);buffer=io.BufferedReader(raw)
            del path;gc.collect();print(events)
            raw.name='released';gc.collect();print(buffer.name,events)
            buffer.close()
        ''')

    def test_utf8_chunk_boundaries_universal_newlines_and_argument_types(self):
        self.compare('''
            f=open('boundary','r',encoding='utf-8')
            for size in [8191,1,1,2,1,8192,3]:
                value=f.read(size);print(len(value),repr(value[:2]),repr(value[-2:]))
            print(repr(f.read()),repr(f.newlines));f.close()
            for mode in ['rb','r']:
                for method in ['read','readline','readlines']:
                    f=open('boundary',mode,encoding=None if mode=='rb' else 'utf-8')
                    try:result=getattr(f,method)(None);print(type(result).__name__)
                    except Exception as error:print(type(error).__name__)
                    f.close()
        ''',{'boundary':('a'*8191+'é\r\n日\rlast\n'+'b'*8192+'\r').encode()})

    def test_binary_bytearray_typed_and_multidimensional_buffer_interop(self):
        self.compare('''
            for buffering in [0,4]:
                f=open('interop','w+b',buffering=buffering)
                source=bytearray(b'abcd');part=memoryview(source)[1:3]
                print(f.write(source),f.write(part),f.write(memoryview(source).cast('H')))
                part.release();f.seek(0)
                target=bytearray(b'?'*20);view=memoryview(target)[2:12]
                print(f.readinto(view),target,f.tell());view.release()
                f.seek(0);view=memoryview(target).cast('H')
                print(f.readinto(view),target);view.release()
                f.seek(0);view=memoryview(target).cast('B',[4,5])
                print(f.readinto(view),target);view.release()
                f.seek(0);print(f.readinto(bytearray()),f.tell())
                if buffering:
                    f.read(1);target=bytearray(b'?'*8)
                    print(f.readinto1(target),target)
                    for method in ['readinto','readinto1']:
                        for size in range(11):
                            f.seek(0);f.read(1);target=bytearray(b'?'*size)
                            print(method,size,getattr(f,method)(target),target,f.tell(),f.raw.tell())
                f.close()
        ''')

    def test_binary_export_validation_release_order_and_closed_file_callbacks(self):
        self.compare('''
            import gc
            for buffering in [0,4]:
                f=open('exports','w+b',buffering=buffering)
                events=[]
                class Export:
                    def __init__(self,data):self.data=bytearray(data)
                    def __buffer__(self,flags):
                        gc.collect();events.append(('get',flags,f.closed));self.view=memoryview(self.data);return self.view
                    def __release_buffer__(self,view):
                        gc.collect();events.append(('release',view is self.view,bytes(self.data),None if f.closed else f.tell()));view.release()
                source=Export(b'xyz')
                print(f.write(source),events);events.clear();f.seek(0)
                target=Export(b'????????')
                print(f.readinto(target),events,bytes(target.data));events.clear()
                f.close()
                for action in [lambda:f.write(source),lambda:f.readinto(target)]:
                    try:action()
                    except Exception as error:print(type(error).__name__,events);events.clear()
                target.data.append(33);print(target.data)
        ''')

    def test_binary_readinto_invalid_exports_and_callback_failures(self):
        self.compare('''
            for buffering in [0,4]:
                f=open('validation','w+b',buffering=buffering);f.write(b'abcdef');f.seek(0)
                values=[b'xx',memoryview(b'xx'),memoryview(bytearray(b'xxxx'))[::2],1,'text']
                for value in values:
                    try:print(f.readinto(value))
                    except Exception as error:print(type(error).__name__)
                try:f.write(memoryview(bytearray(b'xxxx'))[::2])
                except Exception as error:print(type(error).__name__)
                class Bad:
                    def __buffer__(self,flags):raise ValueError('custom')
                for action in [lambda:f.readinto(Bad()),lambda:f.write(Bad())]:
                    try:action()
                    except Exception as error:print(type(error).__name__)
                f.close()
        ''')

    def test_opaque_cookies_restore_expanded_errors_crlf_and_eof_decoder_state(self):
        self.compare('''
            for encoding,errors in [('ascii','backslashreplace'),('utf-8','replace'),('utf-8','ignore'),('latin-1','strict')]:
                for newline in [None,'']:
                    f=open('cookies','r',encoding=encoding,errors=errors,newline=newline)
                    print(encoding,errors,repr(newline))
                    while True:
                        char=f.read(1)
                        if not char:break
                        cookie=f.tell()
                        print(repr(char),cookie)
                        rest=f.read()
                        print(f.seek(cookie)==cookie,f.read()==rest)
                        f.seek(cookie)
                    f.close()
            f=open('cookies','r',encoding='latin-1')
            print(repr(next(f)));f.flush();print(f.tell());f.close()
            f=open('truncate','w+',encoding='utf-8')
            f.write('abc');print(f.truncate());f.seek(0);print(f.read());f.close()
        ''',{'cookies':b'A\xffB\r\nC\rD\nZ\xc3'})


    def test_random_text_reads_and_cookie_restore_traces(self):
        randomizer=random.Random(314159)
        cases=[];files={}
        for case in range(12):
            data=b''.join(randomizer.choice([b'a',b'\r',b'\n',b'\r\n','é'.encode(),'日'.encode(),b'\xff',b'\xc3'])for _ in range(25))
            files['trace'+str(case)]=data
            encoding,errors=randomizer.choice([('ascii','backslashreplace'),('utf-8','replace'),('utf-8','ignore'),('latin-1','strict')])
            newline=randomizer.choice([None,'','\n','\r','\r\n'])
            operations=[(randomizer.choice(['read','readline','save','restore','flush','current']),randomizer.choice([0,1,2,5,-1]))for _ in range(35)]
            cases.append((encoding,errors,newline,operations))
        source='cases='+repr(cases)+'\n'+textwrap.dedent('''
            for index,(encoding,errors,newline,operations) in enumerate(cases):
                f=open('trace'+str(index),encoding=encoding,errors=errors,newline=newline)
                saved=[0]
                for operation,size in operations:
                    try:
                        if operation=='read':value=f.read(size)
                        elif operation=='readline':value=f.readline(size)
                        elif operation=='save':value=f.tell();saved.append(value)
                        elif operation=='restore':value=f.seek(saved[size%len(saved)])
                        elif operation=='next':value=next(f)
                        elif operation=='flush':value=f.flush()
                        else:value=f.seek(0,1)
                        print(index,operation,repr(value))
                    except Exception as error:print(index,operation,type(error).__name__)
                f.close()
        ''')
        self.compare(source,files)

    def test_stale_iteration_snapshot_is_validated_before_stream_changes(self):
        # CPython 3.14.4 release builds can read beyond an empty stale
        # decoder snapshot after seek/iteration/flush. Validate our structural
        # snapshot instead; CPython's unstable result is not an oracle here.
        source='''
f=open('stale',encoding='utf-8')
f.seek(0)
next(f)
f.flush()
try:f.tell()
except OSError:print('safe error')
print(f.buffer.tell())
print(repr(f.read()))
f.close()
'''
        for profile,binary in self.binaries:
            with self.subTest(profile=profile),tempfile.TemporaryDirectory(prefix='pytors-stale-cookie-')as directory:
                directory=Path(directory);(directory/'stale').write_bytes(b'a\nb\n')
                result=subprocess.run([str(binary),source],cwd=directory,capture_output=True,env=self.environment,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertEqual(result.stdout,b"safe error\n4\n'b\\n'\n")

    def test_cookie_return_identity_and_structural_conversion_protocols(self):
        self.compare('''
            events=[]
            class I(int):
                def __int__(self):events.append('int');return 2
            class Index:
                def __index__(self):events.append('index');return 1
            class Number:
                def __lt__(self,other):events.append('lt');return False
                def __int__(self):events.append('int');return 1
            for value in [False,True,I(1),1.5,float('nan'),float('inf'),Index(),Number()]:
                events.clear();f=open('types')
                try:
                    result=f.seek(value);print(type(result).__name__,result is value,repr(f.read()),events)
                except Exception as error:print(type(error).__name__,events)
                f.close()
            f=open('types');cookie=f.tell();print(f.seek(cookie) is cookie);f.close()
            class Zero:
                def __eq__(self,other):events.append('eq');return True
                def __int__(self):raise AssertionError('must not convert')
            for whence in [1,2]:
                f=open('types');events.clear();result=f.seek(Zero(),whence)
                print(type(result).__name__,repr(f.read()),events);f.close()
            events.clear()
            try:f.seek(Number())
            except Exception as error:print(type(error).__name__,events)
        ''',{'types':b'abc'})

    def test_eof_decoder_state_retries_after_file_growth(self):
        self.compare('''
            f=open('grow','r',encoding='utf-8',errors='replace')
            print(repr(f.read(1)),f.tell())
            print(repr(f.read(1)),f.tell())
            print(repr(f.read(1)),f.tell())
            with open('grow','ab')as writer:writer.write('日\\n'.encode())
            print(repr(f.read()),f.tell())
            with open('grow','ab')as writer:writer.write(b'\\xc3')
            print(repr(f.read(1)),f.tell())
            print(repr(f.read(1)),f.tell())
            with open('grow','ab')as writer:writer.write(b'\\xa9')
            print(repr(f.read()),f.tell())
            f.close()
        ''',{'grow':'é\r'.encode()})



if __name__=='__main__':unittest.main()
