"""Builtin print retains its effects and None result in expression contexts."""
import shutil
import unittest
import test_native_mapping_mutations as mutations


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativePrintValueTests(unittest.TestCase):
    compare=mutations.NativeMappingMutationTests.compare

    def test_assignment_and_nested_print_evaluation(self):
        self.compare('''first=print('first',end='|')
second=print(print('inner'),first,sep=':',end='!')
print(second is None)
''')

    def test_boolean_and_conditional_expression_effects(self):
        self.compare('''flag=int(input())
selected=print('left') or (3 if flag else print('right'))
print(selected)
print(flag and print('and'))
print(flag or print('or'))
''',('0\n','1\n'))

    def test_print_value_inside_augmented_mapping_rhs(self):
        self.compare('''d={1:7}
d[1]+=(print('rhs'),2)[1]
print(d)
''')

    def test_captured_builtin_returns_none(self):
        self.compare('''write=print
result=write('alias',sep=':',end='|',flush=True)
print(result)
write(7)
''')

    def test_argument_errors_precede_output(self):
        self.compare("print(print('before'),1//int(input()))\n",('0\n','2\n'))
