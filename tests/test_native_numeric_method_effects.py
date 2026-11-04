"""Builtin numeric method facts avoid unrelated iterator frame costs."""
import ast,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_constraints import analyze
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_generator_effects import may_stop

CASES={'direct_count': 'print(sum(value.bit_count()for value in range(-8,9)))\n',
 'direct_length': 'print(sum(value.bit_length()for value in range(-8,9)))\n',
 'bool_receiver': 'print(sum(value.bit_count()+value.bit_length()for value in '
                  '[False,True,True]))\n',
 'arithmetic_receiver': 'print(sum((value*value-11).bit_count()for value in '
                        'range(12)))\n',
 'source_function_numeric': 'def total(values):\n'
                            ' return '
                            'sum(value.bit_count()+value.bit_length()for value '
                            'in values)\n'
                            'print(total([-4,0,3,17]))\n',
 'transitive_numeric': 'def query(value):return value.bit_count()\n'
                       'print(sum(query(value)for value in range(20)))\n',
 'lambda_numeric': 'print(sum((lambda value:value.bit_count())(value)for value '
                   'in range(12)))\n',
 'nested_extrema': 'def score(rows):\n'
                   ' return max(max(row)-mask.bit_count()**2 for mask,row in '
                   'enumerate(rows))\n'
                   'print(score([[3,7],[9,4],[2,11]]))\n',
 'bool_int_alternatives': 'print(sum((value if value%2 else '
                          'bool(value)).bit_count()for value in range(12)))\n',
 'source_named_method': 'class Counter:\n'
                        ' def bit_count(self):return next(iter(()))\n'
                        'value=Counter()\n'
                        'print(sum(value.bit_count()for _ in range(2)))\n',
 'transitive_source_stop': 'def bit_length(value):return next(iter(()))\n'
                           'print(sum(bit_length(value)for value in '
                           'range(2)))\n'}
BOUNDARIES={'real_next_after_numeric': 'print(sum(value.bit_count()+next(iter(()))for '
                            'value in range(2)))\n',
 'none_alternative_boundary': 'value=None if int(input())else 3\n'
                              'print(sum(value.bit_count()for _ in '
                              'range(2)))\n',
 'saved_method_boundary': 'query=(7).bit_count\n'
                          'print(sum(query()for _ in range(2)))\n',
 'numeric_argument_stop_boundary': 'print(sum((1).bit_count(next(iter(())))for '
                                   '_ in range(2)))\n'}

class NumericMethodEffectProofs(unittest.TestCase):
 def test_canonical_numeric_queries_have_no_stop_effect(self):
  for name in list(CASES)[:9]:
   if name=='lambda_numeric':continue
   with self.subTest(name=name):
    unit=parse_source(CASES[name],"numeric_effect.py")
    before=ast.dump(unit.tree,include_attributes=True)
    selection=select_frames(unit)
    self.assertFalse(may_stop(unit,selection.analysis))
    self.assertNotIn("generator body StopIteration error boundary",selection.reasons)
    self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
 def test_real_cursor_and_source_method_effects_are_retained(self):
  for name in ('source_named_method','transitive_source_stop'):
   with self.subTest(name=name):
    unit=parse_source(CASES[name],"numeric_effect.py")
    self.assertTrue(may_stop(unit,analyze(unit)))
 def test_unresolved_and_protocol_boundaries_stay_explicit(self):
  for name,source in BOUNDARIES.items():
   with self.subTest(name=name):
    unit=parse_source(source,"numeric_effect.py")
    self.assertEqual(bool(may_stop(unit,analyze(unit))),name!='saved_method_boundary')
    for mode in ('i64','i128','bigint'):
     result=transpile(source,TranspileOptions(integer=mode,license='none'))
     self.assertFalse(result.success)
     self.assertTrue(result.diagnostics)
     self.assertTrue(all(d.code=='E006'for d in result.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class NumericMethodExecution(unittest.TestCase):
 def check(self,name):
  source=CASES[name]
  with tempfile.TemporaryDirectory(prefix='pytors-numeric-effect-')as directory:
   directory=Path(directory);original=directory/'main.py';original.write_text(source)
   cp=subprocess.run([sys.executable,'-I','-B','-S',str(original)],capture_output=True,text=True,timeout=10)
   frames=lambda text:re.findall(r'File "([^"\n]+)", line (\d+), in ([^\n]+)',text)
   final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else''
   for mode in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=mode,filename=str(original),license='none'))
    self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native')
    self.assertLess(len(result.rust_source.encode()),512*1024)
    self.assertNotIn('enum Op',result.rust_source)
    rust=directory/(mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=directory/(mode+('.opt'if optimized else'.debug'))
     built=subprocess.run(['rustc','--edition=2021','--crate-name','numeric_effect',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/unavailable','PYTHONPATH':'/unavailable'})
     with self.subTest(name=name,mode=mode,optimized=optimized):
      self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
      self.assertEqual(final(actual.stderr),final(cp.stderr))
      self.assertEqual(frames(actual.stderr),frames(cp.stderr))
      self.assertEqual(actual.stderr.count('The above exception was the direct cause'),cp.stderr.count('The above exception was the direct cause'))
 def test_direct_count(self):self.check('direct_count')
 def test_direct_length(self):self.check('direct_length')
 def test_bool_receiver(self):self.check('bool_receiver')
 def test_arithmetic_receiver(self):self.check('arithmetic_receiver')
 def test_source_function_numeric(self):self.check('source_function_numeric')
 def test_transitive_numeric(self):self.check('transitive_numeric')
 def test_lambda_numeric(self):self.check('lambda_numeric')
 def test_nested_extrema(self):self.check('nested_extrema')
 def test_bool_int_alternatives(self):self.check('bool_int_alternatives')
 def test_source_named_method(self):self.check('source_named_method')
 def test_transitive_source_stop(self):self.check('transitive_source_stop')
