"""Native complex additions retain double arithmetic and source operand order."""
import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as helpers

CASES={
'finite_union':'''for x in [-9.0,0.0,-0.0,16.0]:
 z=x**0.5
 print(z+3,3+z,z-2,2-z,z+True,False-z)
''',
'pair_unions':'''for x in [-9.0,4.0]:
 for y in [-16.0,25.0]:
  first=x**0.5
  second=y**0.5
  print(first+second,first-second,second-first)
''',
'nonfinite_real':'''z=(-1.0)**0.5
for x in [float('inf'),-float('inf'),float('nan'),-0.0]:
 print(z+x,x+z,z-x,x-z)
''',
'operand_order':'''events=[]
def first():
 events.append(1)
 return (-9.0)**0.5
def second():
 events.append(2)
 return 7
print(first()+second(),events)
print(second()-first(),events)
''',
'augmented_union':'''def transform(x):
 value=x**0.5
 value+=3
 value-=1
 return value
print(transform(16.0),transform(-9.0))
''',
'geometry_degree':'''def size(a,b):
 n=min(len(a),len(b))
 return int(n**0.5+1)
print(size([],[]),size([1,2,3,4],[1,2,3]),size([1]*16,[2]*16))
''',
'large_integral_rounding':'''z=(-1.0)**0.5
print(z+(2**60+3),(2**60+3)-z)
''',
}
for name,expression in {
 'none_add':'value+None','string_left':"'x'+value",'list_left':'[1]+value',
 'list_multiply':'value*[1]','bytes_left':"b'x'+value",'none_subtract':'None-value',
}.items():
 CASES[name]="value=(-1.0)**0.5\nprint('before')\nprint("+expression+")\n"

class ComplexAdditiveExecution(unittest.TestCase):
 cases=CASES
 check=helpers.IteratorExecutionTests.check
 def test_native_additive_combinations(self):
  for name in self.cases:
   with self.subTest(name=name):self.check(name)
 def test_bigint_conversion_error_occurs_after_both_operands(self):
  source='''def left():
 print('left')
 return 1<<10000
def right():
 print('right')
 return (-1.0)**0.5
print(left()+right())
'''
  with tempfile.TemporaryDirectory()as tmp:
   folder=Path(tmp);entry=folder/'main.py';entry.write_text(source)
   cp=subprocess.run([sys.executable,str(entry)],capture_output=True,timeout=10)
   result=transpile(source,TranspileOptions(integer='bigint',license='none'))
   self.assertTrue(result.success,result.diagnostics);rust=folder/'main.rs';rust.write_text(result.rust_source)
   for optimized in (False,True):
    binary=folder/str(optimized);build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,timeout=120)
    self.assertEqual(build.returncode,0,build.stderr.decode()[-2000:])
    got=subprocess.run([str(binary)],capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
    self.assertEqual((got.returncode,got.stdout),(cp.returncode,cp.stdout))
    self.assertIn(b'OverflowError:',got.stderr)

class ComplexAdditiveBoundaries(unittest.TestCase):
 def test_other_complex_arithmetic_retains_positioned_diagnostic(self):
  result=transpile('value=(-1.0)**0.5\nprint(value*2)\n',TranspileOptions(license='none'))
  self.assertFalse(result.success)
  self.assertTrue(any('complex arithmetic' in d.message and d.line==2 for d in result.diagnostics),result.diagnostics)
