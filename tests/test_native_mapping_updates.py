"""Numeric mapping updates preserve lookup order and exception atomicity."""
import shutil
import unittest

from py2fastrust import transpile,TranspileOptions
import test_native_mapping_mutations as mutations


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeMappingUpdateTests(unittest.TestCase):
    compare=mutations.NativeMappingMutationTests.compare

    def test_numeric_operations_and_scalar_conditional_operands(self):
        self.compare('''d={1:10,2:20}
x=int(input())
d[1]+=x*2+1
d[2]-=x if x>0 else -x
d[1]*=3
d[1]//=4
d[1]%=7
d[2]&=31
d[2]|=8
d[2]^=3
d[2]<<=1
d[2]>>=2
d[1]**=3
print(d,list(d.items()))
''',('2\n','-3\n','0\n'))

    def test_selected_width_arithmetic_for_existing_entries(self):
        self.compare('''d={1:2**62,2:-5}
x=int(input())
d[1]*=x
d[2]//=x
d[1]+=2**126
print(d)
''',('3\n','-3\n'),integer_policy=True)

    def test_original_key_identity_and_reused_deleted_slots(self):
        self.compare('''d={True:3,2:4,3:5}
del d[2]
d[4]=6
d[1]+=7
d[3]*=2
d[4]%=5
print(d,list(d.items()))
s={'first':4,'last':8}
s['first']+=3
s['last']//=2
print(s)
t={(1,'a'):5}
t[(1,'a')]-=2
print(t)
''')

    def test_missing_key_precedes_unbound_right_operand(self):
        self.compare('''d={1:4}
if int(input()):right=2
key=int(input())
d[key]+=right
print(d)
''',('0\n2\n','0\n1\n','1\n1\n','1\n2\n'))

    def test_scalar_errors_and_short_circuit_operands(self):
        self.compare('''d={1:7}
x=int(input())
d[1]+=(x and 10//x) or 3
print(d)
d[1]//=x
print(d)
''',('0\n','2\n','-2\n'))

    def test_effectful_rhs_does_not_hold_a_mapping_reference(self):
        self.compare('''d={1:7,2:8}
d[1]+=(d.clear(),3)[1]
print(d)
d[1]+=(print('rhs'),2)[1]
print(d)
''')

    def test_key_effects_run_before_borrow_and_rhs(self):
        self.compare('''def mark(value):
 print('key')
 return value
d={1:7}
d[mark(int(input()))]+=3
print(d)
''',('1\n','2\n'))

    def test_compiled_numeric_path_updates_the_existing_slot(self):
        source="d={1:4}\nx=int(input())\nd[1]+=x*2\nprint(d)\n"
        for mode in('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,filename='mapping.py'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertTrue('.item_mut('in result.rust_source or '.get_mut(&'in result.rust_source)
            self.assertNotIn('enum Instruction',result.rust_source)
