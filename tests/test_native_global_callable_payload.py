"""Global callable snapshots retain actual environment, defaults and module."""
from pathlib import Path
import shutil,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_global_callable_payload import read
from tests import test_native_module_linking as _modules

PROJECTS={'binding_error_after_argument': {'helpers.py': 'def calc(value):return value+1\n',
                                  'main.py': 'from helpers import calc\n'
                                             'def argument():\n'
                                             " print('argument')\n"
                                             ' return 7\n'
                                             'calc(argument(),argument())\n'},
 'body_exception_frames': {'helpers.py': 'def calc(value):return 19//value\n',
                           'main.py': 'from helpers import calc\n'
                                      'def run(value):return calc(value)\n'
                                      'print("before")\n'
                                      'run(0)\n'},
 'deleted_global_before_argument': {'helpers.py': 'def calc(value):return value+1\n',
                                    'main.py': 'from helpers import calc\n'
                                               'del calc\n'
                                               'def argument():\n'
                                               " print('argument')\n"
                                               ' return 7\n'
                                               'calc(argument())\n'},
 'failed_module_generation_aliases': {'main.py': 'import state\n'
                                                 'def load(value):\n'
                                                 ' import unstable\n'
                                                 ' return value\n'
                                                 'print(list(map(load,[1])))\n'
                                                 'import unstable\n'
                                                 'old,new=state.saved\n'
                                                 'saved=old\n'
                                                 'def replace():\n'
                                                 ' global old\n'
                                                 ' old=new\n'
                                                 " print('replace')\n"
                                                 ' return 3\n'
                                                 'print(old(),new(),old(replace()),old(),saved(),saved '
                                                 'is new)\n',
                                      'state.py': 'saved=[]\n'
                                                  'count=0\n'
                                                  'def keep(value):saved.append(value)\n',
                                      'unstable.py': 'import state\n'
                                                     'state.count+=1\n'
                                                     'seed=11*state.count\n'
                                                     'def calc(value=seed):return seed+value\n'
                                                     'state.keep(calc)\n'
                                                     'if state.count==1:next(iter([]))\n'},
 'finite_binding_family': {'helpers.py': 'def first(value):return value+1\n'
                                         'def second(value):return value*3\n',
                           'main.py': 'from helpers import first,second\n'
                                      'flag=int(input())\n'
                                      'if flag:current=first\n'
                                      'else:current=second\n'
                                      'print(current(7))\n'},
 'function_metadata_boundary': {'helpers.py': 'def calc(value=3):return value+1\n',
                                'main.py': 'from helpers import calc\n'
                                           'calc.__defaults__=(20,)\n'
                                           'print(calc())\n'},
 'global_closure_rebinding': {'helpers.py': 'def factory(offset):\n'
                                            ' def calc(value=offset):return offset+value\n'
                                            ' return calc\n',
                              'main.py': 'from helpers import factory\n'
                                         'current=factory(10)\n'
                                         'def replace():\n'
                                         ' global current\n'
                                         ' current=factory(20)\n'
                                         " print('replace')\n"
                                         ' return 3\n'
                                         'print(current(replace()),current())\n'},
 'global_lambda_instances': {'helpers.py': 'def factory(offset):return lambda '
                                           'value=offset:offset+value\n',
                             'main.py': 'from helpers import factory\n'
                                        'current=factory(5)\n'
                                        'saved=current\n'
                                        'def replace():\n'
                                        ' global current\n'
                                        ' current=factory(9)\n'
                                        ' return 1\n'
                                        'print(current(replace()),saved(),current(),saved is '
                                        'current,saved is saved)\n'},
 'keyword_binding_error_after_argument': {'helpers.py': 'def calc(value):return value+1\n',
                                          'main.py': 'from helpers import calc\n'
                                                     'def argument():\n'
                                                     " print('keyword')\n"
                                                     ' return 7\n'
                                                     'calc(3,value=argument())\n'},
 'local_parameter_not_global': {'helpers.py': 'def calc(value):return value+1\n'
                                              'def run(function,value):return function(value)\n',
                                'main.py': 'from helpers import calc,run\nprint(run(calc,7))\n'},
 'missing_global_before_argument': {'main.py': 'from effects import argument\n'
                                               'def run():return later(argument())\n'
                                               'run()\n'
                                               'def later(value):return value+1\n',
                                    'effects.py': 'def argument():\n'
                                                  ' print("argument")\n'
                                                  ' return 7\n'},
 'mutable_default_argument_effect': {'helpers.py': 'def factory():\n'
                                                   ' def calc(value,bucket=[]):\n'
                                                   '  bucket.append(value)\n'
                                                   '  return len(bucket)\n'
                                                   ' return calc\n',
                                     'main.py': 'from helpers import factory\n'
                                                'calc=factory()\n'
                                                'saved=calc\n'
                                                'def argument():\n'
                                                " print('before',saved(7))\n"
                                                ' return 9\n'
                                                'print(calc(argument()),saved(11),calc is '
                                                'saved)\n'},
 'plain_import_and_defaults': {'helpers.py': 'offset=11\n'
                                             'def calc(value=3,*,extra=4):return '
                                             'offset+value+extra\n',
                               'main.py': 'from helpers import calc\n'
                                          'print(calc(),calc(5,extra=8))\n'},
 'recursive_callable_declines': {'helpers.py': 'def total(value):\n'
                                               ' if value:return value+total(value-1)\n'
                                               ' return 0\n',
                                 'main.py': 'from helpers import total\n'
                                            'saved=total\n'
                                            'print(saved(6))\n'},
 'retained_alias_identity': {'helpers.py': 'def calc(value=3):return value+11\n',
                             'main.py': 'from helpers import calc\n'
                                        'saved=calc\n'
                                        'print(saved is calc,saved is saved,calc(2),saved())\n'},
 'shared_nonlocal_argument_update': {'helpers.py': 'def factory(offset):\n'
                                                   ' def calc(value=1):return offset+value\n'
                                                   ' def change():\n'
                                                   '  nonlocal offset\n'
                                                   '  offset+=5\n'
                                                   '  return 3\n'
                                                   ' return calc,change\n',
                                     'main.py': 'from helpers import factory\n'
                                                'calc,change=factory(10)\n'
                                                'print(calc(change()),calc())\n'},
 'repeated_definition': {'helpers.py': 'def factory():\n'
                                       ' result=[]\n'
                                       ' for value in range(3):\n'
                                       '  def calc(ignored=0,x=value):return ignored+x\n'
                                       '  result.append(calc)\n'
                                       ' return result\n',
                         'main.py': 'from helpers import factory\n'
                                    'first,second,third=factory()\n'
                                    'current=first\n'
                                    'def change():\n'
                                    ' global current\n'
                                    ' current=third\n'
                                    " print('argument')\n"
                                    ' return 3\n'
                                    'print(current(change()),current(),first(),second(),third(),first '
                                    'is second)\n'},
 'builtin_shadow_fallback': {'helpers.py': 'value=11\n',
                             'main.py': 'import helpers\n'
                                        'saved=int\n'
                                        'def int(value=3):return value+helpers.value\n'
                                        'print(int(4))\n'
                                        'del int\n'
                                        "print(int('7'),saved('9'))\n"},
 'ordinary_function_field': {'helpers.py': 'def calc(value):return value+11\n',
                             'main.py': 'from helpers import calc\n'
                                        'class Holder:\n'
                                        ' def __init__(self,function):self.function=function\n'
                                        'holder=Holder(calc)\n'
                                        'saved=holder.function\n'
                                        'print(holder.function(3),saved is '
                                        'holder.function,saved(5))\n'}}

class GlobalPayloadProofs(unittest.TestCase):
 def compile_pair(self,name,mode):
  calls=[]
  def observe(emitter,node,wanted):
   result=read(emitter,node,wanted)
   if result is not None:
    request=emitter.global_callable_request
    calls.append((request.name,request.layout.environment_type))
   return result
  with tempfile.TemporaryDirectory(prefix='pytors-global-payload-')as directory:
   root=Path(directory)
   for filename,source in PROJECTS[name].items():(root/filename).write_text(source)
   main=root/'main.py';options=TranspileOptions(filename=str(main),integer=mode,license='none')
   with patch('py2fastrust.native_global_callable_payload.read',side_effect=observe):
    result=transpile(main.read_text(),options)
   with patch('py2fastrust.native_global_callable_payload.read',return_value=None):
    baseline=transpile(main.read_text(),options)
  return result,baseline,calls
 def test_actual_closure_lambda_and_repeated_definition_payloads(self):
  for name,environment in (('global_closure_rebinding','ClassLexicalEnvironment'),('global_lambda_instances','ClassLambdaInstance'),('repeated_definition','ClassFunctionInstanceRef')):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,baseline,calls=self.compile_pair(name,mode)
     self.assertTrue(result.success,result.diagnostics)
     self.assertTrue(any(environment in (kind or '')for _,kind in calls))
     self.assertNotEqual(result.rust_source,baseline.rust_source)
 def test_unproved_and_non_global_values_keep_existing_native_code(self):
  for name in ('finite_binding_family','recursive_callable_declines','ordinary_function_field','builtin_shadow_fallback','plain_import_and_defaults','retained_alias_identity'):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,baseline,calls=self.compile_pair(name,mode)
     self.assertTrue(result.success,result.diagnostics)
     self.assertFalse(calls)
     self.assertEqual(result.rust_source,baseline.rust_source)
 def test_uninitialized_global_lookup_keeps_its_checked_capture(self):
  for mode in ('i64','i128','bigint'):
   result,baseline,calls=self.compile_pair('missing_global_before_argument',mode)
   self.assertTrue(result.success,result.diagnostics)
   self.assertTrue(any(name.endswith('later')for name,_ in calls))
 def test_observed_mutable_function_metadata_keeps_positioned_diagnostic(self):
  for mode in ('i64','i128','bigint'):
   result,baseline,calls=self.compile_pair('function_metadata_boundary',mode)
   self.assertFalse(result.success)
   self.assertEqual(result.diagnostics,baseline.diagnostics)
   self.assertTrue(all(d.code=='E006'and d.line>0 and d.column>0 for d in result.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class GlobalPayloadExecution(unittest.TestCase):
 def exercise(self,name):_modules.NativeLinkedModuleTests.exercise(self,PROJECTS[name])
 def test_actual_environment_rebinding_and_defaults(self):
  for name in ('global_closure_rebinding','global_lambda_instances','repeated_definition','mutable_default_argument_effect'):
   with self.subTest(name=name):self.exercise(name)
 def test_shared_nonlocal_updates_and_first_class_aliases(self):
  for name in ('shared_nonlocal_argument_update','retained_alias_identity','ordinary_function_field'):
   with self.subTest(name=name):self.exercise(name)
 def test_lookup_binding_and_body_error_order(self):
  for name in ('deleted_global_before_argument','binding_error_after_argument','keyword_binding_error_after_argument','body_exception_frames'):
   with self.subTest(name=name):self.exercise(name)
 def test_actual_failed_module_generations(self):self.exercise('failed_module_generation_aliases')
 def test_other_native_callable_paths_remain_available(self):
  for name in ('plain_import_and_defaults','recursive_callable_declines','local_parameter_not_global','builtin_shadow_fallback'):
   with self.subTest(name=name):self.exercise(name)
