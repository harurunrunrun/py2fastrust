"""Binary decimal formatting keeps internal float truncation exact."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions,transpile

WRAPPER='import sys,gc\nexec(sys.argv[1])\n'

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class BytesPercentExactTests(unittest.TestCase):
    maxDiff=None
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-bytes-exact-');cls.addClassCleanup(cls.directory.cleanup)
        result=transpile(WRAPPER,TranspileOptions(optimize=False,integer='i64'))
        if not result.success:raise AssertionError(result.diagnostics)
        path=Path(cls.directory.name)/'main.rs';path.write_text(result.rust_source,encoding='utf-8');cls.binary=path.with_suffix('')
        built=subprocess.run(['rustc','--edition=2021',str(path),'-o',str(cls.binary)],capture_output=True,text=True,timeout=150)
        if built.returncode:raise AssertionError(built.stderr)
    def compare(self,source):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,'-I','-c',WRAPPER,source],capture_output=True,text=True,timeout=30)
        actual=subprocess.run([str(self.binary),source],capture_output=True,text=True,timeout=30)
        self.assertEqual(expected.returncode,0,expected.stderr);self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
    def test_large_float_decimal_primitive_and_inherited_slots(self):
        self.compare('''
            class Float(float):pass
            class IndexFloat(float):
                def __index__(self):raise AssertionError('native int slot precedes index')
            for number in [0.0,-0.0,1.25,-1.25,1e30,-1e30,1e100,-1e100,1.7976931348623157e308]:
                for value in [number,Float(number),IndexFloat(number)]:
                    for fmt in [b'%d',b'%i',b'%u',b'%+015.5d']:
                        print(type(value).__name__,repr(fmt%value))
            for value in [float('inf'),-float('inf'),float('nan'),Float(float('inf')),Float(float('nan'))]:
                for fmt in [b'%d',b'%i',b'%u']:
                    try:print(fmt%value)
                    except BaseException as error:print(type(error).__name__,str(error))
        ''')
    def test_custom_int_overrides_and_binary_format_owners(self):
        self.compare('''
            events=[]
            class Float(float):
                def __int__(self):events.append('int');gc.collect();return 27
            value=Float(1e100)
            class Bytes(bytes):pass
            for fmt in [b'%d',Bytes(b'%d'),bytearray(b'%d')]:
                print(type(fmt).__name__,repr(fmt%value),events);events.clear()
                print(type(fmt).__name__,repr(fmt%1e100))
            print(repr(bytes.__mod__(b'%d',value)),events)
            print(repr(bytearray.__mod__(bytearray(b'%d'),1e100)))
            print(repr(b'%(value)+d'%{b'value':1e100}))
            class Mapping:
                def __getitem__(self,key):gc.collect();return 1e100
            print(repr(b'%(value)d'%Mapping()))
        ''')
