"""Native random matches seeded CPython streams and mutable sequence effects."""
import json,os,re,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions

CASES={
'seeded_core_stream_interleaving':'''import random
random.seed(12345)
print([random.getrandbits(32) for _ in range(6)])
print([random.random() for _ in range(4)])
print([random.randrange(-10,20,3) for _ in range(6)])
print([random.randint(-20,20) for _ in range(6)])
values=[1,2,3,4,5]
random.shuffle(values)
print(values)
''',
'absolute_integer_seed_words':'''from random import seed,getrandbits,random
for value in [0,1,-1,4294967296,9223372036854775807,-9223372036854775808]:
 seed(value)
 print([getrandbits(32) for _ in range(3)],random())
seed(17,version=1)
print(getrandbits(32))
seed(17,version=9)
print(getrandbits(32))
''',
'word_boundaries_zero_and_wrapped_bits_consume_full_stream':'''import random
random.seed(777)
mask=(1<<63)-1
for width in [0,1,31,32,33,63,64,65,127,128,129,257,1024]:
 print(width,random.getrandbits(width)&mask)
print(random.random())
''',
'mt_twist_boundary':'''from random import seed,getrandbits,random
seed(56)
for i in range(1300):
 value=getrandbits(32)
 if i in [0,622,623,624,625,1247,1248,1299]:print(i,value)
print(random())
''',
'checked_structural_spans_exceed_native_signed_width':'''import random
random.seed(987)
low=-9223372036854775808
high=9223372036854775807
for _ in range(8):print(random.randrange(low,high),random.randint(low,high))
print([random.randrange(high,low,low) for _ in range(8)])
print(random.random())
''',
'positive_negative_and_boolean_steps':'''import random
random.seed(442)
print([random.randrange(19) for _ in range(8)])
print([random.randrange(3,40,4) for _ in range(8)])
print([random.randrange(30,-20,-7) for _ in range(8)])
print(random.randrange(True),random.randrange(8,None,1),random.randrange(False,True,True))
print(random.randint(True,True))
''',
'canonical_aliases_and_keyword_binding':'''import random as source
from random import randrange as choose,seed as reseed
reseed(a=41,version=2)
print(choose(start=20),source.randint(b=9,a=2))
reseed(41)
print(source.randrange(20),source.randint(2,9))
print(reseed is source.seed,choose is source.randrange)
''',
'shuffle_preserves_shared_list_and_element_identities':'''from random import seed,shuffle,getrandbits
seed(929)
left=[1]
right=[2]
values=[left,right,left,[3]]
alias=values
shuffle(values)
print([item[0] for item in values],alias is values)
left.append(7)
print(values,getrandbits(32))
shuffle([])
shuffle([1])
print(getrandbits(32))
''',
'shuffle_numeric_arrays_uses_same_stream':'''from array import array
import random
random.seed(22)
values=array('I',[2,3,5,7,11,13])
alias=values
random.shuffle(values)
print(values.tolist(),alias is values,random.getrandbits(32))
''',
'source_argument_effect_order':'''import random
def mark(label,value):print(label);return value
random.seed(mark('seed',17),version=mark('version',2))
print(random.randrange(mark('start',2),mark('stop',30),mark('step',3)))
print(random.randint(mark('lower',2),mark('upper',8)))
''',
'failed_calls_do_not_consume_seeded_words':'''import random
class Suppress:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):return True
random.seed(81)
expected=random.getrandbits(32)
random.seed(81)
with Suppress():random.randrange(3,1)
with Suppress():random.randrange(1,9,0)
with Suppress():random.getrandbits(-1)
print(expected==random.getrandbits(32))
''',
 'none_stop_distinguishes_integer_one_from_equal_values':'''import random
class Suppress:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):return True
random.seed(4)
for step in [1,True,1.0,None]:
 with Suppress():print(random.randrange(5,None,step))
print(random.getrandbits(32))
''',
'unseeded_module_invariants':'''import random
values=[random.randrange(-10,11,3) for _ in range(12)]
print(all(-10<=value<11 and (value+10)%3==0 for value in values))
print(all(0<=random.random()<1 for _ in range(12)))
items=list(range(20))
random.shuffle(items)
print(sorted(items)==list(range(20)))
random.seed(None)
print(0<=random.getrandbits(32)<4294967296)
''',
'empty_range_error':"import random\nrandom.randrange(0)\n",
'empty_step_range_error':"import random\nrandom.randrange(1,7,-2)\n",
'zero_step_error':"import random\nrandom.randrange(1,7,0)\n",
'index_type_error':"import random\nrandom.randrange(1,9.0)\n",
'negative_bit_count_error':"import random\nrandom.getrandbits(-1)\n",
'stop_none_checks_step_identity_before_index':"import random\nrandom.randrange(4,None,True)\n",
'randint_lower_index_precedes_upper_index':"import random\nrandom.randint(1.5,None)\n",
'randint_empty_inclusive_range_error':"import random\nrandom.randint(True,False)\n",
'python_bound_method_arity_error':"import random\nrandom.randrange(1,2,3,4)\n",
'c_bound_method_arity_error':"import random\nrandom.getrandbits()\n",
'callable_error_type_name_is_method':"import random\nint(random.seed)\n",
}

class RandomExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_seeded_streams_and_protocol_errors(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(RandomExecutionTests,_name,None)

class RandomWideErrorTests(unittest.TestCase):
 def compare(self,source,modes,module_paths=()):
  filename='random_wide.py'
  cp_reference=('import sys;sys.path[:0]='+repr([str(path)for path in module_paths])+'\n')+iterator_tests.REFERENCE
  cp=subprocess.run([sys.executable,'-I','-S','-c',cp_reference,source,filename],capture_output=True,text=True,timeout=10)
  failure=json.loads(cp.stderr)if cp.returncode else None
  for mode in modes:
   with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
    result=transpile(source,TranspileOptions(integer=mode,filename=filename,license='none',module_paths=tuple(module_paths)))
   self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native');self.assertLess(len(result.rust_source.encode()),512*1024)
   with tempfile.TemporaryDirectory(prefix='pytors-random-wide-')as directory:
    rust=Path(directory,'main.rs');rust.write_text(result.rust_source)
    for optimized in (False,True):
     binary=Path(directory,'native');built=subprocess.run(['rustc','--edition=2021','--crate-name','random_wide',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
     self.assertEqual(built.returncode,0,built.stderr)
     actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
     self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
     if failure:
      self.assertTrue(actual.stderr.endswith(failure['message']+'\n'),actual.stderr)
      self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in failure['frames']])
     else:self.assertEqual(actual.stderr,'')

 def test_local_random_source_module_keeps_its_own_identity(self):
  with tempfile.TemporaryDirectory(prefix='pytors-local-random-')as directory:
   folder=Path(directory)
   (folder/'random.py').write_text('def randrange(stop):return 777\n')
   self.compare('import random\nprint(random.randrange(7))\n',('i64','i128','bigint'),(folder,))

 def test_large_seeds_and_bit_results(self):
  source='import random\nrandom.seed((1<<350)+91)\nprint(random.getrandbits(257))\nprint(random.random())\n'
  self.compare(source,('bigint',))

 def test_full_i128_structural_range_spans(self):
  source='import random\nrandom.seed(35)\nlow=-(1<<127)\nhigh=(1<<127)-1\nfor _ in range(4):print(random.randrange(low,high),random.randint(low,high))\nprint(random.getrandbits(32))\n'
  self.compare(source,('i128','bigint'))

 def test_uint64_count_overflow_and_checked_allocation(self):
  for expression in ('1<<63','1<<64'):
   self.compare('import random\nrandom.getrandbits('+expression+')\n',('i128','bigint'))

 def test_invalid_seed_type_multiline_error(self):
  self.compare('import random\nrandom.seed([])\n',('i64','i128','bigint'))

class RandomGuards(unittest.TestCase):
 def test_unimplemented_random_protocols_name_the_boundary(self):
  cases=(("import random\nrandom.seed('abc')\n",'seed'),
         ("import random\nrandom.seed(1.25)\n",'seed'),
         ("import random\nprint(random.Random())\n",'Random'),
         ("import random\nrandom.shuffle((1,2))\n",'shuffle'),
         ("import random\nprint(random.seed)\n",'bound receiver'))
  for source,fragment in cases:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)
