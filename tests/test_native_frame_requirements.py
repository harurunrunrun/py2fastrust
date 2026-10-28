"""Canonical frame requirements include module writes and definition captures."""
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
from tests import test_native_heapq as _heap


CASES={
 'counter':('''COUNT=0
def tick(amount):
 global COUNT
 COUNT+=amount
 return COUNT
def read():return COUNT
print(tick(int(input())),read(),COUNT)
COUNT=7
print(read(),tick(2),COUNT)
''',('0\n','5\n','-3\n')),
 'binding_replacement':('''VALUE=[1]
saved=VALUE
def replace():
 global VALUE
 VALUE.append(2)
 VALUE=[7]
 VALUE.append(9)
def read():return VALUE
print(read())
replace()
print(read(),VALUE,saved,VALUE is saved)
''',('',)),
 'delete':('''VALUE=3
def read():return VALUE
def erase():
 global VALUE
 del VALUE
print(read())
erase()
print(read())
''',('',)),
 'branch_rebinding':('''VALUE=3
def change(selected):
 global VALUE
 if selected:VALUE='changed'
 else:VALUE=None
def read():return VALUE
print(read())
change(int(input()))
print(read(),VALUE)
''',('0\n','1\n')),
 'comprehension_write':('''COUNT=0
def advance(count):
 global COUNT
 return [(COUNT:=COUNT+1)for unused in range(count)]
print(advance(int(input())),COUNT)
''',('0\n','4\n')),
 'captured_default':('''VALUE=3
def read(value=VALUE):return value
VALUE=8
print(read(),read(9),VALUE)
''',('',)),
 'mutable_default':('''def collect(value,items=[]):
 items.append(value)
 return items
a=collect(3)
b=collect(5)
print(a,b,a is b)
''',('',)),
 'keyword_default':('''def collect(value,*,items=[]):
 items.append(value)
 return items
print(collect(2),collect(4),collect(6,items=[9]))
''',('',)),
 'effectful_default':('''def mark(value):
 print('default',value)
 return [value]
def take(items=mark(3)):
 items.append(4)
 return items
print('defined')
print(take(),take())
''',('',)),
 'unused_default':('''def unused(value=int(input())):return value
print('ready')
''',('3\n','bad\n','')),
 'default_then_global_write':('''COUNT=0
VALUE=3
def tick(value=VALUE):
 global COUNT
 COUNT+=value
 return COUNT
print(tick(),tick(),COUNT)
''',('',)),
}


class FrameRequirementProofTests(unittest.TestCase):
    def test_canonical_requirements_precede_either_emitter(self):
        for name,(source,_)in CASES.items():
            with self.subTest(name=name):
                self.assertNotIn('class ',source)
                selection=select_frames(build_program(source,'requirements.py').main)
                self.assertTrue(selection.required)
                self.assertFalse(selection.recursive_definitions)
                self.assertTrue(set(selection.reasons)&{'module binding writes','definition-time defaults'})

    def test_unused_global_writers_local_shadows_and_literal_defaults_keep_fastpath(self):
        sources=['''VALUE=1
def unused():
 global VALUE
 VALUE=2
print(VALUE)
''','''VALUE=1
def local(VALUE):
 VALUE+=2
 return VALUE
print(local(3),VALUE)
''','''def read(value=-3,*,other=None):return value
print(read(),read(5))
''','''def add(value):return value+1
print(add(3))
''']
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(select_frames(build_program(source,'fast.py').main).required)
                with patch('py2fastrust.native_classes.try_generate_classes',side_effect=AssertionError('unnecessary frame path')):
                    self.assertTrue(transpile(source).success)

    def test_required_frame_failure_does_not_retry_scalar_or_vm(self):
        for source in(CASES['counter'][0],CASES['effectful_default'][0]):
            for mode in('i64','i128','bigint'):
                with patch('py2fastrust.native_classes.try_generate_classes',return_value=None)as frames, \
                     patch('py2fastrust.native_scalar.ScalarGenerator.statements',side_effect=AssertionError('scalar retry')), \
                     patch('py2fastrust.native_bigint.try_generate_bigint',side_effect=AssertionError('BigInt retry')), \
                     patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertEqual(frames.call_count,1)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrameRequirementExecutionTests(unittest.TestCase):
    def compare(self,*args,**kwargs):return _heap.HeapExecutionTests.compare(self,*args,**kwargs)


def _test_case(name):
    def test(self):self.compare(*CASES[name])
    return test

for _name in CASES:setattr(FrameRequirementExecutionTests,'test_'+_name,_test_case(_name))


if __name__=='__main__':unittest.main()
