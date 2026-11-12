"""Canonical static methods use ordinary callable binding without a receiver."""
import shutil
import unittest
from py2fastrust import TranspileOptions,transpile
from tests import test_native_class_iterators as _iterators

CASES={
 'class_instance_saved':'''class C:
 @staticmethod
 def inc(value):return value+1
c=C()
f=C.inc
print(C.inc(2),c.inc(3),f(4),C.inc is c.inc,C.inc is C.inc)
''',
 'zero_arguments':'''class C:
 @staticmethod
 def answer():return 42
print(C.answer(),C().answer())
''',
 'defaults_keywords_variadic':'''class C:
 @staticmethod
 def total(x=2,/,*items,scale=3):return (x+sum(items))*scale
print(C.total(),C().total(4,5,6,scale=2))
''',
 'mutable_default_shared':'''class C:
 @staticmethod
 def collect(value,bucket=[]):
  bucket.append(value)
  return bucket
first=C.collect(2)
second=C().collect(5)
print(first,second,first is second)
''',
 'canonical_aliases':'''import builtins
sm=builtins.staticmethod
class C:
 @sm
 def f(value):return value*2
print(C.f(3),C().f(4))
''',
 'spelling_does_not_choose_descriptor':'''classmethod=staticmethod
class C:
 @classmethod
 def f(x):return x+1
print(C.f(5),C().f(6))
''',
 'decorator_before_default':'''events=[]
def decorator():
 events.append('decorator')
 return staticmethod
def default():
 events.append('default')
 return 4
class C:
 @decorator()
 def f(x=default()):return x+1
print(events,C.f(),C().f(8))
''',
 'saved_reference_and_receiver_order':'''class C:
 @staticmethod
 def f(x):return x+2
saved=C.f
def receiver():
 print('receiver')
 return C()
def argument():
 print('argument')
 return 7
print(receiver().f(argument()),saved(3))
''',
 'nested_private_static':'''class Outer:
 class Inner:
  @staticmethod
  def __f(x):return x+2
  @staticmethod
  def run(x):return Outer.Inner.__f(x)
print(Outer.Inner.run(4),Outer.Inner().run(5))
''',
 'plain_zero_argument_class_body':'''class C:
 def answer():return 9
 value=answer()
print(C.value,C.answer())
''',
 'plain_zero_argument_instance_error':'''class C:
 def answer():return 9
C().answer()
''',
 'missing_argument_effect':'''class C:
 @staticmethod
 def f(x,y):return x+y
def argument():
 print('argument')
 return 3
C.f(argument())
''',
 'duplicate_argument_effect':'''class C:
 @staticmethod
 def f(x):return x
def argument():
 print('argument')
 return 3
C().f(1,x=argument())
''',
 'static_body_error_frames':'''class C:
 @staticmethod
 def divide(x):return 9//x
def call(x):return C.divide(x)
call(0)
''',
 'classmethod_still_binds':'''class C:
 value=7
 @classmethod
 def f(cls,x):return cls.value+x
print(C.f(3),C().f(4))
'''}

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class StaticmethodTests(unittest.TestCase):
 cases=CASES
 check=_iterators.IteratorExecutionTests.check
 def test_binding_and_shared_identity(self):
  for name in ('class_instance_saved','zero_arguments','defaults_keywords_variadic','mutable_default_shared'):
   with self.subTest(name=name):self.check(name)
 def test_canonical_identity_and_definition_order(self):
  for name in ('canonical_aliases','decorator_before_default'):
   with self.subTest(name=name):self.check(name)
 def test_source_scopes_and_plain_zero_argument_functions(self):
  for name in ('nested_private_static','plain_zero_argument_class_body','classmethod_still_binds'):
   with self.subTest(name=name):self.check(name)
 def test_argument_and_receiver_effects(self):
  for name in ('saved_reference_and_receiver_order','missing_argument_effect','duplicate_argument_effect'):
   with self.subTest(name=name):self.check(name)
 def test_error_protocol(self):
  for name in ('plain_zero_argument_instance_error','static_body_error_frames'):
   with self.subTest(name=name):self.check(name)

class StaticmethodGuards(unittest.TestCase):
 def test_unproved_decorators_are_explicit(self):
  for source in (CASES['spelling_does_not_choose_descriptor'],'''def staticmethod(f):return f
class C:
 @staticmethod
 def f(x):return x+1
print(C.f(2))
''','''class C:
 @staticmethod
 @staticmethod
 def f(x):return x+1
print(C.f(2))
''','''class C:
 @staticmethod
 def f(x):return x+1
 raw=f
print(C.f(2))
'''):
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertTrue(result.diagnostics)
   self.assertTrue(any('decorator' in d.message or 'descriptor' in d.message for d in result.diagnostics))
