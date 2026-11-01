"""Captured key callbacks, mutation and binary-search work against CPython."""
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from tests import test_native_heapq as _heap

SOURCES = {'key_visits_only_binary_search_midpoints': 'from bisect import bisect_left,bisect_right\n'
                                            'def key(value):\n'
                                            ' print("key",value)\n'
                                            ' return value\n'
                                            'rows=[0,10,20,30,40,50,60,70,80]\n'
                                            'print("left",bisect_left(rows,35,key=key))\n'
                                            'print("right",bisect_right(rows,40,key=key))\n',
 'insort_new_key_once_before_visited_elements': 'from bisect import insort_left\n'
                                                'def key(row):\n'
                                                ' print("key",row[1])\n'
                                                ' return row[0]\n'
                                                'rows=[(1,"a"),(4,"b"),(9,"c")]\n'
                                                'insort_left(rows,(5,"new"),key=key)\n'
                                                'print(rows)\n',
 'insort_retains_original_payload_and_tie_direction': 'from bisect import '
                                                      'insort_left,insort_right\n'
                                                      'left=[(1,"a"),(3,"b"),(3,"c"),(7,"d")]\n'
                                                      'right=left.copy()\n'
                                                      'print(insort_left(left,(3,"new"),key=lambda '
                                                      'row:row[0]))\n'
                                                      'print(insort_right(right,(3,"new"),key=lambda '
                                                      'row:row[0]))\n'
                                                      'print(left,right)\n',
 'bound_method_key_mutates_state_across_loop_iterations': 'from bisect import bisect_left\n'
                                                          'class State:\n'
                                                          ' def __init__(self):self.calls=0\n'
                                                          ' def key(self,row):\n'
                                                          '  self.calls+=1\n'
                                                          '  return row[0]\n'
                                                          ' def run(self):\n'
                                                          '  rows=[(1,2),(3,4),(5,6)]\n'
                                                          '  for i in range(3):\n'
                                                          '   '
                                                          'print(self.calls,bisect_left(rows,i,key=self.key),self.calls)\n'
                                                          'State().run()\n',
 'closure_key_keeps_definition_time_state': 'from bisect import bisect_right\n'
                                            'def make(offset):\n'
                                            ' def key(row):return row[0]+offset\n'
                                            ' return key\n'
                                            'key=make(10)\n'
                                            'print(bisect_right([(1,),(3,),(5,)],13,key=key))\n',
 'finite_key_none_or_builtin_dispatch': 'from bisect import bisect_left,insort_right\n'
                                        'def run(flag):\n'
                                        ' key=abs if flag else None\n'
                                        ' rows=[1,2,3]\n'
                                        ' result=bisect_left(rows,2,key=key)\n'
                                        ' insort_right(rows,2,key=key)\n'
                                        ' return result,rows\n'
                                        'print(run(False),run(True))\n',
 'key_clear_releases_borrow_and_preserves_next_index_error': 'from bisect import bisect_left\n'
                                                             'rows=[1,3,5,7]\n'
                                                             'def key(value):\n'
                                                             ' rows.clear()\n'
                                                             ' print("key",value)\n'
                                                             ' return value\n'
                                                             'print(bisect_left(rows,0,key=key))\n',
 'insort_new_key_mutation_precedes_default_length': 'from bisect import insort_left\n'
                                                    'rows=[(1,"a"),(3,"b")]\n'
                                                    'def key(row):\n'
                                                    ' print("key",row[1])\n'
                                                    ' if row[1]=="new":rows.append((9,"added"))\n'
                                                    ' return row[0]\n'
                                                    'insort_left(rows,(8,"new"),key=key)\n'
                                                    'print(rows)\n',
 'key_binding_rebound_midsearch_uses_original_callable': 'from bisect import bisect_left\n'
                                                         'def replacement(value):\n'
                                                         ' print("wrong replacement")\n'
                                                         ' return value\n'
                                                         'def original(value):\n'
                                                         ' global key\n'
                                                         ' key=replacement\n'
                                                         ' print("original",value)\n'
                                                         ' return value\n'
                                                         'key=original\n'
                                                         'print(bisect_left([1,3,5],4,key=key))\n',
 'callback_stopiteration_is_not_iterator_termination': 'from bisect import bisect_left\n'
                                                       'def key(value):return next(iter(()))\n'
                                                       'print(bisect_left([1,2,3],2,key=key))\n'}

class BisectKeyProofTests(unittest.TestCase):
    def test_explicit_none_retains_the_ordinary_vector_path(self):
        source = 'from bisect import bisect_left\nprint(bisect_left([1,3],2,key=None))\n'
        for mode in ('i64','i128','bigint'):
            with self.subTest(mode=mode):
                with patch('py2fastrust.native_linked_frames.generate_linked', side_effect=AssertionError('ordinary bisection redirected')):
                    result = transpile(source, TranspileOptions(integer=mode))
                self.assertTrue(result.success, result.diagnostics)

@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class BisectKeyExecutionTests(unittest.TestCase):
    def compare(self, source):
        return _heap.HeapExecutionTests.compare(self, source)

    def test_key_visits_only_binary_search_midpoints(self):
        self.compare(SOURCES['key_visits_only_binary_search_midpoints'])

    def test_insort_new_key_once_before_visited_elements(self):
        self.compare(SOURCES['insort_new_key_once_before_visited_elements'])

    def test_insort_retains_original_payload_and_tie_direction(self):
        self.compare(SOURCES['insort_retains_original_payload_and_tie_direction'])

    def test_bound_method_key_mutates_state_across_loop_iterations(self):
        self.compare(SOURCES['bound_method_key_mutates_state_across_loop_iterations'])

    def test_closure_key_keeps_definition_time_state(self):
        self.compare(SOURCES['closure_key_keeps_definition_time_state'])

    def test_finite_key_none_or_builtin_dispatch(self):
        self.compare(SOURCES['finite_key_none_or_builtin_dispatch'])

    def test_key_clear_releases_borrow_and_preserves_next_index_error(self):
        self.compare(SOURCES['key_clear_releases_borrow_and_preserves_next_index_error'])

    def test_insort_new_key_mutation_precedes_default_length(self):
        self.compare(SOURCES['insort_new_key_mutation_precedes_default_length'])

    def test_key_binding_rebound_midsearch_uses_original_callable(self):
        self.compare(SOURCES['key_binding_rebound_midsearch_uses_original_callable'])

    def test_callback_stopiteration_is_not_iterator_termination(self):
        self.compare(SOURCES['callback_stopiteration_is_not_iterator_termination'])

if __name__ == '__main__':
    unittest.main()
