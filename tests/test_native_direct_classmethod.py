"""Exact immediate classmethods avoid constructing a retained callable carrier."""
import shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_immediate_classmethod import direct_payload
from tests import test_native_class_iterators as _iterators
from tests import test_native_module_linking as _modules

CASES={'default_and_keywords': 'class Holder:\n'
                         ' def __init__(self,value):self.value=value\n'
                         ' @classmethod\n'
                         ' def read(cls,amount=3,*,extra=4):return amount+extra\n'
                         'h=Holder(9)\n'
                         'print(Holder.read(),Holder.read(5,extra=8))\n',
 'receiver_and_argument_order': 'def mark(label,value):\n'
                                ' print(label)\n'
                                ' return value\n'
                                'class Holder:\n'
                                ' def __init__(self,value):self.value=value\n'
                                ' @classmethod\n'
                                ' def read(cls,amount=3):return amount+1\n'
                                'def choose():\n'
                                " print('receiver')\n"
                                ' return Holder\n'
                                'h=Holder(9)\n'
                                "print(choose().read(mark('argument',7)))\n",
 'definition_defaults_once': 'def mark(label,value):\n'
                             ' print(label)\n'
                             ' return value\n'
                             'class Holder:\n'
                             ' def __init__(self,value):self.value=value\n'
                             ' @classmethod\n'
                             " def read(cls,amount=mark('default',3)):return amount+1\n"
                             'h=Holder(9)\n'
                             'print(Holder.read(),Holder.read(8),Holder.read())\n',
 'body_exception_frames': 'class Holder:\n'
                          ' def __init__(self,value):self.value=value\n'
                          ' @classmethod\n'
                          ' def divide(cls,value):return 9//value\n'
                          'def call(value):return Holder.divide(value)\n'
                          'h=Holder(9)\n'
                          'call(0)\n',
 'retained_methods_keep_identity': 'class Holder:\n'
                                   ' def __init__(self,value):self.value=value\n'
                                   ' @classmethod\n'
                                   ' def read(cls,amount=3):return amount+11\n'
                                   'h=Holder(1)\n'
                                   'first=Holder.read\n'
                                   'second=Holder.read\n'
                                   'print(first is first,first is '
                                   'second,first(5),Holder.read(7))\n',
 'instance_classmethod': 'class Holder:\n'
                         ' def __init__(self,value):self.value=value\n'
                         ' @classmethod\n'
                         ' def read(cls,amount=3):return amount+11\n'
                         'h=Holder(1)\n'
                         'print(h.read(5),Holder.read(7))\n',
 'mutable_default': 'class Holder:\n'
                    ' def __init__(self,value):self.value=value\n'
                    ' @classmethod\n'
                    ' def collect(cls,value,bucket=[]):\n'
                    '  bucket.append(value)\n'
                    '  return len(bucket)\n'
                    'h=Holder(1)\n'
                    'print(Holder.collect(4),Holder.collect(7),Holder.collect(9))\n',
 'recursive_classmethod_declines_direct_mode': 'class Holder:\n'
                                               ' def __init__(self,value):self.value=value\n'
                                               ' @classmethod\n'
                                               ' def total(cls,n):\n'
                                               '  if n:return n+cls.total(n-1)\n'
                                               '  return 0\n'
                                               'h=Holder(1)\n'
                                               'print(Holder.total(6))\n',
 'retained_only': 'class Sample:\n'
                  ' def __init__(self,x):self.x=x\n'
                  ' @classmethod\n'
                  ' def read(cls,x=3):return x+4\n'
                  'value=Sample(2)\n'
                  'saved=Sample.read\n'
                  'print(saved(8),saved is saved)\n',
 'list_owner_declines': 'class Sample:\n'
                        ' def __init__(self,x):self.values=[x]\n'
                        ' @classmethod\n'
                        ' def read(cls,x=3):return x+4\n'
                        'value=Sample(2)\n'
                        'print(Sample.read(8),value.values)\n',
 'missing_argument_after_effect': 'def argument():\n'
                                  " print('argument')\n"
                                  ' return 7\n'
                                  'class Sample:\n'
                                  ' def __init__(self,x):self.x=x\n'
                                  ' @classmethod\n'
                                  ' def read(cls,x,y):return x+y\n'
                                  'value=Sample(2)\n'
                                  'Sample.read(argument())\n',
 'duplicate_argument_after_effect': 'def argument():\n'
                                    " print('argument')\n"
                                    ' return 7\n'
                                    'class Sample:\n'
                                    ' def __init__(self,x):self.x=x\n'
                                    ' @classmethod\n'
                                    ' def read(cls,x):return x\n'
                                    'value=Sample(2)\n'
                                    'Sample.read(3,x=argument())\n',
 'variadic_positional_keyword_defaults': 'class Sample:\n'
                                         ' def __init__(self,x):self.x=x\n'
                                         ' @classmethod\n'
                                         ' def read(cls,*items,scale=2):return sum(items)*scale\n'
                                         'value=Sample(2)\n'
                                         'print(Sample.read(),Sample.read(3,4),Sample.read(3,4,scale=5))\n'}

CASES['boolean_layout_integer_arguments']=('class Check:\n'
 ' def __init__(self,flag):self.flag=flag\n'
 ' @classmethod\n'
 ' def squared(cls,value=3):return value*value+2\n'
 'check=Check(True)\n'
 'print(Check.squared(),Check.squared(17),check.flag)\n')

FAILED_RETRY={'main.py': 'import state\n'
            'def load(value):\n'
            ' import unstable\n'
            ' return value\n'
            'print(list(map(load,[1])))\n'
            'import unstable\n'
            'Old,New=state.saved\n'
            'a,b=Old(),New()\n'
            'print(Old.read(),New.read(),Old.read(3),New.read(3),a.read(),b.read(),Old is New)\n',
 'state.py': 'saved=[]\ncount=0\ndef keep(value):saved.append(value)\n',
 'unstable.py': 'import state\n'
                'state.count+=1\n'
                'seed=11*state.count\n'
                'class Holder:\n'
                ' def __init__(self):self.value=seed\n'
                ' @classmethod\n'
                ' def read(cls,amount=seed):return seed+amount\n'
                'state.keep(Holder)\n'
                'if state.count==1:next(iter([]))\n'}

class DirectClassMethodProofs(unittest.TestCase):
 def convert(self,name,mode,disabled=False):
  calls=[]
  def observe(emitter,node,reference,member):
   result=None if disabled else direct_payload(emitter,node,reference,member)
   if result is not None:calls.append(result.code)
   return result
  with patch('py2fastrust.native_immediate_classmethod.direct_payload',side_effect=observe):
   result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return result,calls
 def test_exact_class_reference_captures_generation_without_function_enum(self):
  for name in ('default_and_keywords','receiver_and_argument_order','definition_defaults_once','mutable_default'):
   for mode in ('i64','i128'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.convert(name,mode)
     self.assertTrue(calls)
     self.assertIn('class_selected_method.0',result.rust_source)
     for code in calls:
      self.assertIn('.module.clone()',code)
      self.assertNotIn('ClassFunctionRef',code)
      self.assertNotIn('ClassBoundMethod',code)
      self.assertNotIn('.borrow()',code)
 def test_copy_owner_selects_direct_calls_in_every_integer_mode(self):
  for mode in ('i64','i128','bigint'):
   with self.subTest(mode=mode):
    result,calls=self.convert('boolean_layout_integer_arguments',mode)
    self.assertTrue(calls)
    self.assertIn('class_selected_method.0',result.rust_source)
 def test_retained_unproved_layout_and_recursive_calls_keep_native_path(self):
  for name in ('retained_only','list_owner_declines','recursive_classmethod_declines_direct_mode'):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.convert(name,mode)
     baseline,_=self.convert(name,mode,disabled=True)
     self.assertFalse(calls)
     self.assertEqual(result.rust_source,baseline.rust_source)

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class DirectClassMethodExecution(unittest.TestCase):
 cases=CASES
 check=_iterators.IteratorExecutionTests.check
 def test_receiver_default_and_argument_order(self):
  for name in ('default_and_keywords','receiver_and_argument_order','definition_defaults_once'):
   with self.subTest(name=name):self.check(name)
 def test_binding_and_body_errors(self):
  for name in ('missing_argument_after_effect','duplicate_argument_after_effect','body_exception_frames'):
   with self.subTest(name=name):self.check(name)
 def test_retained_and_instance_identity(self):
  for name in ('retained_methods_keep_identity','instance_classmethod','retained_only'):
   with self.subTest(name=name):self.check(name)
 def test_defaults_variadic_and_unproved_paths(self):
  for name in ('mutable_default','variadic_positional_keyword_defaults','list_owner_declines','recursive_classmethod_declines_direct_mode'):
   with self.subTest(name=name):self.check(name)
 def test_integer_arguments_with_copy_owner(self):
  self.check('boolean_layout_integer_arguments')
 def test_failed_generation_preserves_original_class_defaults(self):
  _modules.NativeLinkedModuleTests.exercise(self,FAILED_RETRY)
