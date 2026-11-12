"""Use fixed tuple field proofs regardless of the producer's normalization kind."""
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
import test_native_union_ordering as helpers


CASES={
 'pop':('pairs=[(2,3),(5,7)]\na,b=pairs.pop()\nprint(a,b,len(pairs))\n',('',)),
 'pop_index':('pairs=[(2,3),(5,7)]\na,b=pairs.pop(int(input()))\nprint(a,b,len(pairs))\n',('0\n','1\n','-1\n','-2\n','2\n','-3\n')),
 'pop_index_effects':('''def index():
 print('index')
 return int(input())
pairs=[(2,3),(5,7)]
print('before')
a,b=pairs.pop(index())
print(a,b,len(pairs))
''',('0\n','2\n')),
 'pop_empty':('pairs=[(2,3)]\npairs.pop()\nprint("before")\na,b=pairs.pop()\nprint(a,b)\n',('',)),
 'pop_duplicate_targets':('pairs=[(2,3)]\nx,x=pairs.pop()\nprint(x,len(pairs))\n',('',)),
 'pop_too_many':('pairs=[(2,3,5)]\nprint("before")\na,b=pairs.pop()\nprint(a,b)\n',('',)),
 'pop_too_few':('pairs=[(2,3)]\nprint("before")\na,b,c=pairs.pop()\nprint(a,b,c)\n',('',)),
 'heterogeneous_pop':('pairs=[("name",2.5)]\na,b=pairs.pop()\nprint(a,b,len(pairs))\n',('',)),
 'nested_target':('pairs=[((2,3),"done")]\n(a,b),c=pairs.pop()\nprint(a,b,c,len(pairs))\n',('',)),
 'deque_popleft':('from collections import deque\npairs=deque([(2,3),(5,7)])\na,b=pairs.popleft()\nprint(a,b,len(pairs))\n',('',)),
 'dict_popitem':('pairs={"a":2,"b":3}\na,b=pairs.popitem()\nprint(a,b,len(pairs))\n',('',)),
 'dict_popitem_reinsert':('''pairs={'a':2,'b':3,'c':5}
del pairs['b']
pairs['b']=7
while pairs:
 a,b=pairs.popitem()
 print(a,b,len(pairs))
''',('',)),
 'dict_popitem_original_numeric_key':('''pairs={True:'one',2:'two'}
pairs[1]='new'
first,value=pairs.popitem()
print(first,value)
last,value=pairs.popitem()
print(last,value)
''',('',)),
 'dict_popitem_empty':('pairs={1:2}\npairs.popitem()\nprint("before")\na,b=pairs.popitem()\nprint(a,b)\n',('',)),
 'dict_popitem_initial_empty':('pairs={}\nprint("before")\na,b=pairs.popitem()\nprint(a,b)\n',('',)),
 'dict_popitem_discarded':('pairs={"a":2,"b":3}\npairs.popitem()\nprint(len(pairs),pairs)\npairs.popitem()\nprint(len(pairs))\n',('',)),
 'function_result':('''def pair():
 print('pair')
 return 'name',2.5
a,b=pair()
print(a,b)
''',('',)),
}


class FixedTupleUnpackLayout(unittest.TestCase):
 def test_pop_has_no_integer_vector_for_unpacking(self):
  source='pairs=[(2,3)]\na,b=pairs.pop()\nprint(a,b)\n'
  for mode in ('i64','i128','bigint'):
   with self.subTest(mode=mode):
    result=transpile(source,TranspileOptions(integer=mode,license='none'))
    self.assertTrue(result.success,result.diagnostics)
    self.assertEqual(result.backend,'native')
    self.assertNotIn('Vec<NativeInt>',result.rust_source)
    self.assertNotIn('Vec<Int>',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class MethodTupleUnpackExecution(unittest.TestCase):
 setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
 tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
 compile=helpers.NativeUnionOrderingTests.compile
 exercise=helpers.NativeUnionOrderingTests.exercise


def runtime_case(name):
 def test(self):
  source,inputs=CASES[name]
  self.exercise(source,inputs)
 return test
for name in CASES:setattr(MethodTupleUnpackExecution,'test_'+name,runtime_case(name))
