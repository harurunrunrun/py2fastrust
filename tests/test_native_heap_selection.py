"""Independent top-k route, key, storage and source-effect comparisons."""
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions, transpile
from tests import test_native_heapq as _heap

SOURCES = {'integer_counts_and_stable_ties': 'from heapq import nsmallest,nlargest\n'
                                   'values=[4,1,4,-2,8,1]\n'
                                   'for count in range(-2,9):\n'
                                   ' print(count,nsmallest(count,values),nlargest(count,values))\n'
                                   'print(values)\n',
 'stable_key_records_keep_original_identity': 'from heapq import nlargest,nsmallest\n'
                                              'rows=[[1,10],[2,20],[1,30],[2,40],[3,50]]\n'
                                              'for count in [1,2,3,5,8]:\n'
                                              ' result=nlargest(count,rows,key=lambda row:row[0])\n'
                                              ' print(result,result[0] is rows[4])\n'
                                              ' result=nsmallest(count,rows,key=lambda '
                                              'row:row[0])\n'
                                              ' print(result,result[0] is rows[0])\n'
                                              'result=nlargest(2,rows,key=lambda row:row[0])\n'
                                              'result[0][1]=99\n'
                                              'print(rows)\n',
 'live_bounded_source_appends_from_key': 'from heapq import nlargest\n'
                                         'rows=[4,1,3,2]\n'
                                         'def key(value):\n'
                                         " print('key',value)\n"
                                         ' if len(rows)<7:rows.append(value+10)\n'
                                         ' return value\n'
                                         'print(nlargest(2,rows,key=key))\n'
                                         'print(rows)\n',
 'known_length_sorted_path_snapshots_before_keys': 'from heapq import nsmallest\n'
                                                   'rows=[4,1,3,2]\n'
                                                   'def key(value):\n'
                                                   " print('key',value)\n"
                                                   ' rows.append(value+10)\n'
                                                   ' return value\n'
                                                   'print(nsmallest(4,rows,key=key))\n'
                                                   'print(rows)\n',
 'one_candidate_route_skips_length_snapshot': 'from heapq import nlargest\n'
                                              'rows=[4,1,3]\n'
                                              'def key(value):\n'
                                              " print('key',value)\n"
                                              ' if len(rows)<5:rows.append(value+10)\n'
                                              ' return value\n'
                                              'print(nlargest(1,rows,key=key))\n'
                                              'print(rows)\n',
 'zero_and_negative_counts_do_not_pull': 'from heapq import nlargest,nsmallest\n'
                                         'def probe(value):\n'
                                         " print('pull',value)\n"
                                         ' return value\n'
                                         'source=map(probe,[4,1,3])\n'
                                         'print(nlargest(0,source,key=7))\n'
                                         'print(nsmallest(-2,source,key=7))\n'
                                         'print(next(source))\n',
 'initial_heap_errors_follow_initial_batch_keys': 'from heapq import nsmallest\n'
                                                  'def key(value):\n'
                                                  " print('key',value)\n"
                                                  ' return None if value==1 else value\n'
                                                  "print('before')\n"
                                                  'nsmallest(3,iter([4,1,3,8]),key=key)\n',
 'bound_key_updates_state_in_outer_loop': 'from heapq import nlargest\n'
                                          'class Rank:\n'
                                          ' def __init__(self):self.calls=0\n'
                                          ' def key(self,value):\n'
                                          '  self.calls+=1\n'
                                          '  return value\n'
                                          ' def run(self):\n'
                                          '  for unused in range(2):\n'
                                          '   print(self.calls)\n'
                                          '   print(nlargest(2,[4,1,8,3],key=self.key))\n'
                                          '   print(self.calls)\n'
                                          'Rank().run()\n',
 'immediate_generator_key_order': 'from heapq import nsmallest\n'
                                  'def pull(value):\n'
                                  " print('pull',value)\n"
                                  ' return value\n'
                                  'def key(value):\n'
                                  " print('key',value)\n"
                                  ' return -value\n'
                                  'print(nsmallest(2,(pull(value)for value in '
                                  'range(5)),key=key))\n',
 'mutable_key_result_is_not_copied': 'from heapq import nsmallest\n'
                                     'scores=[[5],[2],[4],[1]]\n'
                                     'rows=[0,1,2,3]\n'
                                     'def key(value):\n'
                                     ' if value==3:scores[0][0]=0\n'
                                     ' return scores[value]\n'
                                     'print(nsmallest(2,rows,key=key))\n',
 'nested_live_key_result_and_sorted_consumer': 'from heapq import nsmallest\n'
                                               'scores=[[[5]],[[2]],[[4]],[[1]]]\n'
                                               'def key(value):\n'
                                               ' if value==3:scores[0][0][0]=0\n'
                                               ' return scores[value]\n'
                                               'print(nsmallest(2,iter([0,1,2,3]),key=key))\n'
                                               'print(sorted([0,1,2,3],key=key))\n',
 'range_length_overflow_precedes_zero_count': 'from heapq import nsmallest\n'
                                              "print('before')\n"
                                              'print(nsmallest(0,range(-9223372036854775808,9223372036854775807)))\n',
 'one_count_skips_range_length_overflow': 'from heapq import nlargest\n'
                                          'def key(value):\n'
                                          " print('key',value)\n"
                                          ' return 1//0\n'
                                          'nlargest(1,range(-9223372036854775808,9223372036854775807),key=key)\n'}

EMPTY_SOURCE_CASES = {'zero_empty_strict_map_has_no_pull': 'from heapq import nlargest\n'
                                      'source=map(lambda a,b:a+b,[],[1],strict=True)\n'
                                      'print(nlargest(0,source))\n'
                                      "print('after')\n",
 'negative_empty_strict_zip_has_no_pull': 'from heapq import nsmallest\n'
                                          'source=zip([],[1],strict=True)\n'
                                          'print(nsmallest(-3,source,key=7))\n'
                                          "print('after')\n",
 'zero_immediate_generator_over_empty_strict_zip': 'from heapq import nlargest\n'
                                                   'print(nlargest(0,(value for value in '
                                                   'zip([],[1],strict=True))))\n'
                                                   "print('after')\n",
 'positive_empty_strict_zip_still_raises_on_pull': 'from heapq import nlargest\n'
                                                   "print('before')\n"
                                                   'print(nlargest(2,zip([],[1],strict=True),key=7))\n'}

EMPTY_SOURCE_CASES.update({'zero_tuple_bottom_zip': 'from heapq import nlargest\n'
                          'print(nlargest(0,zip((),[1],strict=True)))\n'
                          'print("after")\n',
 'zero_tuple_bottom_map': 'from heapq import nsmallest\n'
                          'print(nsmallest(0,map(lambda a,b:a,(),[1],strict=True)))\n'
                          'print("after")\n'})

class HeapSelectionProofTests(unittest.TestCase):
    def test_float_decoration_and_custom_count_boundaries_are_positioned(self):
        sources = [
            "from heapq import nlargest\nprint(nlargest(2,[float('nan'),1.0]))\n",
            "from heapq import nsmallest\nclass Count:\n def __index__(self):return 2\nprint(nsmallest(Count(),[3,1,2]))\n",
        ]
        for source in sources:
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)

@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class HeapSelectionExecutionTests(unittest.TestCase):
    def compare(self, source):
        return _heap.HeapExecutionTests.compare(self,source)

    def test_integer_counts_and_stable_ties(self):
        self.compare(SOURCES['integer_counts_and_stable_ties'])

    def test_stable_key_records_keep_original_identity(self):
        self.compare(SOURCES['stable_key_records_keep_original_identity'])

    def test_live_bounded_source_appends_from_key(self):
        self.compare(SOURCES['live_bounded_source_appends_from_key'])

    def test_known_length_sorted_path_snapshots_before_keys(self):
        self.compare(SOURCES['known_length_sorted_path_snapshots_before_keys'])

    def test_one_candidate_route_skips_length_snapshot(self):
        self.compare(SOURCES['one_candidate_route_skips_length_snapshot'])

    def test_zero_and_negative_counts_do_not_pull(self):
        self.compare(SOURCES['zero_and_negative_counts_do_not_pull'])

    def test_initial_heap_errors_follow_initial_batch_keys(self):
        self.compare(SOURCES['initial_heap_errors_follow_initial_batch_keys'])

    def test_bound_key_updates_state_in_outer_loop(self):
        self.compare(SOURCES['bound_key_updates_state_in_outer_loop'])

    def test_immediate_generator_key_order(self):
        self.compare(SOURCES['immediate_generator_key_order'])

    def test_mutable_key_result_is_not_copied(self):
        self.compare(SOURCES['mutable_key_result_is_not_copied'])

    def test_nested_live_key_result_and_sorted_consumer(self):
        self.compare(SOURCES['nested_live_key_result_and_sorted_consumer'])

    def test_range_length_overflow_precedes_zero_count(self):
        self.compare(SOURCES['range_length_overflow_precedes_zero_count'])

    def test_one_count_skips_range_length_overflow(self):
        self.compare(SOURCES['one_count_skips_range_length_overflow'])

    def test_empty_output_cursors_preserve_zero_pull_and_error_protocols(self):
        for source in EMPTY_SOURCE_CASES.values():
            self.compare(source)

if __name__=='__main__':
    unittest.main()
