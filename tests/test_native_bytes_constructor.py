"""Canonical bytes count construction retains binding, errors and allocation."""
import json,os,re,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'empty_count_and_existing_bytes':"print(bytes(),bytes(0),bytes(5),bytes(False),bytes(True),bytes(b'abc'))\n",
'stored_builtin_alias':"make=bytes\nprint(make(3),make(b'abc'))\n",
'count_argument_effect':"def count():print('count');return 3\nprint(bytes(count()))\n",
'negative_count':"print('before')\nprint(bytes(-3))\n",
'negative_minimum_fixed_width':"print(bytes(-9223372036854775808))\n",
'float_source':"print(bytes(2.5))\n",
'none_source':"print(bytes(None))\n",
'string_without_encoding':"print(bytes('abc'))\n",
'source_binding_shadow':"def bytes(value):return value+2\nprint(bytes(3))\n",
}

class BytesConstructorExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_native_bytes_forms(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(BytesConstructorExecutionTests,_name,None)

class BytesConstructorOverflowTests(unittest.TestCase):
 def test_counts_beyond_native_ssize_in_wide_modes(self):
  for integer in ('i128','bigint'):
   for count in ('9223372036854775808','-9223372036854775809','-(1<<100)'):
    source='print(bytes('+count+'))\n';filename='bytes_count.py'
    cp=subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,filename],capture_output=True,text=True,timeout=10)
    failure=json.loads(cp.stderr);self.assertEqual(cp.returncode,1)
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
     result=transpile(source,TranspileOptions(integer=integer,filename=filename,license='none'))
    self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native')
    with tempfile.TemporaryDirectory(prefix='pytors-bytes-count-')as directory:
     rust=Path(directory,'main.rs');rust.write_text(result.rust_source)
     for optimized in (False,True):
      binary=Path(directory,'native');built=subprocess.run(['rustc','--edition=2021','--crate-name','bytes_count',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
      self.assertEqual(built.returncode,0,built.stderr)
      actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
      self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
      self.assertEqual(actual.stderr.splitlines()[-1],failure['message'])
      self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in failure['frames']])

class BytesConstructorGuards(unittest.TestCase):
 def test_unimplemented_bytes_conversion_is_explicit(self):
  for source,fragment in (("print(bytes('abc','utf8'))\n",'encoding'),("class Box:\n def __bytes__(self):return b'abc'\nprint(bytes(Box()))\n",'__bytes__')):
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertIn(fragment,result.diagnostics[0].message)
