"""Constructor tail results retain capture order, cleanup and error frames."""
from contextlib import contextmanager
import shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_tail_constructor_result import capture
from tests import test_native_class_iterators as _iterators
from tests import test_native_module_linking as _modules

CASES={'plain_identity_return': 'class Point:\n'
                          ' def __init__(self,value):self.value=value\n'
                          'def make(value):return Point(value+1)\n'
                          'p=make(7)\n'
                          'print(p.value)\n',
 'argument_and_constructor_order': 'def mark(value):\n'
                                   " print('argument',value)\n"
                                   ' return value\n'
                                   'class Point:\n'
                                   ' def __init__(self,value):\n'
                                   "  print('init',value)\n"
                                   '  self.value=value\n'
                                   'def make(value):\n'
                                   " print('caller',value)\n"
                                   ' return Point(mark(value))\n'
                                   'print(make(8).value)\n',
 'constructor_default_once': 'def default():\n'
                             " print('default')\n"
                             ' return 12\n'
                             'class Point:\n'
                             ' def __init__(self,value=default()):self.value=value\n'
                             'def make():return Point()\n'
                             'print(make().value,make().value)\n',
 'constructor_body_exception': 'class Point:\n'
                               ' def __init__(self,value):\n'
                               "  print('init')\n"
                               '  self.value=12//value\n'
                               'def make(value):return Point(value)\n'
                               'make(0)\n',
 'argument_exception_before_constructor': 'def argument():\n'
                                          " print('argument')\n"
                                          ' return 3//0\n'
                                          'class Point:\n'
                                          ' def __init__(self,value):\n'
                                          "  print('init')\n"
                                          '  self.value=value\n'
                                          'def make():return Point(argument())\n'
                                          'make()\n',
 'mutable_owner_aliases': 'class Bundle:\n'
                          ' def __init__(self,items):self.items=items\n'
                          'def make(items):return Bundle(items)\n'
                          'items=[3]\n'
                          'first=make(items)\n'
                          'first.items.append(7)\n'
                          'print(items,first.items is items)\n',
 'branch_nominal_union_declines': 'class Left:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'class Right:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'def make(value):\n'
                                  ' if value:return Left(value)\n'
                                  ' return Right(value+4)\n'
                                  'print(make(3).value,make(0).value)\n',
 'recursive_caller_declines': 'class Point:\n'
                              ' def __init__(self,value):self.value=value\n'
                              'def make(value):\n'
                              ' if value:return make(value-1)\n'
                              ' return Point(value+9)\n'
                              'print(make(6).value)\n',
 'non_tail_constructor_declines': 'class Point:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'def make(value):\n'
                                  ' point=Point(value)\n'
                                  ' point.value+=3\n'
                                  ' return point\n'
                                  'print(make(8).value)\n',
 'empty_constructor': 'class Empty:pass\n'
                      'def make():return Empty()\n'
                      'value=make()\n'
                      'print(isinstance(value,Empty))\n',
 'context_cleanup_on_success': 'class Context:\n'
                               ' def __enter__(self):\n'
                               "  print('enter')\n"
                               '  return self\n'
                               ' def __exit__(self,kind,value,trace):\n'
                               "  print('exit')\n"
                               '  return False\n'
                               'class Point:\n'
                               ' def __init__(self,value):self.value=value\n'
                               'def make(value):\n'
                               ' with Context():return Point(value)\n'
                               'print(make(8).value)\n',
 'context_cleanup_on_exception': 'class Context:\n'
                                 ' def __enter__(self):\n'
                                 "  print('enter')\n"
                                 '  return self\n'
                                 ' def __exit__(self,kind,value,trace):\n'
                                 "  print('exit')\n"
                                 '  return False\n'
                                 'class Point:\n'
                                 ' def __init__(self,value):self.value=12//value\n'
                                 'def make(value):\n'
                                 ' with Context():return Point(value)\n'
                                 'make(0)\n'}

BOUNDARIES={'finally_cleanup_on_return': 'class Point:\n'
                              ' def __init__(self,value):self.value=value\n'
                              'def make(value):\n'
                              ' try:return Point(value)\n'
                              " finally:print('finally')\n"
                              'print(make(8).value)\n',
 'binding_error_after_arguments': 'def argument():\n'
                                  " print('argument')\n"
                                  ' return 7\n'
                                  'class Point:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'def make():return Point(argument(),argument())\n'
                                  'make()\n'}

FAILED_RETRY={'main.py': 'import state\n'
            'def load(value):\n'
            ' import unstable\n'
            ' return value\n'
            'print(list(map(load,[1])))\n'
            'import unstable\n'
            'Old,OldMake=state.saved[0]\n'
            'New,NewMake=state.saved[1]\n'
            'print(OldMake().value,NewMake().value,OldMake(3).value,NewMake(4).value,Old is New)\n',
 'state.py': 'saved=[]\ncount=0\ndef keep(cls,make):saved.append((cls,make))\n',
 'unstable.py': 'import state\n'
                'state.count+=1\n'
                'seed=11*state.count\n'
                'class Point:\n'
                ' def __init__(self,value):self.value=value\n'
                'def make(value=seed):return Point(value)\n'
                'state.keep(Point,make)\n'
                'if state.count==1:next(iter([]))\n'}

class TailConstructorProofs(unittest.TestCase):
 def compile(self,name,mode,disabled=False):
  calls=[]
  @contextmanager
  def observe(emitter,node):
   with capture(emitter,node)as request:
    yield request
    if request is not None and request.code is not None:calls.append(request.code)
  with patch('py2fastrust.native_tail_constructor_result.capture',side_effect=observe):
   if disabled:
    with patch('py2fastrust.native_tail_constructor_result.register'):
     result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
   else:result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return result,calls
 def test_exact_tail_constructor_result_selected_in_every_integer_mode(self):
  for name in ('plain_identity_return','argument_and_constructor_order','empty_constructor'):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.compile(name,mode)
     self.assertTrue(calls)
     self.assertTrue(all('class_sync_call('in code for code in calls))
     self.assertTrue(all('.await'not in code for code in calls))
 def test_non_tail_union_recursion_and_context_controls_keep_original_code(self):
  for name in ('branch_nominal_union_declines','recursive_caller_declines','non_tail_constructor_declines','context_cleanup_on_success','context_cleanup_on_exception'):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.compile(name,mode)
     baseline,_=self.compile(name,mode,disabled=True)
     self.assertFalse(calls)
     self.assertEqual(result.rust_source,baseline.rust_source)
 def test_existing_unimplemented_boundaries_keep_positioned_diagnostics(self):
  for name,source in BOUNDARIES.items():
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result=transpile(source,TranspileOptions(integer=mode,license='none'))
     with patch('py2fastrust.native_tail_constructor_result.register'):
      baseline=transpile(source,TranspileOptions(integer=mode,license='none'))
     self.assertFalse(result.success)
     self.assertEqual(result.diagnostics,baseline.diagnostics)
     self.assertTrue(all(d.code=='E006'and d.line>=1 and d.column>=1 for d in result.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class TailConstructorExecution(unittest.TestCase):
 cases=CASES
 check=_iterators.IteratorExecutionTests.check
 def test_order_and_defaults(self):
  for name in ('plain_identity_return','argument_and_constructor_order','constructor_default_once'):
   with self.subTest(name=name):self.check(name)
 def test_original_exception_frames(self):
  for name in ('constructor_body_exception','argument_exception_before_constructor'):
   with self.subTest(name=name):self.check(name)
 def test_boxed_alias_and_linked_empty_class_capture(self):
  for name in ('mutable_owner_aliases','empty_constructor'):
   with self.subTest(name=name):self.check(name)
 def test_cleanup_control(self):
  for name in ('context_cleanup_on_success','context_cleanup_on_exception'):
   with self.subTest(name=name):self.check(name)
 def test_failed_import_constructor_context_and_defaults(self):
  _modules.NativeLinkedModuleTests.exercise(self,FAILED_RETRY)
