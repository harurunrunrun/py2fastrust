"""Starred iteration targets share assignment unpacking and lexical cells."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
CASES={'for_tuple_rows': 'for first,*rest,last in '
                   '[(1,2,3),(4,5)]:print(first,rest,last)\n',
 'for_list_rows': 'for first,*rest in [[1,2],[3,4,5]]:\n'
                  ' rest.append("new")\n'
                  ' print(first,rest)\n',
 'for_shared_iterator': 'rows=iter([(1,2,3),(4,5,6)])\n'
                        'for first,*rest in rows:print(first,rest)\n'
                        'print(list(rows))\n',
 'list_comprehension': 'print([(first,rest,last) for first,*rest,last in '
                       '[(1,2,3),(4,5)]])\n',
 'generator_sum': 'print(sum(first+sum(rest) for first,*rest in '
                  '[(1,2,3),(4,5)]))\n',
 'set_comprehension': 'print(sorted({first+sum(rest) for first,*rest in '
                      '[(1,2,3),(4,5)]}))\n',
 'dict_comprehension': 'print({first:rest for first,*rest in '
                       '[(1,2,3),(4,5)]})\n',
 'multiple_clauses': 'print([first+sum(rest)+other for first,*rest in '
                     '[(1,2,3),(4,5)] for other in range(2)])\n',
 'filters': 'print([rest for first,*rest in [(1,2,3),(4,5),(7,8,9)] if '
            'first%2])\n',
 'nested_pattern': 'print([(first,middle,rest) for first,(middle,*rest) in '
                   '[(1,(2,3,4)),(5,(6,7))]])\n',
 'comprehension_scope': 'rest="outside"\n'
                        'values=[rest for first,*rest in [(1,2,3),(4,5)]]\n'
                        'print(rest,values)\n',
 'late_bound_lambda': 'callbacks=[lambda:rest for first,*rest in '
                      '[(1,2,3),(4,5)]]\n'
                      'print([callback() for callback in callbacks])\n',
 'iterable_lookup_before_target': 'rest=[(1,2,3),(4,5)]\n'
                                  'print([rest for first,*rest in rest])\n'
                                  'print(rest)\n',
 'heterogeneous_rows': 'print([(first,rest,last) for first,*rest,last in '
                       '[(1,"x",None,True),(2,"y",False,False)]])\n',
 'unpack_error_in_list': 'print([rest for first,*rest,last in [(1,2),(3,)]])\n',
 'unpack_error_in_generator': 'print(sum(sum(rest) for first,*rest,last in '
                              '[(1,2),(3,)]))\n',
 'all_any_consumers': 'rows=[(1,2,3),(4,5)]\n'
                      'print(all(rest for first,*rest in rows),any(sum(rest)>5 '
                      'for first,*rest in rows))\n',
 'dict_items_targets': 'values={1:[2,3],4:[5,6]}\n'
                       'print([(key,rest) for key,*rest in values.items()])\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class StarComprehensionTargets(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_for_tuple_rows(self):self.check('for_tuple_rows')
    def test_for_list_rows(self):self.check('for_list_rows')
    def test_for_shared_iterator(self):self.check('for_shared_iterator')
    def test_list_comprehension(self):self.check('list_comprehension')
    def test_generator_sum(self):self.check('generator_sum')
    def test_set_comprehension(self):self.check('set_comprehension')
    def test_dict_comprehension(self):self.check('dict_comprehension')
    def test_multiple_clauses(self):self.check('multiple_clauses')
    def test_filters(self):self.check('filters')
    def test_nested_pattern(self):self.check('nested_pattern')
    def test_comprehension_scope(self):self.check('comprehension_scope')
    def test_late_bound_lambda(self):self.check('late_bound_lambda')
    def test_iterable_lookup_before_target(self):self.check('iterable_lookup_before_target')
    def test_heterogeneous_rows(self):self.check('heterogeneous_rows')
    def test_unpack_error_in_list(self):self.check('unpack_error_in_list')
    def test_unpack_error_in_generator(self):self.check('unpack_error_in_generator')
    def test_all_any_consumers(self):self.check('all_any_consumers')
    def test_dict_items_targets(self):self.check('dict_items_targets')


class StarComprehensionSelection(unittest.TestCase):
    def test_generator_logical_scope_selects_shared_target_frames(self):
        unit=build_program(CASES['generator_sum'],'star_generator_case.py').main
        self.assertIn('extended assignment unpacking',select_frames(unit).reasons)
