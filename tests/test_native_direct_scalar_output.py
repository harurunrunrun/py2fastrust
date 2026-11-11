"""Builtin scalar output writes into the buffer without temporary strings."""
import shutil
import unittest

from py2fastrust import TranspileOptions, transpile
import test_native_initialized_lexical_scalars as lexical


def wrapped(body):
 return 'def factory():\n def run():\n'+''.join('  '+line+'\n' for line in body.splitlines())+' return run\nfactory()()\n'


CASES = [
 wrapped('print(0,1,-1,-9223372036854775808,9223372036854775807)'),
 wrapped('print(True,False,None,"abc","")'),
 wrapped(r'print("a\x00b", "line\nnext", "é", sep="|")'),
 wrapped('print(13,False,None,"abc",sep="|",end="!")\nprint()\nprint(7,8,sep=None,end=None)'),
 wrapped('printer=print\nprinter(13,False,None,"abc",sep="|",end="!")\nprinter()'),
 wrapped('print(13,1.5,-0.0,b"ab",[1,2],(3,4))'),
 wrapped('print("first",end="",flush=True)\nprint(2,flush=False)\nprint("last",end="!",flush=True)'),
 '''def factory():
 def value():
  print('value')
  return 3
 def run():print(value())
 return run
factory()()
''',
 wrapped('print("before")\nprint(13,sep=5)'),
 wrapped('print("before")\nprint(13,end=5)'),
]


class DirectScalarOutputProofs(unittest.TestCase):
 def test_fixed_integer_print_uses_the_existing_output_buffer(self):
  for mode in ('i64','i128'):
   result=transpile(CASES[0],TranspileOptions(integer=mode,license='none'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertEqual(result.backend,'native')
   self.assertIn('write!(&mut class_scope.io.borrow_mut().output',result.rust_source)
   self.assertNotIn('push_str(&(ClassDisplay::class_str',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class DirectScalarOutputExecution(unittest.TestCase):
 def test_scalar_printing_effects_keywords_flush_and_errors(self):
  for source in CASES:
   with self.subTest(source=source):
    lexical.InitializedScalarExecution.exercise(self,source)
