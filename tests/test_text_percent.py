"""Unicode percent formatting, argument protocols and callback continuations."""
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

WRAPPER='import sys,gc,functools,math\nexec(sys.argv[1])\n'

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TextPercentTests(unittest.TestCase):
    maxDiff=None
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-text-percent-');cls.addClassCleanup(cls.directory.cleanup)
        supplied=os.environ.get('PYTORS_TEXT_PERCENT_DRIVER')
        if supplied:cls.binary=Path(supplied);return
        result=transpile(WRAPPER,TranspileOptions(optimize=False));
        if not result.success:raise AssertionError(result.diagnostics)
        path=Path(cls.directory.name)/'main.rs';path.write_text(result.rust_source,encoding='utf-8');cls.binary=path.with_suffix('')
        built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(cls.binary)],capture_output=True,text=True,timeout=150)
        if built.returncode:raise AssertionError(built.stderr)
    def compare(self,source):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,'-I','-c',WRAPPER,source],capture_output=True,text=True,timeout=60)
        actual=subprocess.run([str(self.binary),source],capture_output=True,text=True,timeout=60)
        self.assertEqual(expected.returncode,0,expected.stderr);self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
    def test_basic_flags_precision_unicode_and_every_conversion(self):
        self.compare('''
            for fmt,value in [('%05d',7),('%c',-1),('%c',1<<32),('%c','é'),('%(x)s',{'x':'ok'}),('%.*s',(2,'é🙂x'))]:
                try:print(repr((fmt,'ok',fmt%value)))
                except BaseException as error:print(repr((fmt,type(error).__name__,str(error))))
            for kind in 'diuoxXeEfFgGsrca':
                for flags in ['', '-', '+', ' ', '#', '0', '-0', '+ ', '#0', '+#0']:
                    for width in ['', '12']:
                        for precision in ['', '.', '.0', '.2', '.7']:
                            fmt='%'+flags+width+precision+kind
                            value='é🙂x' if kind in 'sra' else ('🙂' if kind=='c' else -27)
                            try:print(repr((fmt,fmt%value)))
                            except BaseException as error:print(fmt,type(error).__name__,str(error))
            for width in [-12,-1,0,1,8]:
                for precision in [-2,-1,0,1,2,6]:print(repr('%*.*s'%(width,precision,'é🙂x')))
            for value in [1e30,1e100,-1e100,float('inf'),float('nan')]:
                for fmt in ['%d','%i','%u','%+010.7d']:
                    try:print(fmt,fmt%value)
                    except BaseException as error:print(fmt,type(error).__name__,str(error))
        ''')
    def test_parsing_and_argument_errors(self):
        self.compare('''
            class Index:
                def __index__(self):raise AssertionError('star must not call index')
            cases=[('',None),('',()),('',(1,)),('%%',{}),('%%',[]),('%%',b''),('%%',set()),
                   ('%',()),('%+',()),('%3',()),('%.',()),('%.*',()),('%h',()),('%lls',1),
                   ('%q',()),('%q',1),('%é',1),('🙂%q',1),('%5%',1),('%s',(1,2)),
                   ('%*s',(Index(),'x')),('%.*s',(Index(),'x')),('%*s',('3','x')),
                   ('%999999999999999999999999s','x'),('%.99999999999999999999999s','x'),
                   ('%(bad',{}),('%(bad',1),('%()s',{'':'ok'}),('%((a))s',{'(a)':'ok'}),
                   ('%(x)*s',{'x':3}),('%(x)*s',{'x':(2,'x')}),('%(x)s%s',{'x':'a'}),
                   ('%s%(x)s',{'x':'a'}),('%s%s',{}),('%(x)s',[]),('%(x)s',b'abc'),
                   ('%c',''),('%c','é🙂'),('%c',b'a'),('%c',1.5)]
            for fmt,value in cases:
                try:print(repr((fmt,'ok',fmt%value)))
                except BaseException as error:print(repr((fmt,type(error).__name__,str(error))))
        ''')
    def test_mapping_order_nested_keys_mutation_and_gc(self):
        self.compare('''
            events=[]
            class Mapping:
                def __getitem__(self,key):events.append(('get',key));gc.collect();return Text(key)
            class Text:
                def __init__(self,text):self.text=text
                def __str__(self):events.append(('str',self.text));gc.collect();return 'é🙂'+self.text
            print('%(one)8.3s|%((two))s'%Mapping());print(events)
            events.clear()
            for fmt in ['%(one)','%(one)q','%(one)*s','%(one)99999999999999999999s','%(one)s %(two)s']:
                try:print(fmt%Mapping())
                except BaseException as error:print(type(error).__name__,str(error))
                print(events);events.clear()
            class Tuple(tuple):
                def __getitem__(self,key):raise AssertionError('tuple override')
                def __len__(self):raise AssertionError('tuple length')
            print('%s %d'%Tuple(('ok',7)))
            class Map(dict):
                def __missing__(self,key):gc.collect();return key.upper()
            print('%(missing)s'%Map())
        ''')
    def test_integer_float_and_character_protocols_error_masking(self):
        self.compare('''
            events=[]
            class Number:
                def __int__(self):events.append('int');gc.collect();return 27
                def __index__(self):events.append('index');gc.collect();return 65
                def __float__(self):events.append('float');gc.collect();return 2.5
            class Int(int):
                def __int__(self):events.append('int override');return 91
                def __index__(self):events.append('index override');return 92
                def __float__(self):events.append('float override');return 3.25
            class Float(float):
                def __int__(self):events.append('float int');return 93
                def __float__(self):events.append('float float');return 94.0
            for value in [Number(),Int(7),Float(1.25)]:
                for fmt in ['%d','%i','%u','%x','%c','%f']:
                    events.clear()
                    try:result=('ok',fmt%value)
                    except BaseException as error:result=(type(error).__name__,str(error))
                    print(fmt,type(value).__name__,result,events)
            for kind in ['int','index','float']:
                for error_type in [TypeError,ValueError,LookupError,StopIteration]:
                    class Bad:
                        pass
                    def operation(self):raise error_type('callback failure')
                    setattr(Bad,'__'+kind+'__',operation)
                    for fmt in ['%d','%x','%c','%f']:
                        try:print('ok',fmt%Bad())
                        except BaseException as error:print(kind,fmt,type(error).__name__,str(error))
            class Bad:
                def __int__(self):return 'wrong'
                def __index__(self):return 'wrong'
                def __float__(self):return 7
            for fmt in ['%d','%x','%c','%f']:
                try:print(fmt%Bad())
                except BaseException as error:print(fmt,type(error).__name__,str(error))
        ''')
    def test_operator_explicit_wrappers_and_reflected_subclasses(self):
        self.compare('''
            class Format(str):pass
            class Right(str):
                def __rmod__(self,left):return 'reflected:'+left
            print('%s'%Right('value'))
            print(Format('%s')%'value')
            print(str.__mod__('%05d',7),str.__rmod__('value','%s'))
            print(str.__rmod__('x',3) is NotImplemented)
            value=Format('%s');value%='done';print(type(value).__name__,value)
            class Text:
                def __str__(self):return 'str'
                def __repr__(self):return 'ré🙂'
            print('%s|%r|%a|%12.3r'%(Text(),Text(),Text(),Text()))
            for operation in [lambda:str.__mod__('%s'),lambda:str.__mod__('%s',1,2),lambda:str.__mod__('%s',1,x=2)]:
                try:operation()
                except BaseException as error:print(type(error).__name__,str(error))
        ''')
    def test_recursive_callbacks_and_finite_depth_gc(self):
        self.compare('''
            class Value:
                def __init__(self,depth):self.depth=depth
                def next(self):return Value(self.depth-1)
                def __str__(self):return 'done' if self.depth==0 else '%s'%self.next()
                def __repr__(self):return 'done' if self.depth==0 else '%r'%self.next()
                def __int__(self):
                    if self.depth==0:gc.collect();return 7
                    return int('%d'%self.next())
                def __index__(self):
                    if self.depth==0:gc.collect();return 65
                    return ord('%c'%self.next())
                def __float__(self):
                    if self.depth==0:gc.collect();return 1.25
                    return float('%.2f'%self.next())
                def __getitem__(self,key):
                    if self.depth==0:gc.collect();return 7
                    return int('%(key)d'%self.next())
            sys.setrecursionlimit(3000)
            for fmt in ['%s','%r','%d','%x','%c','%f','%(key)d']:
                print('finite',fmt,fmt%Value(300))
            class Infinite:
                def __str__(self):return '%s'%self
                def __repr__(self):return '%r'%self
                def __int__(self):return int('%d'%self)
                def __index__(self):return ord('%c'%self)
                def __float__(self):return float('%f'%self)
                def __getitem__(self,key):return '%(key)s'%self
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for fmt in ['%s','%r','%d','%x','%c','%f','%(key)s']:
                    try:fmt%Infinite();result='unexpected return'
                    except RecursionError:result='caught'
                    print(limit,fmt,result)
        ''')
    def test_many_directives_use_heap_progress_instead_of_rust_recursion(self):
        self.compare("values=tuple(range(20000))\nvalue=('%d,'*20000)%values\nprint(len(value),value[:12],value[-12:])\n")
    def test_seeded_primitive_differential_corpus(self):
        rng=random.Random(20261027);cases=[]
        for _ in range(500):
            kind=rng.choice('diuoxXeEfFgGsrca');flags=rng.choice(['','-','0','+','#','+#0',' ']);width=rng.choice(['','1','8','15']);precision=rng.choice(['','.0','.2','.8'])
            value=rng.choice(['é🙂a','日本語','', 'a\x00b']) if kind in 'sra' else (rng.choice(['é','🙂','a'])if kind=='c'else rng.randint(-100000,100000))
            cases.append(('%'+flags+width+precision+kind,value))
        self.compare('for fmt,value in '+repr(cases)+':\n try:print(repr(fmt%value))\n except BaseException as error:print(type(error).__name__,str(error))\n')
    def test_native_conversion_boundaries_and_input_suppressed_errors(self):
        self.compare('''
            class Number:
                __int__=staticmethod(functools.partial(len,42))
                __index__=staticmethod(functools.partial(len,42))
            for fmt in ['%d','%x','%c']:
                try:print(fmt%Number())
                except BaseException as error:print(type(error).__name__,str(error))
            class Stop:
                __int__=staticmethod(functools.partial(next,iter([])))
            marker=object()
            print(next(map(lambda x:'%d'%x,[Stop()]),marker)is marker)
            saved=(sys.stdin,sys.stdout,sys.stderr);events=[]
            class Reader:
                def readline(self):events.append('readline');return '3\\n'
            class Writer:
                def write(self,text):events.append(('write',text))
                def flush(self):events.append('flush')
            class Error:
                pass
            class InputInt:
                __int__=staticmethod(input)
            Error.flush=staticmethod(functools.partial(len,42))
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                try:'%d'%InputInt()
                except BaseException as error:outcome=(type(error).__name__,str(error))
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(outcome,events)
            Error.flush=staticmethod(functools.partial(str.__mod__,'%d',Number()));events.clear()
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                result=input()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print(result,events)
            class Source:
                def __iter__(self):return iter([1])
                __len__=staticmethod(functools.partial(str.__mod__,'%d',Number()))
                def __length_hint__(self):return 1
            print(list(Source()))
        ''')
    def test_aot_wrappers_unicode_c_diagnostics_and_large_float_decimal(self):
        source=textwrap.dedent('''
            import gc
            class Text:
                def __str__(self):gc.collect();return 'é🙂x'
            class Mapping:
                def __getitem__(self,key):gc.collect();return Text()
            print('%05d|%.2s'%(7,Text()))
            print('%(key)6.2s'%Mapping())
            print(str.__mod__('%c','é'))
            print('%d'%1e100)
            for value in [-1,1<<32]:
                try:print('%c'%value)
                except OverflowError as error:print(type(error).__name__,str(error))
        ''')
        result=transpile(source,TranspileOptions(optimize=False));self.assertTrue(result.success,result.diagnostics)
        root=Path(self.directory.name);path=root/'aot.rs';path.write_text(result.rust_source,encoding='utf-8');binary=path.with_suffix('')
        built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=150);self.assertEqual(built.returncode,0,built.stderr)
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=20)
        actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20)
        self.assertEqual(expected.returncode,0,expected.stderr);self.assertEqual(actual.returncode,0,actual.stderr);self.assertEqual(actual.stdout,expected.stdout)
        unsupported="for operation in [lambda:'%c'%55296,lambda:str.__mod__('%c',55296),lambda:format(55296,'c')]:\n try:operation()\n except BaseException as error:print(type(error).__name__,str(error))\n"
        actual=subprocess.run([str(self.binary),unsupported],capture_output=True,text=True,timeout=20)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,('NotImplementedError unpaired Unicode surrogates are not supported\n')*3)

    def test_float_special_values_rounding_and_unicode_character_boundaries(self):
        self.compare('''
            values=[0.0,-0.0,1.005,-1.005,2.675,1e-300,5e-324,1e100,1.7976931348623157e308,float('inf'),-float('inf'),float('nan'),-float('nan')]
            for value in values:
                for kind in 'eEfFgG':
                    for flags in ['', '+', ' ', '#0', '+#0', '-0']:
                        for precision in [0,1,2,6,17]:
                            fmt='%'+flags+'16.'+str(precision)+kind
                            print(repr(fmt%value))
            for value in [0,127,255,256,55295,57344,1114111,-1,1114112,1<<32]:
                for fmt in ['%c','%4c','%-4c','%.0c']:
                    try:print(value,repr(fmt%value))
                    except BaseException as error:print(value,type(error).__name__,str(error))
        ''')
