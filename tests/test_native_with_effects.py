"""Implicit enter/exit source calls invalidate lazy loop-field caches."""
import shutil,unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_context_managers as support

CASES = {'exit_mutates_field_read_before_with': {'main.py': 'class Guard:\n'
                                                    ' def __init__(self):self.value=0\n'
                                                    ' def __enter__(self):pass\n'
                                                    ' def __exit__(self,a,b,c):self.value+=1\n'
                                                    ' def run(self):\n'
                                                    '  for _ in range(3):\n'
                                                    '   print(self.value)\n'
                                                    '   with self:pass\n'
                                                    '  print(self.value)\n'
                                                    'Guard().run()\n'},
 'enter_mutates_field_read_after_with': {'main.py': 'class Guard:\n'
                                                    ' def __init__(self):self.value=0\n'
                                                    ' def __enter__(self):self.value+=1\n'
                                                    ' def __exit__(self,a,b,c):pass\n'
                                                    ' def run(self):\n'
                                                    '  for _ in range(3):\n'
                                                    '   with self:pass\n'
                                                    '   print(self.value)\n'
                                                    'Guard().run()\n'},
 'aliased_manager_mutates_field_in_while': {'main.py': 'class Guard:\n'
                                                       ' def __init__(self):self.value=0\n'
                                                       ' def __enter__(self):pass\n'
                                                       ' def __exit__(self,a,b,c):self.value+=2\n'
                                                       ' def run(self):\n'
                                                       '  alias=self\n'
                                                       '  count=0\n'
                                                       '  while count<3:\n'
                                                       '   print(self.value)\n'
                                                       '   with alias:pass\n'
                                                       '   count+=1\n'
                                                       'Guard().run()\n'},
 'no_with_invariant_field_fast_path': {'main.py': 'class Box:\n'
                                                  ' def __init__(self):self.value=7\n'
                                                  ' def run(self):\n'
                                                  '  for _ in range(3):print(self.value)\n'
                                                  'Box().run()\n'}}

class WithEffectProofTests(unittest.TestCase):
    def test_no_with_loop_keeps_invariant_field_cache(self):
        for mode in ('i64','i128','bigint'):
            with self.subTest(integer=mode):
                result=transpile(CASES['no_with_invariant_field_fast_path']['main.py'],TranspileOptions(integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                self.assertIn('initialized loop field',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class WithEffectExecutionTests(unittest.TestCase):
    exercise=support.ContextManagerExecutionTests.exercise


def _execution(files):
    def test(self):self.exercise(files)
    return test


for _name,_files in CASES.items():setattr(WithEffectExecutionTests,'test_'+_name,_execution(_files))
