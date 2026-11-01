"""Comparator effects use the shared AOT callback and sorting protocols."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
CASES={'recursive_callback': 'from functools import cmp_to_key\n'
                       'def recur(n,x):\n'
                       ' if n==0:return x\n'
                       ' return recur(n-1,x)\n'
                       'def compare(a,b):return recur(3,a-b)\n'
                       'print(sorted([4,1,3,2],key=cmp_to_key(compare)))\n',
 'recursive_method_sort': 'from functools import cmp_to_key\n'
                          'def recur(n,x):\n'
                          ' if n==0:return x\n'
                          ' return recur(n-1,x)\n'
                          'values=[4,1,3,2]\n'
                          'values.sort(key=cmp_to_key(lambda '
                          'a,b:recur(3,b-a)))\n'
                          'print(values)\n',
 'partial_stop_state': 'from functools import cmp_to_key\n'
                       'values=[8,3,6,1,5,2,7,4]\n'
                       'calls=[0]\n'
                       'def compare(a,b):\n'
                       ' calls[0]+=1\n'
                       ' if calls[0]==7:return next(iter([]))\n'
                       ' return a-b\n'
                       'def run(_):\n'
                       ' values.sort(key=cmp_to_key(compare))\n'
                       ' return 0\n'
                       'print(list(map(run,[1])))\n'
                       'print(values,calls)\n',
 'reverse_partial_stop_state': 'from functools import cmp_to_key\n'
                               'values=[8,3,6,1,5,2,7,4]\n'
                               'calls=[0]\n'
                               'def compare(a,b):\n'
                               ' calls[0]+=1\n'
                               ' if calls[0]==7:return next(iter([]))\n'
                               ' return a-b\n'
                               'def run(_):\n'
                               ' '
                               'values.sort(key=cmp_to_key(compare),reverse=True)\n'
                               ' return 0\n'
                               'print(list(map(run,[1])))\n'
                               'print(values,calls)\n',
 'empty_list_during_comparison': 'from functools import cmp_to_key\n'
                                 'values=[3,1,2]\n'
                                 'def compare(a,b):\n'
                                 ' print(len(values))\n'
                                 ' return a-b\n'
                                 'values.sort(key=cmp_to_key(compare))\n'
                                 'print(values)\n',
 'mutation_during_comparison': 'from functools import cmp_to_key\n'
                               'values=[3,1,2]\n'
                               'def compare(a,b):\n'
                               ' values.append(9)\n'
                               ' return a-b\n'
                               'values.sort(key=cmp_to_key(compare))\n'
                               'print(values)\n',
 'mixed_key_alternatives': 'from functools import cmp_to_key\n'
                           'def compare(a,b):return b-a\n'
                           'def solve(mode):\n'
                           ' key=cmp_to_key(compare) if mode==0 else None if '
                           'mode==1 else abs\n'
                           ' return sorted([-3,1,-2],key=key)\n'
                           'print(solve(0),solve(1),solve(2))\n',
 'returned_factory': 'from functools import cmp_to_key\n'
                     'def make(direction):\n'
                     ' def compare(a,b):return direction*(a-b)\n'
                     ' return cmp_to_key(compare)\n'
                     'key=make(-1)\n'
                     'print(sorted([3,1,2],key=key))\n',
 'saved_callback': 'from functools import cmp_to_key\n'
                   'def compare(a,b):return a-b\n'
                   'key=cmp_to_key(compare)\n'
                   'compare=lambda a,b:b-a\n'
                   'print(sorted([3,1,2],key=key))\n',
 'multiple_factories': 'from functools import cmp_to_key\n'
                       'def solve(key):return sorted([3,1,2],key=key)\n'
                       'a=cmp_to_key(lambda a,b:a-b)\n'
                       'b=cmp_to_key(lambda a,b:b-a)\n'
                       'print(solve(a),solve(b))\n',
 'factory_identity': 'from functools import cmp_to_key\n'
                     'key=cmp_to_key(lambda a,b:a-b)\n'
                     'other=key\n'
                     'print(bool(key),key is other,key is cmp_to_key(lambda '
                     'a,b:a-b))\n'
                     'print(sorted([3,1,2],key=other))\n',
 'cmp_global_rebinding': 'from functools import cmp_to_key\n'
                         'def compare(a,b):return a-b\n'
                         'key=cmp_to_key(compare)\n'
                         'def source():\n'
                         ' global compare\n'
                         ' compare=lambda a,b:b-a\n'
                         ' return [3,1,2]\n'
                         'print(sorted(source(),key=key))\n',
 'tuple_comparator_result': 'from functools import cmp_to_key\n'
                            'print(sorted([3,1,2],key=cmp_to_key(lambda '
                            'a,b:(a,b))))\n',
 'none_comparator_result': 'from functools import cmp_to_key\n'
                           'print(sorted([3,1,2],key=cmp_to_key(lambda '
                           'a,b:None)))\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class ComparisonKeyEffects(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_recursive_callback(self):self.check('recursive_callback')
    def test_recursive_method_sort(self):self.check('recursive_method_sort')
    def test_partial_stop_state(self):self.check('partial_stop_state')
    def test_reverse_partial_stop_state(self):self.check('reverse_partial_stop_state')
    def test_empty_list_during_comparison(self):self.check('empty_list_during_comparison')
    def test_mutation_during_comparison(self):self.check('mutation_during_comparison')
    def test_mixed_key_alternatives(self):self.check('mixed_key_alternatives')
    def test_returned_factory(self):self.check('returned_factory')
    def test_saved_callback(self):self.check('saved_callback')
    def test_multiple_factories(self):self.check('multiple_factories')
    def test_factory_identity(self):self.check('factory_identity')
    def test_cmp_global_rebinding(self):self.check('cmp_global_rebinding')
    def test_tuple_comparator_result(self):self.check('tuple_comparator_result')
    def test_none_comparator_result(self):self.check('none_comparator_result')
