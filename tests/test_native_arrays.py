"""Native numeric buffers match CPython array ownership and conversion rules."""
import unittest,json,os,re,subprocess,sys,tempfile
from pathlib import Path
from unittest.mock import patch
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'integer_codes_have_real_native_widths':'''from array import array
for values in [array('b',[-128,127]),array('B',[0,255]),array('h',[-32768,32767]),array('H',[0,65535]),array('i',[-2147483648,2147483647]),array('I',[0,4294967295]),array('l',[-3,4]),array('L',[3,4]),array('q',[-3,4]),array('Q',[3,4])]:
 print(values.typecode,values.itemsize,list(values))
''',
 'raw_bytes_use_target_native_endianness':'''from array import array
print(array('H',b'\\x01\\x02\\xff\\x00'))
print(array('I',b'\\x01\\x02\\x03\\x04'))
print(array('i',b'\\xff\\xff\\xff\\xff'))
''',
'finite_array_owner_keys_preserve_live_cursor':'''from array import array
rows=[array('I',[1,2]),array('H',[3,4])]
for row in rows:
 stream=iter(row)
 print(row[0],row[-1],next(stream),list(stream))
 row[0]=8
 print(row[0],list(reversed(row)))
''',
'floating_buffers_round_and_pack_native_endian':'''from array import array
first=array('f',[1.25,16777217,-3.5])
second=array('d',[1.25,16777217,-3.5])
print(first,second,list(first),list(second))
print(array('f',first.tobytes()),array('d',second.tobytes()))
''',
'unsigned_bytes_constructor_and_augmented_writes':'''from array import array
values=array('I',bytes(16))
values[1]=7
values[2]|=1<<5
values[-1]+=9
print(values,list(values),len(values),bool(values),values.typecode,values.itemsize)
''',
'constructor_copy_and_cross_type_conversion':'''from array import array
first=array('h',[1,2,3])
second=array('I',first)
first[0]=9
second[1]=8
print(first,second)
print(array('H',()),array('I'),array('I',b''))
''',
'aliases_and_lists_of_typed_buffers':'''from array import array
row=array('H',[0])*4
table=[row,row,array('H',[1,2])]
table[0][2]=8
row.append(3)
print(table[1],row is table[1],table[2] is row,id(row)==id(table[0]))
''',
'repetition_and_inplace_aliases':'''from array import array
row=array('H',[1,2])
other=row
copy=3*row
row*=2
row+=array('H',[9])
row.extend(row)
print(row,other,copy,row is other,row is copy)
row*=0
print(row,other,copy)
print(array('H')*9223372036854775807)
''',
'live_forward_and_reverse_cursors':'''from array import array
row=array('i',[1,2])
stream=iter(row)
alias=stream
print(next(stream),next(alias))
row.append(3)
print(next(stream),next(stream,None))
row.append(4)
print(next(stream,None))
back=reversed(row)
row.append(5)
print(next(back))
row.clear()
print(next(back,None))
row.append(8)
print(next(back,None))
''',
'slices_copy_and_obey_steps':'''from array import array
row=array('i',[1,2,3,4,5])
copy=row[1:4]
row[2]=9
print(copy,row[::-1],row[10:20],row[-100:100:2])
print(row[None:None:-2])
''',
'standard_numeric_buffer_methods':'''from array import array
row=array('H',[1,2])
row.append(True)
row.extend([4,5])
row.fromlist([6,7])
row.frombytes(array('H',[8,9]).tobytes())
print(row.pop(),row.pop(0),row)
row.reverse()
print(row.tolist(),row.tobytes())
row.byteswap()
print(row)
row.byteswap()
print(row)
row.clear()
print(row,bool(row))
''',
'iterable_constructor_and_deferred_source_effects':'''from array import array
def values():
 print('start')
 yield 2
 print('resume')
 yield 3
print(array('I',values()))
''',
'extend_source_callbacks_invalidate_field_caches':'''from array import array
class Box:
 def __init__(self):self.value=1
box=Box()
def values():
 box.value+=1
 yield box.value
row=array('I')
for i in range(3):
 print(box.value)
 row.extend(values())
 print(box.value)
print(row)
''',
 'atomic_fromlist_and_partial_extend':'''from array import array
class Suppress:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):return True
row=array('I',[9])
with Suppress():row.fromlist([1,2.5,3])
print(row)
with Suppress():row.extend([1,2.5,3])
print(row)
''',
'constructor_failure_keeps_source_cursor_position':'''from array import array
class Suppress:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):return True
stream=iter([1,2.5,3])
with Suppress():array('I',stream)
print(next(stream))
''',
'mutable_default_buffer_is_captured_once':'''from array import array
def grow(row=array('I')):
 row.append(1)
 return row
first=grow()
second=grow()
print(first,second,first is second)
''',
'store_order_and_captured_augmented_primaries':'''from array import array
first=array('I',[2])
second=array('I',[9])
current=first
index=0
def owner():print('owner');return current
def key():print('key');return index
def rhs():
 global current,index
 print('rhs')
 current=second
 index=9
 return 4
owner()[key()]+=rhs()
print(first,second)
''',
'store_checks_index_before_element_conversion':'''from array import array
row=array('I',[1])
row[9]=1.5
''',
'unsigned_value_conversion_error':"from array import array\nprint(array('I',[-1]))\n",
'narrow_value_overflow_error':"from array import array\nprint(array('H',[65536]))\n",
'signed_value_overflow_error':"from array import array\nprint(array('b',[128]))\n",
'float_to_integer_error':"from array import array\nprint(array('I',[1.25]))\n",
'invalid_bytes_multiple':"from array import array\nprint(array('I',b'abc'))\n",
'wrong_typecode_is_runtime_error_after_arguments':'''from array import array
def initializer():print('initializer');return [1]
print(array('x',initializer()))
''',
'short_typecode_is_runtime_error':"from array import array\nprint(array(''))\n",
'nonstring_typecode_is_runtime_error':"from array import array\nprint(array(3))\n",
'constructor_string_error':"from array import array\nprint(array('I','abc'))\n",
'method_bound_arguments_evaluate_before_error':'''from array import array
def argument():print('argument');return 2
row=array('I')
row.append(argument(),argument())
''',
'extend_wrong_array_kind':"from array import array\nrow=array('I',[1])\nrow.extend(array('H',[2]))\n",
'constructor_keyword_error':"from array import array\nprint(array('I',initializer=[1]))\n",
'index_error':"from array import array\nprint(array('I',[1])[3])\n",
'index_type_error':"from array import array\nprint(array('I',[1])[1.5])\n",
'pop_empty_error':"from array import array\nrow=array('I')\nrow.pop()\n",
'isinstance_uses_canonical_array_class':'''from array import array
saved=array
print(isinstance(array('I'),saved),isinstance(array('d'),saved),isinstance([1],saved))
''',
}

class ArrayExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_native_numeric_arrays(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(ArrayExecutionTests,_name,None)

class ArrayGuards(unittest.TestCase):
 def test_unimplemented_array_apis_are_explicit(self):
  cases=(("from array import array\nprint(array('u','abc'))\n",'Unicode'),
         ("from array import array\ncode=input()\nprint(array(code))\n",'typecode'),
         ("from array import array\nrow=array('I')\nprint(row.buffer_info())\n",'buffer_info'),
         ("from array import array\nrow=array('I',[1])\nrow[:]=array('I',[2])\n",'slice assignment'),
         ("from array import array\nrow=array('I',[1])\ndel row[0]\n",'deletion'),
         ("from array import array\nrows=[array('I'),array('H')]\nfor row in rows:print(array('I')+row)\n",'alternatives'))
  for source,fragment in cases:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)


class ArrayWideIntegerTests(unittest.TestCase):
 def compare(self,source,modes):
  filename='array_wide.py'
  cp=subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,filename],capture_output=True,text=True,timeout=10)
  failure=json.loads(cp.stderr)if cp.returncode else None
  for mode in modes:
   with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
    result=transpile(source,TranspileOptions(integer=mode,filename=filename,license='none'))
   self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native');self.assertLess(len(result.rust_source.encode()),512*1024)
   with tempfile.TemporaryDirectory(prefix='pytors-array-wide-')as directory:
    rust=Path(directory,'main.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=Path(directory,'native');built=subprocess.run(['rustc','--edition=2021','--crate-name','array_wide',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
     if failure:
      self.assertEqual(actual.stderr.splitlines()[-1],failure['message'])
      self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in failure['frames']])
     else:self.assertEqual(actual.stderr,'')

 def test_wide_integer_conversion_and_structural_errors(self):
  snippets=("row=array('Q',[18446744073709551615]);print(row,list(row),array('Q',row))",
            "print(array('Q',[18446744073709551616]))",
            "print(array('q',[9223372036854775808]))",
            "print(array('b',[1<<100]))",
            "print(array('I')*-(1<<100))",
            "print(array('I',[1])[1<<100])",
            "row=array('I',[1]);row.pop(1<<100)")
  for snippet in snippets:
   with self.subTest(snippet=snippet):self.compare('from array import array\n'+snippet+'\n',('i128','bigint'))

 def test_bigint_to_float_overflow_is_checked(self):
  self.compare("from array import array\nprint(array('f',[1<<1100]))\n",('bigint',))
