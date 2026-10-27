"""CPython differential checks for float/bytes native subclass payloads."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeScalarSubclassTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source):
        source = textwrap.dedent(source)
        return self.run_source(source + "\nexec(" + repr(source) + ", {})\n")

    def test_construction_conversion_identity_and_initializer_order(self):
        self.compare('''
            events=[]
            class F(float):pass
            class B(bytes):pass
            f=F(1.75);b=B(b'abcdefgh')
            f.note='float';b.note='bytes'
            for cls,value in [(F,f),(B,b)]:
                print(type(value) is cls,isinstance(value,cls.__bases__[0]),value.note)
                print(cls.__new__ is cls.__bases__[0].__new__)
                print(type(cls(value)) is cls,cls(value) is value)
            print(float(f),type(float(f)) is float,float(f) is float(f))
            print(bytes(b),type(bytes(b)) is bytes,bytes(b) is bytes(b))
            print(float.__float__(f) is f,bytes.__bytes__(b) is b)
            class Convert:
                def __float__(self):events.append('float');return 2.5
                def __bytes__(self):events.append('bytes');return b
            print(F(Convert()),B(Convert()),events)
            class IndexOnly:
                def __index__(self):events.append('index');return 7
            class Text(str):pass
            print(F(b'1.25'),F(Text('2.5')),F(IndexOnly()),events[-1])
            for text in ['  +1_2.5_0e-1  ','\u2003-\uff11\uff12.\u0665\u2003','inf','-INFINITY','nan']:
                print(F(text))
            for text in ['1__0','_1','1_','1_.0','1._0','nan_','1e_2','\x1c1']:
                try:F(text)
                except Exception as error:print(type(error).__name__)
            print(bytes(Convert()) is b,bytes.__new__(bytes,Convert()) is b)
            value=B(Convert());print(type(value) is B,value is b,events)
            class SubFloatReturn:
                def __float__(self):return F(6.5)
                def __index__(self):raise AssertionError('float precedes index')
            print(float(SubFloatReturn()),F(SubFloatReturn()))
            class InvalidFloat:
                def __float__(self):events.append('bad float');return 3
                def __index__(self):raise AssertionError('must not use index')
            try:F(InvalidFloat())
            except Exception as error:print(type(error).__name__,events[-1])
            class Initialize(float):
                def __init__(self,*args,**kw):events.append(('init',args,list(kw.items())))
            print(Initialize(extra=7),Initialize(2.5,extra=9),events[-2:])
            class New(float):
                def __new__(cls,value):events.append('new');return super().__new__(cls,value)
                def __init__(self,value):events.append('initialized')
            print(New(3.5),events[-2:])
            class Foreign(bytes):
                def __new__(cls,value):return value
                def __init__(self,value):raise AssertionError('foreign init')
            print(Foreign(17))
            for factory in [lambda:F(extra=1),lambda:Initialize(1,2),lambda:B(extra=1),
                            lambda:float.__new__(bytes,1),lambda:bytes.__new__(float,b'a')]:
                try:factory()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_native_descriptors_numeric_sequence_and_index_protocols(self):
        self.compare('''
            class F(float):pass
            class B(bytes):pass
            f=F(3.5);b=B(b'abcd')
            print(f+2,2+f,f-2,2-f,f*2,2*f,f/2,7/f,f//2,7//f,f%2,7%f)
            print(f**2,2**f,divmod(f,2),divmod(7,F(2)))
            print(-f,+f,abs(f),int(f),bool(f),not F(0),round(f),round(f,1))
            print(float.__pow__(f,2,None),float.__rpow__(f,2,None),float.__divmod__(f,2))
            print(f.real,f.imag,f.conjugate(),type(f.real) is float)
            print(f.real is f.real,f.conjugate() is f.conjugate())
            x=1.75;print(x.real is x,x.conjugate() is x,x.imag is x.imag)
            print(F.real.__objclass__ is float,F.conjugate.__objclass__ is float)
            print(f.conjugate.__self__ is f,F.__add__.__objclass__ is float)
            print(hash(f)==hash(3.5),{f:'float'}[3.5],f==3.5,f<4,4>f)
            print(b+b'ef',b'zz'+b,b*2,2*b,b*0,b*-2)
            print(type(b+b) is bytes,type(b*1) is bytes)
            print(len(b),bool(b),not B(),b[1],b[-1],b[::2],list(b),list(reversed(b)))
            print(B(b'bc') in b,98 in b,b'zz' not in b,hash(b)==hash(b'abcd'),{b:7}[b'abcd'])
            print(b==b'abcd',b<B(b'zz'),b.decode(),b.find(B(b'bc')))
            print(b.hex(),bytes.hex(b),b.hex(':',2),b.hex(b'-',-3),b.hex(sep=':',bytes_per_sep=0))
            print(b.hex(bytes_per_sep=2))
            for action in (lambda:b.hex(None),lambda:b.hex('xx'),lambda:b.hex('é'),
                           lambda:b.hex(':',1<<31),lambda:b.hex(':',1.5),lambda:b.hex(unknown=1)):
                try:action()
                except Exception as error:print(type(error).__name__)
            print(B(b',').join([B(b'ab'),B(b'cd')]),b.split(B(b'b')))
            class Index:
                def __index__(self):return 2
            print(b*Index(),Index()*b,bytes.__mul__(b,Index()),b[Index()])
            print(bytes.__contains__(b,B(b'bc')),bytes.__add__(b,b))
            print(float.__add__(f,object()) is NotImplemented)
            for descriptor,arguments in [(float.__float__,(1,)),(bytes.__bytes__,('a',)),
                (F.real.__get__,('a',)),(float.__add__,(f,)),(bytes.__mul__,(b,)),
                (bytes.__contains__,(b,999)),(bytes.__mul__,(b,1<<62)),
                (float.__pow__,(f,2,3))]:
                try:descriptor(*arguments)
                except Exception as error:print(type(error).__name__)
        ''')

    def test_python_overrides_mro_and_explicit_native_bypass(self):
        self.compare('''
            events=[]
            class NumericMixin:
                def __float__(self):events.append('convert');return 9.5
                def __neg__(self):return 'negative'
                def __bool__(self):return False
                def __hash__(self):return 19
                def __add__(self,other):return 'add'
                def __radd__(self,other):return 'radd'
                def __eq__(self,other):return 'equal'
                def conjugate(self):return 'conjugate'
            class Native(float,NumericMixin):pass
            class Python(NumericMixin,float):pass
            for cls in (Native,Python):
                value=cls(1.25)
                print(cls.__name__,float(value),-value,bool(value),value+2,2+value,value==2,value.conjugate())
                print(float.__float__(value),float.__neg__(value),float.__add__(value,2),hash(value))
            class ByteMixin:
                def __len__(self):return 9
                def __iter__(self):return iter([7,8])
                def __contains__(self,item):return 'contains'
                def __getitem__(self,item):return 'item'
                def __bytes__(self):events.append('byteconvert');return b'custom'
                def __add__(self,other):return 'byteadd'
                def __radd__(self,other):return 'byteradd'
            class NativeBytes(bytes,ByteMixin):pass
            class PythonBytes(ByteMixin,bytes):pass
            for cls in (NativeBytes,PythonBytes):
                value=cls(b'abcd')
                print(cls.__name__,len(value),list(value),3 in value,value[0],bytes(value),value+b'e',b'e'+value)
                print(bytes.__len__(value),bytes.__getitem__(value,0),list(bytes.__iter__(value)))
            class Reflected(float):
                def __radd__(self,other):return 'subtype first'
                def __rdivmod__(self,other):return 'divmod reflected'
            print(1.25+Reflected(2),divmod(5,Reflected(2)))
            class Override(float):
                def __divmod__(self,other):return ('override',other)
                def __neg__(self):return 17
            print(divmod(Override(3),2),-Override(3),events)
            class Display(float):
                def __repr__(self):return 'float repr'
                @property
                def real(self):return 'custom real'
            value=Display(1.25)
            print(str(value),repr(value),float.__repr__(value),value.real,float.real.__get__(value))
            class ByteDisplay(bytes):
                def __repr__(self):return 'bytes repr'
                def __str__(self):return 'bytes str'
                def __bytes__(self):return b'converted'
            value=ByteDisplay(b'abcd')
            print(str(value),repr(value),bytes.__str__(value),bytes.__repr__(value),bytes(value),bytes.__bytes__(value))
        ''')

    def test_slots_properties_layout_conflicts_and_gc(self):
        self.compare('''
            import gc
            class F(float):
                __slots__=('value','__weakref__')
            class EmptyF(float):__slots__=()
            class B(bytes):pass
            class EmptyB(bytes):__slots__=()
            class Plain:pass
            class Mixed(bytes,Plain):pass
            f=F(2.5);f.value=['shared'];print(f,f.value,hasattr(f,'__dict__'),hasattr(f,'__weakref__'))
            for value in (EmptyF(1),B(b'abcd'),EmptyB(b'abcd'),Mixed(b'abcd')):
                print(type(value).__name__,hasattr(value,'__dict__'),hasattr(value,'__weakref__'))
            for definition in ["class Bad(bytes):__slots__=('x',)",
                               "class Bad(bytes):__slots__=('__weakref__',)",
                               "class Bad(float,bytes):pass"]:
                try:exec(definition)
                except Exception as error:print(type(error).__name__)
            for value in (f,EmptyF(1)):
                try:value.real=17
                except Exception as error:print(type(error).__name__)
            for value in (f,EmptyB(b'abcd')):
                try:value.missing=1
                except Exception as error:print(type(error).__name__)
            events=[]
            class Final(bytes):
                def __del__(self):events.append((type(self).__name__,bytes(self)))
            def make():
                value=Final(b'abcd');value.cycle=[value]
            make();gc.collect();print(events)
            values=[]
            for i in range(300):
                value=B(b'abcd');value.cycle=[value];values.append(value)
            gc.collect();print(len(values),values[-1],values[-1].cycle[0] is values[-1])
        ''')

    def test_all_modes_debug_release_standalone(self):
        source=textwrap.dedent('''
            class F(float):pass
            class B(bytes):pass
            f=F(2.5);b=B(b'abcdefgh');alias=b
            print(f, f+3, 3+f, -f, f.real, f.conjugate(), divmod(f,2))
            print(b,b*2,2*b,b+b'!',b[1:4],98 in b,bytes(b) is bytes(b))
            b+=b'!';print(alias,b,type(b) is bytes,alias is b)
            f+=1;print(f,type(f) is float)
            exec("class D(float):pass\\nprint(D(1.5)+2, type(D(1.5)).__name__)")
        ''')
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,check=True).stdout
        with tempfile.TemporaryDirectory(prefix='scalar-subclass-standalone-') as directory:
            path=Path(directory)
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,filename='scalar.py',optimize=False))
                self.assertTrue(result.success,result.diagnostics)
                target=path/(integer+'.rs');target.write_text(result.rust_source,encoding='utf-8')
                for optimized in (False,True):
                    with self.subTest(integer=integer,release=optimized):
                        binary=path/(integer+('-release' if optimized else '-debug'))
                        command=['rustc','--edition=2021',str(target),'-o',str(binary)]
                        if optimized:command.append('-O')
                        compiled=subprocess.run(command,capture_output=True,text=True,timeout=150)
                        self.assertEqual(compiled.returncode,0,compiled.stderr)
                        environment=dict(os.environ,PATH=str(path/'no-tools'))
                        environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
                        actual=subprocess.run([str(binary)],env=environment,capture_output=True,text=True,timeout=15)
                        self.assertEqual(actual.returncode,0,actual.stderr)
                        self.assertEqual(actual.stdout,expected)


if __name__=='__main__':unittest.main()
