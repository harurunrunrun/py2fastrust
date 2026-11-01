"""Live shared deque consumers preserve source ownership and mutation state."""
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
import test_native_union_ordering as helpers

SOURCES={'shared_consumers_and_comprehensions': 'from collections import deque\n'
                                        'class Holder:\n'
                                        ' def run(self):\n'
                                        '  queue=deque([1,2,3])\n'
                                        '  return '
                                        'list(queue),tuple(queue),sum(queue),min(queue),max(queue),any(queue),all(queue),sorted(queue),[x*2 '
                                        'for x in queue],sum(x+1 for x in queue)\n'
                                        'print(Holder().run())\n',
 'saved_cursor_aliases_share_position': 'from collections import deque\n'
                                        'class Holder:\n'
                                        ' def run(self):\n'
                                        '  queue=deque([1,2,3])\n'
                                        '  first=iter(queue)\n'
                                        '  second=first\n'
                                        '  return '
                                        'next(first),next(second),list(first),list(second),list(queue)\n'
                                        'print(Holder().run())\n',
 'index_replacement_is_live_without_invalidation': 'from collections import deque\n'
                                                   'class Holder:\n'
                                                   ' def run(self):\n'
                                                   '  queue=deque([1,2,3])\n'
                                                   '  cursor=iter(queue)\n'
                                                   '  print(next(cursor))\n'
                                                   '  queue[1]=8\n'
                                                   '  queue[-1]+=2\n'
                                                   '  print(next(cursor),list(cursor),queue)\n'
                                                   'Holder().run()\n',
 'append_alias_invalidates_cursor': 'from collections import deque\n'
                                    'def change(queue):queue.append(4)\n'
                                    'queue=deque([1,2,3])\n'
                                    'first=iter(queue)\n'
                                    'print(next(first))\n'
                                    'change(queue)\n'
                                    'print(next(first))\n',
 'exhausted_forward_cursor_still_checks_mutation': 'from collections import deque\n'
                                                   'queue=deque([1])\n'
                                                   'cursor=iter(queue)\n'
                                                   'print(next(cursor),next(cursor,"done"))\n'
                                                   'queue.append(2)\n'
                                                   'print(next(cursor,"wrong"))\n',
 'zero_maxlen_extend_consumes_without_state_change': 'from collections import deque\n'
                                                     'def mark(value):\n'
                                                     ' print("item",value)\n'
                                                     ' return value\n'
                                                     'queue=deque(maxlen=0)\n'
                                                     'cursor=iter(queue)\n'
                                                     'queue.extend(mark(i)for i in range(3))\n'
                                                     'queue.extendleft(mark(i)for i in range(2))\n'
                                                     'print(next(cursor,"done"),queue)\n',
 'zero_maxlen_append_invalidates_empty_cursor': 'from collections import deque\n'
                                                'queue=deque(maxlen=0)\n'
                                                'cursor=iter(queue)\n'
                                                'queue.append(1)\n'
                                                'next(cursor)\n',
 'extend_alias_self_snapshot': 'from collections import deque\n'
                               'class Holder:\n'
                               ' def run(self):\n'
                               '  queue=deque([1,2],maxlen=5)\n'
                               '  alias=queue\n'
                               '  alias.extend(queue)\n'
                               '  print(queue)\n'
                               '  queue.extendleft(alias)\n'
                               '  print(alias)\n'
                               'Holder().run()\n',
 'extend_iterator_is_live_and_raises': 'from collections import deque\n'
                                       'queue=deque([1,2])\n'
                                       'alias=queue\n'
                                       'print(queue)\n'
                                       'queue.extend(iter(alias))\n'
                                       'print("wrong")\n',
 'generator_item_mutates_receiver_before_append': 'from collections import deque\n'
                                                  'def extend(queue):\n'
                                                  ' queue.extend(queue.popleft()for _ in '
                                                  'range(2))\n'
                                                  ' queue.extendleft(queue.pop()for _ in '
                                                  'range(2))\n'
                                                  ' return queue\n'
                                                  'print(extend(deque([1,2,3])))\n',
 'finite_union_sources_include_deque_list_range': 'from collections import deque\n'
                                                  'queue=deque([1,2])\n'
                                                  'def choose(flag):\n'
                                                  ' if flag==0:return queue\n'
                                                  ' if flag==1:return [7,8]\n'
                                                  ' return range(3,5)\n'
                                                  'class Holder:\n'
                                                  ' def run(self,source):return list(map(lambda '
                                                  'x:x+10,source)),list(zip(source,[9,8]))\n'
                                                  'holder=Holder()\n'
                                                  'print(holder.run(choose(0)),holder.run(choose(1)),holder.run(choose(2)))\n',
 'starred_print_and_enumeration': 'from collections import deque\n'
                                  'class Holder:\n'
                                  ' def run(self):\n'
                                  '  queue=deque([2,4,6])\n'
                                  '  print(*queue,sep="|")\n'
                                  '  return [(i,value)for i,value in enumerate(queue,3)]\n'
                                  'print(Holder().run())\n'}

class NativeDequeCursorProofTests(unittest.TestCase):
    def test_nonmutating_unique_owner_iteration_keeps_ordinary_lowering(self):
        source='from collections import deque\nqueue=deque([1,2])\nqueue.append(3)\nfor value in queue:print(value)\n'
        with patch('py2fastrust.native_linked_frames.generate_linked',side_effect=AssertionError('ordinary deque iteration redirected')):
            result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)

    def test_cursor_deque_cycle_has_a_positioned_collection_diagnostic(self):
        source='from collections import deque\nqueue=deque()\ncursor=iter(queue)\nqueue.append(cursor)\nprint(len(queue))\n'
        for mode in('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('cycle',str(result.diagnostics[0]))

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeDequeCursorExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise
    def compare(self,names):
        for name in names:
            with self.subTest(case=name):self.exercise(SOURCES[name],('',))
    def test_shared_collection_reduction_and_comprehension_consumers(self):
        self.compare(('shared_consumers_and_comprehensions','saved_cursor_aliases_share_position'))
    def test_live_replacement_and_structural_mutation(self):
        self.compare(('index_replacement_is_live_without_invalidation','append_alias_invalidates_cursor','exhausted_forward_cursor_still_checks_mutation'))
    def test_zero_bound_extension_and_append_have_distinct_mutation_rules(self):
        self.compare(('zero_maxlen_extend_consumes_without_state_change','zero_maxlen_append_invalidates_empty_cursor'))
    def test_self_snapshot_is_based_on_object_identity_and_iterators_remain_live(self):
        self.compare(('extend_alias_self_snapshot','extend_iterator_is_live_and_raises'))
    def test_generator_item_runs_before_receiver_borrow(self):
        self.compare(('generator_item_mutates_receiver_before_append',))
    def test_finite_source_union_and_nested_enumeration_keep_registered_cursors(self):
        self.compare(('finite_union_sources_include_deque_list_range','starred_print_and_enumeration'))

if __name__=='__main__':unittest.main()
