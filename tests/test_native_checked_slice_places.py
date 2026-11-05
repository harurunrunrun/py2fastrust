"""Checked native element places preserve Python indexing and effect order."""
import shutil,unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_module_linking as execution

PROGRAM='''class Array:
    def __init__(self):self.values=[11,22,33]
    def update(self,index,value):
        old=self.values[index]
        self.values[index]=value
        return old,self.values[index]
a=Array()
for i in range(-3,3):
    print(a.update(i,100+i))
'''

class CheckedSliceEmission(unittest.TestCase):
    def test_owned_vector_indexing_uses_one_checked_element_place(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(PROGRAM,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            self.assertIn('class_slice_get(values,index)',result.rust_source)
            self.assertIn('class_slice_get_mut(values,index)',result.rust_source)
            self.assertNotIn('values[offset]',result.rust_source)
            self.assertNotIn('get_unchecked',result.rust_source)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class CheckedSliceExecution(unittest.TestCase):
    def exercise(self,source):
        execution.NativeLinkedModuleTests.exercise(self,{'main.py':source})

    def test_negative_indices_and_repeated_owned_updates(self):
        self.exercise(PROGRAM)

    def test_local_and_shared_aliases_keep_effectful_assignment_order(self):
        self.exercise('''class Worker:
    def local(self):
        values=[7,8,9]
        for index in range(-3,3):values[index]+=index
        return values[-1],values[0],len(values)
    def shared(self,values):
        def index():
            print("index",len(values))
            values.append(10)
            return -1
        values[index()]=values[index()]+1
        return values
values=[1,2,3]
alias=values
w=Worker()
print(w.local(),w.shared(values),alias)
''')

    def test_minimum_integer_read_keeps_original_error_frames(self):
        self.exercise('''class Array:
    def __init__(self):self.values=[1,2]
    def read(self,index):return self.values[index]
print(Array().read(-9223372036854775808))
''')

    def test_invalid_assignment_keeps_rhs_effects_and_original_error(self):
        self.exercise('''def value():
    print("rhs")
    return 9
class Array:
    def __init__(self):self.values=[1,2]
    def write(self,index):self.values[index]=value()
Array().write(9223372036854775807)
''')
