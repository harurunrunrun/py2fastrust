"""Native bytearray retains mutable-byte identity and original evaluation stages."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions


SUPPRESS='''class Suppress:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):return True
'''

CASES={
'constructors_and_builtin_type_identity':'''print(bytearray(),bytearray(4),bytearray(True))
print(bytearray([0,1,127,255]),bytearray((True,False,65)),bytearray(range(4)))
print(bytearray(source=b'ab'),isinstance(bytearray(),bytearray),isinstance(b'ab',bytearray))
print(bytearray)
''',
'canonical_constructor_alias_and_shadow':'''make=bytearray
bytearray=3
print(make(b'abc'),bytearray)
''',
'copy_identity_repr_and_bytes_snapshot':r'''a=bytearray(b"a'\\\x00\n\xff")
alias=a
other=bytearray(a)
frozen=bytes(a)
a[0]=90
print(a,repr(a),str(a),alias is a,other is a,other,frozen)
print(id(a)==id(alias),id(a)==id(other),bool(a),len(a),bool(bytearray()))
''',
'negative_integer_reads_writes_and_augmented':'''a=bytearray([3,8,20])
a[-1]=255
a[True]+=4
print(a[0],a[-1],a)
''',
'concat_and_repeat_result_types':'''a=bytearray(b'ab')
print(a+b'c',b'c'+a,a+bytearray(b'd'),3*a,a*(-2))
print(isinstance(a+b'c',bytearray),isinstance(b'c'+a,bytes))
''',
'in_place_mutations_retain_alias':'''a=bytearray(b'ab')
alias=a
a+=bytearray(a)
a*=2
print(a,alias is a,alias)
a*=0
print(alias,alias is a)
''',
'nonempty_self_iadd_preserves_buffer_error':"a=bytearray(b'ab')\na+=a\n",
'empty_self_iadd_has_no_resize_error':"a=bytearray()\na+=a\nprint(a)\n",
'read_slices_create_independent_mutable_buffers':'''a=bytearray(range(9))
for b in [a[:],a[::-1],a[2:8:2],a[-100:100],a[7:1:-2]]:print(b)
b=a[:]
b[0]=88
print(a,b,b is a)
''',
'contiguous_and_extended_slice_stores':'''a=bytearray(b'abcdef')
a[1:3]=b'XYZ'
a[5:2]=[48,49]
print(a)
a[::2]=b'12345'
print(a)
a[7:0:-2]=[1,2,3,4]
print(a)
a[:]=a
a[1:8]=b''
print(a)
''',
'self_slice_write_snapshots_rhs':'''a=bytearray(b'abcdef')
alias=a
a[1:3]=a
print(a,alias is a)
a[::2]=a[:5]
print(a)
''',
'slice_source_iteration_has_no_length_hint_and_sees_current_length':'''a=bytearray(b'abcd')
class Source:
 def __iter__(self):
  global a
  print('iter')
  a+=b'Q'
  return iter([7,8])
 def __len__(self):print('unexpected hint');return 2
a[2:99]=Source()
print(a)
a=bytearray(b'abcd')
a[-2:]=Source()
print(a)
''',
'constructor_iteration_has_no_length_hint':'''class Source:
 def __iter__(self):print('iter');return iter([1,2,3])
 def __len__(self):print('unexpected hint');return 3
print(bytearray(Source()))
''',
'slice_source_failure_is_atomic':SUPPRESS+'''a=bytearray(b'abcd')
def source():
 print('first');yield 7
 print('invalid');yield 256
 print('unreachable');yield 8
with Suppress():a[1:3]=source()
print(a)
''',
'slice_current_length_failure_retains_callback_effects':SUPPRESS+'''a=bytearray(b'abcd')
def source():
 global a
 a+=b'Q'
 yield 7
 yield 8
with Suppress():a[::-1]=source()
print(a)
''',
'rhs_owner_bounds_and_iteration_order':'''a=bytearray(b'abcd')
def owner():print('owner');return a
def bound(label,value):print(label);return value
def source():
 print('pull')
 yield 8
 yield 9
def rhs():print('rhs');return source()
owner()[bound('start',1):bound('stop',3):bound('step',1)]=rhs()
print(a)
''',
'forward_iterator_sharing_and_mutation':'''a=bytearray([1,2])
cursor=iter(a)
alias=cursor
print(next(cursor),iter(cursor) is cursor)
a[1]=8
a.append(9)
print(next(alias),list(cursor),next(alias,99))
a.append(10)
print(list(cursor),a)
''',
'reverse_cursor_captures_start_and_shares_position':'''a=bytearray([1,2,3])
cursor=reversed(a)
alias=cursor
print(isinstance(cursor,reversed),isinstance(iter(a),reversed))
a.append(4)
print(next(cursor),next(alias))
a[:]=b'Q'
print(list(cursor),next(alias,99))
''',
'methods_mutate_and_return_real_types':'''a=bytearray(b'ab')
alias=a
a.extend(a)
a.extend(b'CD')
b=a.copy()
a.reverse()
print(a,b,alias is a,b is a)
print(a.clear(),a,alias)
''',
'bytearray_comparisons_use_byte_sequences':'''a=bytearray(b'ab')
b=bytearray(b'ab')
print(a==b,a==b'ab',b'ab'==a,a!=[97,98],a<b'c',b'a'<a)
print(a is b,a is a,a is None)
''',
'element_range_error_precedes_bounds_error':"a=bytearray([1])\na[999]=256\n",
'element_type_error_precedes_bounds_error':"a=bytearray([1])\na[999]=1.0\n",
'index_type_precedes_element_range_error':"a=bytearray([1])\na[1.5]=256\n",
'out_of_range_index':"print(bytearray([1])[2])\n",
'slice_zero_step_precedes_rhs_byte_validation':"a=bytearray([1])\na[::0]=[256]\n",
'extended_slice_requires_exact_length':"a=bytearray(b'abcd')\na[::2]=b'X'\n",
'slice_rejects_integer_count_source':"a=bytearray(b'abcd')\na[:]=3\n",
'constructor_invalid_element':"print(bytearray([1,256]))\n",
'constructor_float_error':"print(bytearray(1.5))\n",
'constructor_none_error':"print(bytearray(None))\n",
'constructor_negative_count':"print(bytearray(-1))\n",
'constructor_text_needs_encoding':"print(bytearray('abc'))\n",
'method_binding_error_after_argument_effects':"a=bytearray()\na.clear(print('argument'))\n",
'immutable_bytes_repeat_is_independent':'''def mark(label,value):print(label);return value
print(mark('bytes',b'ab')*mark('count',3),2*b'Q',b'Q'*(-2),b''*5)
''',
'immutable_bytes_size_multiplication_is_checked':"print(b'ab'*9223372036854775807)\n",
'numeric_consumers_use_byte_text_and_character_protocols':'''print(int(bytearray(b' -4 ')),int(bytearray(b'0xA'),0),int(bytearray(b'101'),base=2))
print(float(bytearray(b' -1.25 ')),ord(bytearray(b'Z')))
''',
'invalid_bytearray_integer_text':"print(int(bytearray(b'bad')))\n",
'invalid_bytearray_float_text':"print(float(bytearray(b'bad')))\n",
'invalid_bytearray_ordinal_length':"print(ord(bytearray(b'ab')))\n",
'complete_byte_repr_and_nested_display':'''a=bytearray(range(256))
print(repr(a))
print([bytearray(b'a'),bytearray()],f"{bytearray(b'Q')!r}")
''',
'forward_cursor_has_real_builtin_type_in_errors':"print(int(iter(bytearray())))\n",
'reverse_cursor_has_real_builtin_type_in_errors':"print(int(reversed(bytearray())))\n",
}


class BytearrayExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_native_mutable_byte_contracts(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)


for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(BytearrayExecutionTests,_name,None)


class BytearrayBoundaryTests(unittest.TestCase):
 def test_unimplemented_protocols_are_explicit(self):
  programs=[("bytearray('ab','utf8')",'encoding'),
   ("from array import array\nbytearray(array('I',[1]))",'buffer'),
   ("from array import array\na=bytearray()\na[:]=array('I',[1])",'buffer'),
   ("from array import array\narray('I',bytearray([1,0,0,0]))",'buffer'),
   ("from array import array\na=array('I')\na.frombytes(bytearray([1,0,0,0]))",'buffer'),
   ("a=bytearray(b'ab')\na[:]+=b'c'",'augmented'),
   ("a=bytearray()\na.extend([1,2])",'length-hint'),
   ("a=bytearray()\na.pop()",'pop'),
   ("a=bytearray()\ndel a[:]",'deletion')]
  for source,word in programs:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertTrue(any(word in diagnostic.message for diagnostic in result.diagnostics),result.diagnostics)


class BytearrayWideTests(unittest.TestCase):
 def test_checked_counts_and_indices_beyond_signed_size(self):
  import os,subprocess,sys,tempfile
  from pathlib import Path
  from unittest.mock import patch
  programs=["print(bytearray(1<<100))\n", "a=bytearray([1])\na[1<<100]=256\n", "print(b''*(1<<100))\n"]
  for source in programs:
   expected=subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,'bytearray_wide.py'],capture_output=True,text=True,timeout=10)
   import json
   failure=json.loads(expected.stderr)
   with tempfile.TemporaryDirectory(prefix='pytors-bytearray-wide-')as directory:
    for mode in ('i128','bigint'):
     with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
      result=transpile(source,TranspileOptions(integer=mode,filename='bytearray_wide.py',license='none'))
     self.assertTrue(result.success,result.diagnostics)
     rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
     for optimized in (False,True):
      binary=rust.with_suffix('.opt'if optimized else'.debug')
      built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
      self.assertEqual(built.returncode,0,built.stderr)
      ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
      self.assertEqual((ran.returncode,ran.stdout),(expected.returncode,expected.stdout),ran.stderr)
      self.assertEqual(ran.stderr.splitlines()[-1],failure['message'])
