"""Immutable callable binding construction preserves owner, defaults and lookup."""
import shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_immutable_class_functions import emit
import test_native_class_iterators as iterator_tests

CASES={'plain_alias_and_defaults': 'class Score:\n'
                             '    def __init__(self, value=0):\n'
                             '        self.value = value\n'
                             '    def read(self, bonus=3):\n'
                             '        return self.value + bonus\n'
                             '    def __add__(self, other):\n'
                             '        return Score(self.value + other.value)\n'
                             'Alias = Score\n'
                             'read = Alias.read\n'
                             'first = Alias(7)\n'
                             'second = first + Alias(11)\n'
                             'print(read(first), read(second, 5), Alias.read(first, 0))\n',
 'classmethod_scalar_factory': 'events = []\n'
                               'def default_value():\n'
                               '    events.append(5)\n'
                               '    return 9\n'
                               'class Number:\n'
                               '    base = 13\n'
                               '    def __init__(self, value=0):\n'
                               '        self.value = value\n'
                               '    @classmethod\n'
                               '    def make(cls, value=default_value()):\n'
                               '        result = cls()\n'
                               '        result.value = value + cls.base\n'
                               '        return result\n'
                               '    def read(self):\n'
                               '        return self.value\n'
                               'Alias = Number\n'
                               'print(events, Alias.make().read(), Alias.make(4).read(), events)\n',
 'class_body_delete_then_restore': 'class Item:\n'
                                   '    def __init__(self, value):\n'
                                   '        self.value = value\n'
                                   '    def read(self):\n'
                                   '        return self.value + 1\n'
                                   '    original = read\n'
                                   '    del read\n'
                                   '    read = original\n'
                                   'value = Item(6)\n'
                                   'print(Item.read(value), value.read())\n',
 'plain_function_identity': 'class Measure:\n'
                            '    def __init__(self, value):\n'
                            '        self.value = value\n'
                            '    def read(self):\n'
                            '        return self.value\n'
                            'first = Measure.read\n'
                            'second = Measure.read\n'
                            'print(first is second, first == second, first(Measure(9)))\n',
 'classmethod_bound_identity': 'class Measure:\n'
                               '    def __init__(self, value):\n'
                               '        self.value = value\n'
                               '    @classmethod\n'
                               '    def make(cls, value):\n'
                               '        return cls(value)\n'
                               'first = Measure.make\n'
                               'second = Measure.make\n'
                               'print(first is second, first == second, first(9).value)\n',
 'mutable_default_alias': 'defaults = [3]\n'
                          'class Digit:\n'
                          '    def __init__(self, value):\n'
                          '        self.value = value\n'
                          '    def read(self, extra=defaults):\n'
                          '        return self.value + extra[0]\n'
                          'value = Digit(8)\n'
                          'print(Digit.read(value))\n'
                          'defaults[0] = 19\n'
                          'print(Digit.read(value), value.read())\n',
 'effectful_class_receiver': 'events = []\n'
                             'class Number:\n'
                             '    def __init__(self, value):\n'
                             '        self.value = value\n'
                             '    @classmethod\n'
                             '    def make(cls, value):\n'
                             '        return cls(value + 2)\n'
                             'def choose():\n'
                             '    events.append(7)\n'
                             '    return Number\n'
                             'print(choose().make(9).value, events)\n',
 'class_body_store_same_function': 'class Entry:\n'
                                   '    def __init__(self, value):\n'
                                   '        self.value = value\n'
                                   '    def read(self):\n'
                                   '        return self.value\n'
                                   '    read = read\n'
                                   'value = Entry(7)\n'
                                   'print(Entry.read(value), value.read())\n'}
BOUNDARIES={'class_namespace_replacement': 'class Item:\n'
                                '    def __init__(self, value):\n'
                                '        self.value = value\n'
                                '    def read(self):\n'
                                '        return self.value + 1\n'
                                'def replacement(self):\n'
                                '    return self.value + 20\n'
                                'old = Item.read\n'
                                'first = Item(4)\n'
                                'Item.read = replacement\n'
                                'print(old(first), Item.read(first), first.read())\n',
 'class_body_duplicate_definition': 'class Digit:\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value = value\n'
                                    '    def read(self):\n'
                                    '        return self.value + 1\n'
                                    '    old = read\n'
                                    '    def read(self):\n'
                                    '        return self.value + 10\n'
                                    'value = Digit(8)\n'
                                    'print(Digit.old(value), Digit.read(value), value.read())\n',
 'class_body_conditional_replacement': 'def replacement(self):\n'
                                       '    return self.value + 17\n'
                                       'class Digit:\n'
                                       '    def __init__(self, value):\n'
                                       '        self.value = value\n'
                                       '    def read(self):\n'
                                       '        return self.value + 1\n'
                                       '    if int(input()):\n'
                                       '        read = replacement\n'
                                       'value = Digit(8)\n'
                                       'print(Digit.read(value), value.read())\n',
 'method_metadata_changed': 'class Score:\n'
                            '    def __init__(self, value):\n'
                            '        self.value = value\n'
                            '    def read(self, bonus=3):\n'
                            '        return self.value + bonus\n'
                            'Score.read.__defaults__ = (19,)\n'
                            'print(Score.read(Score(4)))\n',
 'missing_after_delete': 'class Entry:\n'
                         '    def __init__(self, value):\n'
                         '        self.value = value\n'
                         '    def read(self):\n'
                         '        return self.value\n'
                         'value = Entry(7)\n'
                         'del Entry.read\n'
                         'print(Entry.read(value))\n',
 'class_binding_rebound_old_alias': 'class Token:\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value = value\n'
                                    '    @classmethod\n'
                                    '    def make(cls, value):\n'
                                    '        return cls(value + 1)\n'
                                    '    def read(self):\n'
                                    '        return self.value\n'
                                    'Old = Token\n'
                                    'old_make = Old.make\n'
                                    'class Token:\n'
                                    '    def __init__(self, value):\n'
                                    '        self.value = value\n'
                                    '    @classmethod\n'
                                    '    def make(cls, value):\n'
                                    '        return cls(value + 30)\n'
                                    '    def read(self):\n'
                                    '        return self.value\n'
                                    'print(Old.make(2).read(), Token.make(2).read(), '
                                    'old_make(2).read())\n',
 'decorated_replacement': 'def wrap(function):\n'
                          '    def replacement(self):\n'
                          '        return function(self) + 10\n'
                          '    return replacement\n'
                          'class Count:\n'
                          '    def __init__(self, value):\n'
                          '        self.value = value\n'
                          '    @wrap\n'
                          '    def read(self):\n'
                          '        return self.value\n'
                          'value = Count(6)\n'
                          'print(Count.read(value), value.read())\n'}

BOUNDARIES['private_method_binding']='class Number:\n    def __init__(self, value):\n        self.value = value\n    def __read(self, extra=3):\n        return self.value + extra\n    @classmethod\n    def build(cls, value):\n        return cls(value)\nprint(Number._Number__read(Number.build(7)), Number.build(11)._Number__read())\n'

class ImmutableClassFunctionProofs(unittest.TestCase):
 def compile(self,name,mode='i64',disabled=False):
  calls=[]
  def observe(registry,emitter,node,reference,member,stored):
   result=None if disabled else emit(registry,emitter,node,reference,member,stored)
   if result is not None:calls.append((member.name,result.code))
   return result
  # Exercise the callable-reference adapter independently of direct calls.
  with patch('py2fastrust.native_immediate_classmethod.direct_payload',return_value=None),patch('py2fastrust.native_immutable_class_functions.emit',side_effect=observe):
   result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return result,calls
 def test_exact_plain_and_classmethod_bindings_use_actual_class_module(self):
  for name in ('plain_alias_and_defaults','classmethod_scalar_factory','mutable_default_alias','effectful_class_receiver'):
   for mode in ('i64','i128'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.compile(name,mode)
     self.assertTrue(calls)
     for member,code in calls:
      self.assertIn('ClassCallablePayload_F',code)
      self.assertNotIn('ClassFunctionRef',code)
      self.assertIn('.module.clone()',code)
      self.assertNotIn('.borrow()',code)
      self.assertNotIn('class_scope.globals',code)
 def test_class_body_rebindings_keep_existing_namespace_lookup(self):
  for name in ('class_body_delete_then_restore','class_body_store_same_function'):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,calls=self.compile(name,mode)
     baseline,_=self.compile(name,mode,disabled=True)
     self.assertFalse(calls)
     self.assertEqual(result.rust_source,baseline.rust_source)
 def test_noncopy_value_layout_keeps_existing_namespace_lookup(self):
  for name in ('plain_alias_and_defaults','classmethod_scalar_factory'):
   result,calls=self.compile(name,'bigint')
   baseline,_=self.compile(name,'bigint',disabled=True)
   self.assertFalse(calls)
   self.assertEqual(result.rust_source,baseline.rust_source)
 def test_unsupported_mutations_and_replacements_keep_exact_diagnostics(self):
  for name,source in BOUNDARIES.items():
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result=transpile(source,TranspileOptions(integer=mode,license='none'))
     with patch('py2fastrust.native_immutable_class_functions.emit',return_value=None):
      baseline=transpile(source,TranspileOptions(integer=mode,license='none'))
     self.assertFalse(result.success)
     self.assertEqual(result.diagnostics,baseline.diagnostics)
     self.assertTrue(all(d.code=='E006'for d in result.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ImmutableClassFunctionExecution(unittest.TestCase):
 cases=CASES
 check=iterator_tests.IteratorExecutionTests.check
 def test_plain_alias_and_defaults(self):self.check('plain_alias_and_defaults')
 def test_classmethod_scalar_factory(self):self.check('classmethod_scalar_factory')
 def test_class_body_delete_then_restore(self):self.check('class_body_delete_then_restore')
 def test_plain_function_identity(self):self.check('plain_function_identity')
 def test_classmethod_bound_identity(self):self.check('classmethod_bound_identity')
 def test_mutable_default_alias(self):self.check('mutable_default_alias')
 def test_effectful_class_receiver(self):self.check('effectful_class_receiver')
 def test_class_body_store_same_function(self):self.check('class_body_store_same_function')

FAILED_RETRY={'main.py': 'import state\n'
            '\n'
            'def load(value):\n'
            '    import unstable\n'
            '    return value\n'
            '\n'
            'print(list(map(load, [1])))\n'
            'import unstable\n'
            'Old, New = state.saved\n'
            'print(Old.read(Old()), New.read(New()))\n'
            'print(Old.make().value, New.make().value)\n',
 'state.py': 'saved = []\ncount = 0\n\ndef keep(value):\n    saved.append(value)\n',
 'unstable.py': 'import state\n'
                '\n'
                'state.count += 1\n'
                'seed = 11 * state.count\n'
                '\n'
                'class Box:\n'
                '    def __init__(self, value=0):\n'
                '        self.value = value\n'
                '    def read(self, amount=seed):\n'
                '        return self.value + seed + amount\n'
                '    @classmethod\n'
                '    def make(cls, value=seed):\n'
                '        return cls(value)\n'
                '\n'
                'state.keep(Box)\n'
                'if state.count == 1:\n'
                '    next(iter([]))\n'}

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ImmutableClassFunctionLinkedExecution(unittest.TestCase):
 def test_failed_import_old_and_new_class_method_defaults(self):
  from tests import test_native_module_linking as support
  support.NativeLinkedModuleTests.exercise(self,FAILED_RETRY)
