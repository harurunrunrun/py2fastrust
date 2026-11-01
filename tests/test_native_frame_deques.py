"""Shared native deque arguments/fields retain bounded queue and alias semantics."""
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
import test_native_union_ordering as helpers

SOURCES={'bfs_queue_function_argument': 'from collections import deque\n'
                                'def search(graph,queue,distance):\n'
                                ' while queue:\n'
                                '  vertex=queue.popleft()\n'
                                '  for neighbor in graph[vertex]:\n'
                                '   if distance[neighbor]<0:\n'
                                '    distance[neighbor]=distance[vertex]+1\n'
                                '    queue.append(neighbor)\n'
                                ' return distance\n'
                                'graph=[[1,2],[2,3],[3],[],[0]]\n'
                                'queue=deque([0])\n'
                                'print(search(graph,queue,[0,-1,-1,-1,-1]),len(queue))\n',
 'bfs_queue_class_field': 'from collections import deque\n'
                          'class Search:\n'
                          ' def __init__(self,graph):\n'
                          '  self.graph=graph\n'
                          '  self.queue=deque()\n'
                          ' def run(self,start):\n'
                          '  distance=[-1]*len(self.graph)\n'
                          '  distance[start]=0\n'
                          '  self.queue.append(start)\n'
                          '  while self.queue:\n'
                          '   vertex=self.queue.popleft()\n'
                          '   for neighbor in self.graph[vertex]:\n'
                          '    if distance[neighbor]<0:\n'
                          '     distance[neighbor]=distance[vertex]+1\n'
                          '     self.queue.append(neighbor)\n'
                          '  return distance\n'
                          'search=Search([[1,2],[2,3],[3],[]])\n'
                          'print(search.run(0),search.run(2))\n',
 'pair_queue_across_functions': 'from collections import deque\n'
                                'def append(queue,pair):queue.append(pair)\n'
                                'def take(queue):return queue.popleft()\n'
                                'class Search:\n'
                                ' def __init__(self):self.queue=deque([(0,0)])\n'
                                ' def run(self):\n'
                                '  answer=0\n'
                                '  while self.queue:\n'
                                '   vertex,depth=take(self.queue)\n'
                                '   answer+=vertex\n'
                                '   if depth<3:\n'
                                '    append(self.queue,(vertex+1,depth+1))\n'
                                '    append(self.queue,(vertex+2,depth+1))\n'
                                '  return answer\n'
                                'print(Search().run())\n',
 'nullable_maxlen_and_copy': 'from collections import deque\n'
                             'class Holder:\n'
                             ' def run(self,bound=None):\n'
                             '  queue=deque([1,2,3],maxlen=bound)\n'
                             '  alias=queue\n'
                             '  queue.append(4)\n'
                             '  alias.appendleft(0)\n'
                             '  copy=queue.copy()\n'
                             '  copy.clear()\n'
                             '  copy.append(9)\n'
                             '  return queue,copy,queue.maxlen,copy.maxlen,copy is queue\n'
                             'holder=Holder()\n'
                             'print(holder.run(),holder.run(2),holder.run(0))\n',
 'constructor_alias_local_import_and_return': 'import collections as containers\n'
                                              'def create(values):\n'
                                              ' from collections import deque as fifo\n'
                                              ' constructor=fifo\n'
                                              ' return constructor(values)\n'
                                              'def mutate(queue):\n'
                                              ' queue.appendleft(8)\n'
                                              ' return queue.pop()\n'
                                              'class Holder:\n'
                                              ' def run(self):\n'
                                              '  queue=create([1,2])\n'
                                              '  alias=queue\n'
                                              '  print(alias is queue,mutate(alias),queue)\n'
                                              '  other=containers.deque([9])\n'
                                              '  print(mutate(other),other)\n'
                                              'Holder().run()\n',
 'clear_return_value_and_copy_independence': 'from collections import deque\n'
                                             'class Holder:\n'
                                             ' def run(self):\n'
                                             '  queue=deque([1,2])\n'
                                             '  alias=queue\n'
                                             '  other=queue.copy()\n'
                                             '  print(alias.clear(),queue,other)\n'
                                             '  alias.appendleft(3)\n'
                                             '  print(queue,other,alias is queue,other is '
                                             'queue)\n'
                                             'Holder().run()\n',
 'method_receiver_captured_before_argument_rebind': 'from collections import deque\n'
                                                    'queue=deque([1])\n'
                                                    'def replacement():\n'
                                                    ' global queue\n'
                                                    ' old=queue\n'
                                                    ' queue=deque([9])\n'
                                                    ' old.appendleft(2)\n'
                                                    ' print("item",old,queue)\n'
                                                    ' return 3\n'
                                                    'class Holder:\n'
                                                    ' def run(self):\n'
                                                    '  alias=queue\n'
                                                    '  queue.append(replacement())\n'
                                                    '  return alias,queue\n'
                                                    'print(Holder().run())\n',
 'empty_pop_after_successful_alias_call': 'from collections import deque\n'
                                          'def take(queue):return queue.popleft()\n'
                                          'queue=deque([2])\n'
                                          'print(take(queue),queue)\n'
                                          'take(queue)\n',
 'class_wrong_bound_type_after_effects': 'from collections import deque\n'
                                         'def mark(label,value):\n'
                                         ' print(label)\n'
                                         ' return value\n'
                                         'class Holder:\n'
                                         ' def run(self):return '
                                         'deque(mark("source",[1,2]),maxlen=mark("bound","3"))\n'
                                         'Holder().run()\n',
 'mutable_payload_copy_keeps_child_identity': 'from collections import deque\n'
                                              'class Holder:\n'
                                              ' def run(self,payload):\n'
                                              '  queue=deque([payload])\n'
                                              '  copy=queue.copy()\n'
                                              '  first=queue.popleft()\n'
                                              '  second=copy.pop()\n'
                                              '  first.append(7)\n'
                                              '  return first is '
                                              'second,first,payload,queue,copy\n'
                                              'print(Holder().run([1]))\n',
 'class_isinstance_deque_alias': 'import collections\n'
                                 'class Holder:\n'
                                 ' def run(self):\n'
                                 '  factory=collections.deque\n'
                                 '  first=factory([1])\n'
                                 '  return '
                                 'isinstance(first,factory),isinstance([],factory),first\n'
                                 'print(Holder().run())\n'}

SOURCES['acyclic_closure_reads_shared_deque']='from collections import deque\ndef reader(queue):\n def read():return len(queue)\n return read\nqueue=deque([1])\nread=reader(queue)\nprint(read())\nqueue.append(2)\nprint(read(),queue)\n'

class NativeFrameDequeProofTests(unittest.TestCase):
    def test_shared_deque_cycles_keep_a_positioned_ownership_diagnostic(self):
        for source in('from collections import deque\ndef make():\n queue=deque()\n def read():return len(queue)\n queue.append(read)\n return queue\nprint(len(make()))\n','from collections import deque\nclass Holder:\n def __init__(self):\n  self.queue=deque()\n  self.queue.append(self)\nprint(len(Holder().queue))\n'):
            for mode in('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertGreater(result.diagnostics[0].line,0)
                self.assertIn('cycle',str(result.diagnostics[0]))

    def test_unique_owner_keeps_the_direct_vecdeque_path(self):
        with patch('py2fastrust.native_linked_frames.generate_linked',side_effect=AssertionError('ordinary deque was redirected')):
            result=transpile('from collections import deque\nq=deque([1,2])\nq.append(3)\nprint(q.popleft(),q)\n')
        self.assertTrue(result.success,result.diagnostics)

    def test_shared_cursor_and_bound_method_gaps_are_positioned(self):
        for source,detail in(
            ('from collections import deque\nclass Q:\n def run(self):return list(deque([1,2]))\nprint(Q().run())\n','iteration'),
            ('from collections import deque\nclass Q:\n def run(self):\n  q=deque([1,2])\n  q.extend(q)\nQ().run()\n','deque.extend'),
            ('from collections import deque\nclass Q:\n def run(self):\n  q=deque([1])\n  method=q.append\nQ().run()\n','attribute')):
            for mode in('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertGreater(result.diagnostics[0].line,0)
                self.assertIn(detail,str(result.diagnostics[0]))

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeFrameDequeExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise
    def compare(self,names):
        for name in names:
            with self.subTest(case=name):self.exercise(SOURCES[name],('',))
    def test_acyclic_closure_keeps_its_deque_owner(self):
        self.compare(('acyclic_closure_reads_shared_deque',))
    def test_bfs_queues_cross_functions_and_fields(self):
        self.compare(('bfs_queue_function_argument','bfs_queue_class_field','pair_queue_across_functions'))
    def test_nullable_bounds_and_copy_aliases(self):
        self.compare(('nullable_maxlen_and_copy','constructor_alias_local_import_and_return','clear_return_value_and_copy_independence'))
    def test_receiver_survives_argument_rebinding(self):
        self.compare(('method_receiver_captured_before_argument_rebind',))
    def test_empty_pop_and_bad_bound_keep_error_order(self):
        self.compare(('empty_pop_after_successful_alias_call','class_wrong_bound_type_after_effects'))
    def test_copy_retains_mutable_child_identity(self):
        self.compare(('mutable_payload_copy_keeps_child_identity',))
    def test_canonical_constructor_type_identity(self):
        self.compare(('class_isinstance_deque_alias',))

if __name__=='__main__':unittest.main()
