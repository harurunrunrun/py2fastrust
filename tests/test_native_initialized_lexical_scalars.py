"""Presence and scalar equality are independent closure certificates."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_initialized_lexical_scalars as initialized


SAFE = '''def factory():
 value=13
 def read(x):return value+x
 return read
first=factory()
second=factory()
print(first(2),second(4),first(6),first is second)
'''

CASES = {
 'late': '''def factory():
 def read():return value
 value=13
 return read
print(factory()())
''',
 'before_store': '''def factory():
 def read():return value
 print(read())
 value=13
factory()
''',
 'conditional': '''def factory(flag):
 if flag:value=13
 def read():return value
 return read
print('before')
print(factory(False)())
''',
 'deleted': '''def factory():
 value=13
 def read():return value
 del value
 return read
print('before')
print(factory()())
''',
 'nonlocal': '''def factory():
 value=13
 def read():return value
 def change():
  nonlocal value
  value=29
 print(read())
 change()
 return read
print(factory()())
''',
 'same_value_reassigned': '''def factory():
 value=13
 def read():return value
 value=13
 return read
print(factory()())
''',
 'different_invocations': '''def factory(value):
 def read():return value
 return read
first=factory(13)
second=factory(29)
print(first(),second(),first())
''',
 'boolean': '''def factory():
 value=True
 def read():return value
 return read
print(factory()())
''',
 'descendant': '''def factory():
 value=13
 def middle():
  def read():return value+1
  return read
 return middle
print(factory()()())
''',
 'early_ancestor': '''def factory():
 def middle():
  def read():return value
  return read
 callback=middle()
 print(callback())
 value=13
factory()
''',
 'defaults': '''def factory():
 value=13
 def read(x=value):return value+x
 return read
print(factory()(),factory()(2))
''',
 'loop_store': '''def factory():
 for value in [13]:pass
 def read():return value
 return read
print(factory()())
''',
 'replaced_during_argument': '''def factory():
 value=13
 def read(x):return value+x
 return read
saved=factory()
def argument():
 global saved
 saved=factory()
 print('argument')
 return 2
print(saved(argument()))
''',
}


class InitializedScalarProofs(unittest.TestCase):
 def convert(self,source,mode='i64'):
  observed=[]
  original=initialized.Registry.__init__
  def inspect(registry,model,constants):
   before=ast.dump(model.unit.tree,include_attributes=True)
   original(registry,model,constants)
   self.assertEqual(before,ast.dump(model.unit.tree,include_attributes=True))
   observed.extend(registry.reads)
  with patch.object(initialized.Registry,'__init__',inspect):
   result=transpile(source,TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  self.assertEqual(result.backend,'native')
  return result,observed

 def test_body_capture_erasure_preserves_observed_function_identity(self):
  from py2fastrust import native_scalar_heap_constants as constants
  from py2fastrust.native_callable_carriers import registry
  models=[];original=constants.prepare
  def observe(model):
   original(model);models.append(model)
  for identity in (False,True):
   source=SAFE if identity else SAFE.replace(',first is second','')
   models.clear()
   with patch.object(constants,'prepare',observe):result=transpile(source,TranspileOptions(license='none'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertEqual(len(models),1)
   model=models[0];carrier=registry(model)
   targets=[target for target in carrier.targets.values() if type(target) is int
            and model.callable_cells.plans[target].node.name=='read']
   self.assertTrue(targets)
   for target in targets:
    self.assertEqual(bool(carrier.layout(target).fields),identity)
    plan=model.callable_cells.plans[target]
    self.assertNotRegex(result.rust_source,rf'fn class_function_{plan.index}\([^)]*class_lexical_parent')

 def test_presence_certificate_is_required_beside_a_constant_fact(self):
  for name in ('late','before_store','conditional','deleted','nonlocal',
               'same_value_reassigned','different_invocations','early_ancestor','loop_store'):
   with self.subTest(name=name):
    result,reads=self.convert(CASES[name])
    self.assertFalse(reads)

 def test_literal_store_precedes_each_closure_creation(self):
  for source in (SAFE,CASES['boolean'],CASES['descendant'],CASES['defaults'],CASES['replaced_during_argument']):
   for mode in ('i64','i128','bigint'):
    with self.subTest(source=source,mode=mode):
     result,reads=self.convert(source,mode)
     self.assertTrue(reads)
     with patch.object(initialized,'selected',return_value=False), patch.object(initialized.Registry,'refine_contexts'):
      baseline=transpile(source,TranspileOptions(integer=mode,license='none'))
     self.assertTrue(baseline.success,baseline.diagnostics)
     self.assertNotEqual(result.rust_source,baseline.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class InitializedScalarExecution(unittest.TestCase):
 def exercise(self,source):
  with tempfile.TemporaryDirectory(prefix='pytors-initialized-lexical-') as directory:
   root=Path(directory)
   main=root/'main.py';main.write_text(source)
   expected=subprocess.run([sys.executable,'-S',str(main)],text=True,capture_output=True,timeout=15)
   frames=lambda error:re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',error)
   # CPython's display-only spelling suggestion is outside exception.args.
   message=lambda error:(error.rstrip().splitlines()[-1] if error else '').partition('. Did you mean:')[0]
   for mode in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy generator entered')):
     result=transpile(source,TranspileOptions(filename=str(main),integer=mode,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    self.assertEqual(result.backend,'native')
    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     with self.subTest(integer=mode,optimized=optimized):
      binary=root/(mode+str(optimized))
      built=subprocess.run(['rustc','--edition=2021','--crate-name','initialized_lexical',*(['-O'] if optimized else []),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
      self.assertEqual(built.returncode,0,built.stderr)
      actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=15,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
      self.assertEqual((actual.stdout,actual.returncode),(expected.stdout,expected.returncode))
      self.assertEqual(frames(actual.stderr),frames(expected.stderr))
      self.assertEqual(message(actual.stderr),message(expected.stderr))

 def test_closure_values_identity_defaults_and_argument_effects(self):
  for source in (SAFE,*(CASES[name] for name in ('boolean','descendant','defaults','replaced_during_argument'))):
   with self.subTest(source=source):
    self.exercise(source)

 def test_unbound_deleted_and_reassigned_cells_keep_python_behavior(self):
  for name in ('late','before_store','conditional','deleted','nonlocal',
               'same_value_reassigned','different_invocations','early_ancestor','loop_store'):
   with self.subTest(name=name):
    self.exercise(CASES[name])
