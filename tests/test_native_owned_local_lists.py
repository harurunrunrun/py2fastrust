"""Unique local vectors and shared Python list identities on the class path."""
import shutil
import unittest

from py2fastrust import TranspileOptions,transpile
from tests import test_native_classes as _classes
from tests import test_native_module_linking as _linked


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class OwnedLocalListTests(unittest.TestCase):
    compile=_classes.NativeClassTests.compile
    compare=_classes.NativeClassTests.compare
    exercise=_linked.NativeLinkedModuleTests.exercise

    def test_indexed_dp_uses_owned_storage_in_a_program_with_classes(self):
        source='''class Marker: pass
def solve(n):
 a=[0]*(n+1)
 a[0]=1
 for i in range(1,n+1):a[i]=a[i-1]+i
 print(len(a),a[-1],a[0])
solve(9)
'''
        self.compare(source)
        rust=transpile(source,TranspileOptions(license='none')).rust_source
        self.assertRegex(rust,r'let mut class_local_\d+:Option<Vec<NativeInt>>')
        self.assertNotIn('class_list_get(',rust)
        self.assertNotIn('class_list_set(',rust)

    def test_comprehension_and_fresh_replacement(self):
        self.compare('''class Marker: pass
def solve():
 a=[i*i for i in range(7)]
 a[2]+=a[-1]
 print(a[2],len(a))
 a=[8,9]
 print(a[-1],len(a))
solve()
''')

    def test_repeated_elements_keep_shared_identity(self):
        self.compare('''class Marker: pass
def solve():
 row=[1]
 rows=[row]*3
 rows[1][0]=8
 print(rows[0][0],rows[2][0],rows[0] is rows[1])
solve()
''')

    def test_escaped_alias_and_lexical_rebinding_keep_shared_storage(self):
        self.compare('''class Marker: pass
def solve():
 a=[1,2]
 b=a
 b[0]=9
 print(a[0],a is b)
 def touch():
  nonlocal a
  a=[8,9]
  return 0
 a[0]+=touch()
 print(a[0],a[1],b[0])
solve()
''')

    def test_index_and_rhs_calls_execute_in_python_order(self):
        self.compare('''class Marker: pass
def index():
 print('index')
 return -1
def value():
 print('value')
 return 8
def solve():
 a=[1,2]
 a[index()]=value()
 a[index()]+=value()
 print(a[0],a[-1])
solve()
''')

    def test_unbound_owner_precedes_index_call(self):
        self.compare('''class Marker: pass
def index():
 print('must not run')
 return 0
def solve(flag):
 if flag:a=[1]
 print(a[index()])
solve(False)
''')

    def test_shadowed_len_keeps_argument_identity(self):
        self.compare('''class Marker: pass
def solve():
 a=[1,2]
 def len(x):
  x[0]=8
  return 19
 print(len(a),a[0])
solve()
''')

    def test_comprehension_target_has_its_own_binding(self):
        self.compare('''class Marker: pass
def solve():
 a=[1,2]
 b=[a*a for a in range(3)]
 print(a[0],b[-1])
solve()
''')

    def test_list_constructor_copies_outer_vector_without_aliasing(self):
        self.compare('''class Marker:pass
def solve():
 original=[2,3]
 a=list(original)
 a[0]=8
 b=list(range(3))
 print(a[0],original[0],a[-1],b[0],b[-1],len(b))
solve()
''')

    def test_input_array_can_append_a_different_element_type(self):
        self.compare('''class Marker:pass
def solve():
 a=list(map(int,input().split()))
 a.append('tail')
 print(a[0]+1,a[-1],len(a))
solve()
''',data='2 3\n')

    def test_mutable_heterogeneous_pairs_and_pop(self):
        self.compare('''class Marker:pass
def solve(i):
 pair=[3,'cat']
 print(pair[0]+2,pair[1]+'s')
 pair[0]='changed'
 pair[1]=9
 print(pair[i],pair[1-i],len(pair))
 pair.append(False)
 print(pair.pop(),pair[0],pair[-1])
solve(0)
solve(1)
''')

    def test_imported_function_arrays_use_only_registered_source_nodes(self):
        self.exercise({
            'main.py':'import library\nlibrary.solve(6)\n',
            'library.py':'''class Marker:pass
def solve(n):
 a=[0]*(n+1)
 a[0]=1
 b=list(range(n+1))
 for i in range(1,n+1):a[i]=a[i-1]+b[i]
 print(a[-1],b[0],len(a))
'''})


if __name__=='__main__':unittest.main()
