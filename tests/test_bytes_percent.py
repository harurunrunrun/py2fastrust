"""Binary printf conversions preserve buffers, callbacks and argument order."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import test_runtime
from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class BytesPercentTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source, **options):
        source = textwrap.dedent(source)
        self.run_source(source + "\nexec(" + repr(source) + ", {})\n", **options)

    def test_conversions_flags_width_precision_and_binary_data(self):
        self.compare(r'''
            for owner in (bytes, bytearray):
                for f, value in [
                    (b'plain\xff', ()), (b'100%%', ()),
                    (b'%b|%s|%a|%r', (b'\x00\xff', bytearray(b'abc'), '\xe9\u65e5', '\u2603')),
                    (b'%c%c%c', (65, b'\x00', bytearray(b'\xff'))),
                    (b'%+09d|% 8i|%-08u', (-123, 45, 3)),
                    (b'%#010x|%#010X|%#010o', (-255, 255, 255)),
                    (b'%08.5d|%#.0x|%#.0o|%.0d', (12, 0, 0, 0)),
                    (b'%05c|%08s|%-8.2b|%.3r', (65, b'abc', b'abcdef', '\xe9')),
                    (b'%*.*b|%*s|%.*s', (8, 3, b'abcdef', -5, b'x', -1, b'abc')),
                    (b'%*s', (-9223372036854775808,b'x')),
                    (b'%hd|%ld|%Ld|%u', (1, 2, 3, -4)),
                    (b'%+012.4f|%#.0e|%#.4g|%08F', (-1.25, 1.25, 1.25, float('inf'))),
                    (b'%.0g|%.5G|%E|%f', (1.25, 123456., .00001, -0.0)),
                ]:
                    result = owner(f) % value
                    print(type(result).__name__, result)
                value = owner(b'%s'); alias = value; value %= b'x'
                print(value, alias, value is alias)
        ''')

    def test_mapping_parentheses_and_argument_boundaries(self):
        self.compare(r'''
            events=[]
            class Mapping:
                def __getitem__(self,key):
                    events.append(key)
                    return {b'a':b'A',b'a(b)c':b'B',b'n':42}[key]
            for owner in (bytes, bytearray):
                print(owner(b'%(a)s %(a(b)c)b %(n)#08x')%Mapping(),events)
                for f,value in [(b'plain',{}),(b'%%',[]),(b'plain',range(2)),(b'plain',memoryview(b'x')),
                    (b'%s',()),(b'plain',(1,)),(b'%s',(b'a',b'b')),(b'%(a)s',()),
                    (b'%(a)s%s',{b'a':b'A'}),(b'%(n)*s',Mapping()),(b'%(a',Mapping()),
                    (b'%(a)s',[]),(b'%(a)s',memoryview(b'x')),(b'%s',{'a':1})]:
                    try:print(owner(f)%value)
                    except Exception as error:print(type(error).__name__)
        ''')

    def test_numeric_and_bytes_protocol_priority_and_gc(self):
        self.compare(r'''
            import gc
            events=[]
            class Number:
                def __int__(self):events.append('int');gc.collect();return 12
                def __index__(self):events.append('index');gc.collect();return 13
                def __float__(self):events.append('float');gc.collect();return 1.25
            class Exporter:
                def __buffer__(self,flags):events.append(('buffer',flags));gc.collect();return memoryview(b'abcd')[::2]
                def __release_buffer__(self,view):events.append(('release',view.tobytes()));gc.collect();view.release()
            class Both(Exporter):
                def __bytes__(self):events.append('bytes');gc.collect();return b'bytes'
            class Bytes(bytes):
                def __bytes__(self):events.append('bytes override');return b'bad'
            class Array(bytearray):
                def __bytes__(self):events.append('array override');return b'bad'
            class Integer(int):
                def __int__(self):events.append('int override');return 99
                def __index__(self):events.append('index override');return 98
            class IntegerFloat(int):
                def __float__(self):events.append('integer float');return 9.25
            class Float(float):
                def __int__(self):events.append('float int');return 9
                def __float__(self):events.append('float override');return 7.5
            class Repr:
                def __repr__(self):gc.collect();return '\xe9\U0001f600'
            print(b'%d %x %c %.2f'%(Number(),Number(),Number(),Number()))
            print(b'%s %b %s %s'%(Exporter(),Both(),Bytes(b'good'),Array(b'right')))
            print(bytearray(b'%d %x %d %.2f %a')%(Integer(2),Integer(3),Float(2.5),Float(2.5),Repr()))
            print(b'%.2f'%IntegerFloat(2))
            print(events)
            class FloatError:
                def __float__(self):raise LookupError('float sentinel')
            try:b'%f'%FloatError()
            except Exception as error:print(type(error).__name__,error.__context__ is None)
            for f,value in [(b'%*s',(Number(),b'x')),(b'%d','12'),(b'%f',b'1.5'),(b'%x',1.2),
                (b'%.*s',(2147483648,b'x')),(b'%.*s',(-2147483649,b'x')),(b'%c',memoryview(b'x')),(b'%c',256),(b'%c',-1),(b'%c',b'xx'),(b'%s',[1,2])]:
                try:print(f%value)
                except Exception as error:print(type(error).__name__)
        ''')

    def test_live_mutable_format_pinning_and_exception_cleanup(self):
        self.compare(r'''
            import gc
            for altered in (b'%s-ABC',b'%s-%r!',b'%s%%%s'):
                f=bytearray(b'%s-%s!')
                class Mutate:
                    def __bytes__(self):f[:]=altered;gc.collect();return b'A'
                try:print(f%(Mutate(),b'B'))
                except Exception as error:print(type(error).__name__)
                print(f);f.append(33);print(f)
            f=bytearray(b'%s')
            class Resize:
                def __bytes__(self):f.append(33);return b'A'
            try:print(f%Resize())
            except Exception as error:print(type(error).__name__)
            f.append(33);print(f)
            class Bad:
                def __bytes__(self):raise LookupError('sentinel')
            try:bytearray(b'%s')%Bad()
            except Exception as error:print(type(error).__name__,str(error))
        ''')

    def test_descriptors_subclasses_and_reflected_operators(self):
        self.compare(r'''
            class B(bytes):pass
            class A(bytearray):pass
            for value in (B(b'%s'),A(b'%s')):
                result=value%b'good';print(type(result).__name__,result)
            for owner,value in ((bytes,b'x'),(bytearray,bytearray(b'x'))):
                for left in (b'%s',bytearray(b'%s'),'%s',1):
                    result=owner.__rmod__(value,left)
                    print(result is NotImplemented,result if result is not NotImplemented else 'NI')
                print(owner.__mod__(owner(b'%b'),b'value'))
            class Override(bytes):
                def __mod__(self,other):return 'override'
            class Reflected:
                def __rmod__(self,other):return ('reflected',other)
            print(Override(b'%s')%b'x',b'%s'%Reflected(),bytearray(b'%s')%Reflected())
            for f in (b'%',b'%q',b'%5%',b'%\xff',b'%99999999999999999999999999s',b'%.99999999999999999999999s'):
                try:print(f%b'x')
                except Exception as error:print(type(error).__name__)
        ''')

    def test_deterministic_float_matrix_and_big_integer_precision(self):
        self.compare('''
            state=17
            for index in range(150):
                state=(state*1103515245+12345)%2147483647
                value=(state-1073741824)/(10**(index%13))
                for kind in (b'f',b'e',b'g',b'G'):
                    f=b'%+#018.'+str(index%9).encode()+kind
                    print(f%value)
            for flags in (b'',b'#',b'+',b' ',b'0',b'-',b'+#0',b'-#0'):
                for precision in (b'',b'.0',b'.3'):
                    for kind in (b'd',b'i',b'u',b'o',b'x',b'X'):
                        for value in (0,1,-1,42,-42,2147483647):
                            f=b'%'+flags+b'12'+precision+kind;print(f%value)
            try:b'%f'%(10**1000)
            except Exception as error:print(type(error).__name__)
            n=2**100+12345
            for value in (n,-n,0):
                print(b'%+050.40d|%#050.40x|%#.40o'%(value,value,value))
        ''',integer='bigint')

    def test_all_integer_modes_debug_release_without_external_tools(self):
        source = textwrap.dedent('''
            import gc
            class Value:
                def __bytes__(self):gc.collect();return b'bytes'
            print(b'%s %a %#010x %+.3f'%(Value(),'\u65e5',-255,1.25))
            a=bytearray(b'%(x)b %(n)08.4d')
            print(a%{b'x':memoryview(b'abcd')[::2],b'n':-12})
            class Mutate:
                def __bytes__(self):a[:]=b'%s-%r!';return b'A'
            a[:]=b'%s-%s!';print(a%(Mutate(),b'B'));a.append(33);print(a)
            exec("print(bytearray(b'%*.*s') % (-6,3,b'abcdef'))")
        ''')
        expected = subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,check=True).stdout
        with tempfile.TemporaryDirectory(prefix='bytes-percent-standalone-') as directory:
            path = Path(directory)
            for integer in ('i64','i128','bigint'):
                result = transpile(source,TranspileOptions(integer=integer,filename='binary_format.py',optimize=False))
                self.assertTrue(result.success,result.diagnostics)
                target = path/(integer+'.rs'); target.write_text(result.rust_source,encoding='utf-8')
                for release in (False,True):
                    with self.subTest(integer=integer,release=release):
                        binary = path/(integer+('-release' if release else '-debug'))
                        command = ['rustc','--edition=2021',str(target),'-o',str(binary)]
                        if release:command.append('-O')
                        compiled = subprocess.run(command,capture_output=True,text=True,timeout=180)
                        self.assertEqual(compiled.returncode,0,compiled.stderr)
                        environment = dict(os.environ,PATH=str(path/'no-tools'))
                        environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
                        actual = subprocess.run([str(binary)],cwd=path,env=environment,capture_output=True,text=True,timeout=20)
                        self.assertEqual(actual.returncode,0,actual.stderr)
                        self.assertEqual(actual.stdout,expected)


if __name__ == '__main__':
    unittest.main()
