"""Deque indexed references preserve captured owners, raw indices and effects."""
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
import test_native_union_ordering as helpers

SOURCES={'monotonic_queue_class_pairs': 'from collections import deque\n'
                                'class Window:\n'
                                ' def __init__(self,width):\n'
                                '  self.width=width\n'
                                '  self.queue=deque()\n'
                                '  self.index=0\n'
                                ' def add(self,value):\n'
                                '  while self.queue and self.queue[-1][0]>=value:self.queue.pop()\n'
                                '  self.queue.append((value,self.index))\n'
                                '  if '
                                'self.queue[0][1]<=self.index-self.width:self.queue.popleft()\n'
                                '  self.index+=1\n'
                                '  return self.queue[0][0]\n'
                                'window=Window(3)\n'
                                'print([window.add(value)for value in[4,2,3,1,5,0,6]])\n',
 'fresh_random_monotonic_queue_argument': 'from collections import deque\n'
                                          'def windows(values,width,queue):\n'
                                          ' queue.clear()\n'
                                          ' answer=[]\n'
                                          ' for i,value in enumerate(values):\n'
                                          '  while queue and values[queue[-1]]<=value:queue.pop()\n'
                                          '  queue.append(i)\n'
                                          '  while queue[0]<=i-width:queue.popleft()\n'
                                          '  if i+1>=width:answer.append(values[queue[0]])\n'
                                          ' return answer\n'
                                          'queue=deque()\n'
                                          'for values in [[5, 2, -8, 5], [7, -9, 5, -8, 9, 4, 7, '
                                          '2, 8, -4, -6, 8, -8], [-6, -7, 7, -5, -6], [2], [-9, 0, '
                                          '-5, 1, 5, 7, -9, 3, -3, 1, 7, -1], [6], [-9, -6, 9, -8, '
                                          '-3, -2, 3, 1, -8, -3, 6, -2], [-4, -1, -3], [0, 9, -8, '
                                          '-4, 5, -8, -1, 5, -8, -2, 7, -5], [5, -5, -3, 8, 5, 0, '
                                          '-8, -9, 8, -3, 5, -1, 9, -3], [6, 1, -7], [9, -4, 2, '
                                          '-6, -8, 8, -5, -3, -9, -8, -5, -6], [7, 6, 7, -5, -6, '
                                          '-4, -5, 9, -4, -2], [-9, 7, -6, 2, -8, -7], [1, 4, 7, '
                                          '-6, -6, -9, -9, -7, 0, 5, 9], [1, -9], [-6, -5, 8, 5, '
                                          '-8, -9, -6], [9, 7, 4, 2, 2, -4, 3, 8, -9, 2, 0, -3, '
                                          '-3], [3, -7], [5, 3], [3, 0, -7, 5, 7, -9, -5, -8, 5, '
                                          '8, -4, 5, 3, 5], [0, -2, -9, 1, -9, -9, -3, 1, -9, -6, '
                                          '-7], [5, 0, -8, 5, 8, -2, -6], [4, 8]]:\n'
                                          ' for width in '
                                          'range(1,len(values)+1):print(windows(values,width,queue))\n',
 'assignment_rhs_before_owner_index': 'from collections import deque\n'
                                      'queue=deque([1,2,3,4])\n'
                                      'def right():\n'
                                      ' print("right",queue)\n'
                                      ' return queue.pop()\n'
                                      'def owner():\n'
                                      ' print("owner",queue)\n'
                                      ' return queue\n'
                                      'def index():\n'
                                      ' print("index",queue)\n'
                                      ' return queue.popleft()-1\n'
                                      'class Holder:\n'
                                      ' def run(self):owner()[index()]=right()\n'
                                      'Holder().run()\n'
                                      'print(queue)\n',
 'augassign_negative_index_recomputed_after_rhs': 'from collections import deque\n'
                                                  'class Holder:\n'
                                                  ' def run(self):\n'
                                                  '  queue=deque([10,20,30])\n'
                                                  '  queue[-1]+=queue.popleft()\n'
                                                  '  return queue\n'
                                                  'print(Holder().run())\n',
 'augassign_store_error_after_rhs_shrink': 'from collections import deque\n'
                                           'def right(queue):\n'
                                           ' value=queue.popleft()\n'
                                           ' print("right",queue)\n'
                                           ' return value\n'
                                           'class Holder:\n'
                                           ' def run(self):\n'
                                           '  queue=deque([10,20,30])\n'
                                           '  queue[2]+=right(queue)\n'
                                           'Holder().run()\n',
 'augassign_captured_owner_survives_global_rebind': 'from collections import deque\n'
                                                    'queue=deque([10,20])\n'
                                                    'def right():\n'
                                                    ' global queue\n'
                                                    ' old=queue\n'
                                                    ' queue=deque([99])\n'
                                                    ' print("right",old,queue)\n'
                                                    ' return 3\n'
                                                    'class Holder:\n'
                                                    ' def run(self):\n'
                                                    '  old=queue\n'
                                                    '  queue[0]+=right()\n'
                                                    '  return old,queue\n'
                                                    'print(Holder().run())\n',
 'deletion_indices_evaluate_left_to_right': 'from collections import deque\n'
                                            'def mark(label,index):\n'
                                            ' print(label,index)\n'
                                            ' return index\n'
                                            'class Holder:\n'
                                            ' def run(self):\n'
                                            '  queue=deque([0,1,2,3,4])\n'
                                            '  del '
                                            'queue[mark("first",1)],queue[mark("second",-1)]\n'
                                            '  return queue\n'
                                            'print(Holder().run())\n',
 'indexed_writes_change_element_types': 'from collections import deque\n'
                                        'def change(queue,index,value):queue[index]=value\n'
                                        'queue=deque([1,2])\n'
                                        'change(queue,0,"x")\n'
                                        'print(queue,queue[0],queue[-1])\n'
                                        'del queue[0]\n'
                                        'print(queue)\n',
 'indexed_list_augassign_keeps_child_alias': 'from collections import deque\n'
                                             'child=[1]\n'
                                             'queue=deque([child,[8]])\n'
                                             'queue[0]+=[2,3]\n'
                                             'queue[-1]*=2\n'
                                             'print(queue,child,queue[0]is child)\n',
 'wrong_deletion_index_after_successful_argument': 'from collections import deque\n'
                                                   'def erase(queue,index):del queue[index]\n'
                                                   'queue=deque([1,2,3])\n'
                                                   'erase(queue,0)\n'
                                                   'print(queue)\n'
                                                   'erase(queue,"x")\n',
 'augassign_index_expression_runs_once': 'from collections import deque\n'
                                         'queue=deque([10,20])\n'
                                         'def index():\n'
                                         ' print("index")\n'
                                         ' return 0\n'
                                         'def right():\n'
                                         ' print("right")\n'
                                         ' return 3\n'
                                         'class Holder:\n'
                                         ' def run(self):queue[index()]+=right()\n'
                                         'Holder().run()\n'
                                         'print(queue)\n'}

class NativeDequeIndexProofTests(unittest.TestCase):
    def test_ordinary_indexed_deque_keeps_the_existing_path(self):
        source='from collections import deque\nq=deque([1,2])\nq[-1]+=1\ndel q[0]\nprint(q[0])\n'
        with patch('py2fastrust.native_linked_frames.generate_linked',side_effect=AssertionError('ordinary deque redirected')):
            result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)

    def test_custom_index_protocol_is_a_positioned_boundary(self):
        source='from collections import deque\nclass Index:\n def __index__(self):return 0\nclass Holder:\n def run(self):return deque([3])[Index()]\nprint(Holder().run())\n'
        for mode in('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('__index__',str(result.diagnostics[0]))

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeDequeIndexExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise
    def compare(self,names):
        for name in names:
            with self.subTest(case=name):self.exercise(SOURCES[name],('',))
    def test_monotonic_windows_in_shared_function_and_class_queues(self):
        self.compare(('monotonic_queue_class_pairs','fresh_random_monotonic_queue_argument'))
    def test_assignment_evaluates_rhs_before_target(self):
        self.compare(('assignment_rhs_before_owner_index',))
    def test_augassign_normalizes_original_index_after_rhs(self):
        self.compare(('augassign_negative_index_recomputed_after_rhs','augassign_store_error_after_rhs_shrink','augassign_index_expression_runs_once'))
    def test_augassign_retains_owner_across_global_rebinding(self):
        self.compare(('augassign_captured_owner_survives_global_rebind',))
    def test_deletion_evaluation_and_index_errors(self):
        self.compare(('deletion_indices_evaluate_left_to_right','wrong_deletion_index_after_successful_argument'))
    def test_mutable_child_identity_and_element_type_changes(self):
        self.compare(('indexed_writes_change_element_types','indexed_list_augassign_keeps_child_alias'))

if __name__=='__main__':unittest.main()
