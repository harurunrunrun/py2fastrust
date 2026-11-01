"""Reverse source providers preserve native sequence ownership and endpoints."""
import shutil
import unittest
from unittest.mock import patch
from py2fastrust import transpile
import test_native_union_ordering as helpers

SOURCES={'circular_queue_class_and_aliases': 'from collections import deque\n'
                                     'class Ring:\n'
                                     ' def __init__(self,values):self.values=deque(values)\n'
                                     ' def move(self,amount):\n'
                                     '  self.values.rotate(amount)\n'
                                     '  return tuple(self.values)\n'
                                     ' def flip(self):\n'
                                     '  alias=self.values\n'
                                     '  alias.reverse()\n'
                                     '  return tuple(self.values)\n'
                                     'ring=Ring([1,2,3,4,5])\n'
                                     'print(ring.move(2),ring.move(-7),ring.flip(),ring.move(True))\n',
 'rotate_zero_invalidates_forward_cursor': 'from collections import deque\n'
                                           'queue=deque([1,2,3])\n'
                                           'cursor=iter(queue)\n'
                                           'print(next(cursor))\n'
                                           'queue.rotate(0)\n'
                                           'print(next(cursor))\n',
 'reverse_is_visible_to_both_cursor_directions': 'from collections import deque\n'
                                                 'queue=deque([1,2,3,4])\n'
                                                 'forward=iter(queue)\n'
                                                 'backward=reversed(queue)\n'
                                                 'print(next(forward),next(backward))\n'
                                                 'queue.reverse()\n'
                                                 'print(list(forward),list(backward),queue)\n',
 'reversed_after_last_item_is_sticky': 'from collections import deque\n'
                                       'queue=deque([1])\n'
                                       'cursor=reversed(queue)\n'
                                       'print(next(cursor))\n'
                                       'queue.append(2)\n'
                                       'print(next(cursor,"end"),list(cursor))\n',
 'reversed_finite_deque_families_and_consumers': 'from collections import deque\n'
                                                 'def choose(flag):\n'
                                                 ' if flag:return deque([1,2,3])\n'
                                                 ' return deque([7,8])\n'
                                                 'def show(queue):\n'
                                                 ' return '
                                                 'list(reversed(queue)),sum(reversed(queue)),list(zip(reversed(queue),queue))\n'
                                                 'print(show(choose(True)),show(choose(False)))\n',
 'rotate_captured_receiver_before_argument_rebind': 'from collections import deque\n'
                                                    'queue=deque([1,2,3])\n'
                                                    'def amount():\n'
                                                    ' global queue\n'
                                                    ' queue=deque([8,9])\n'
                                                    ' print("argument")\n'
                                                    ' return -1\n'
                                                    'class Holder:\n'
                                                    ' def run(self):\n'
                                                    '  alias=queue\n'
                                                    '  queue.rotate(amount())\n'
                                                    '  return alias,queue\n'
                                                    'print(Holder().run())\n',
 'reverse_list_initial_endpoint_and_live_replacement': 'class Holder:\n'
                                                       ' def run(self):\n'
                                                       '  values=[1,2,3]\n'
                                                       '  cursor=reversed(values)\n'
                                                       '  values.append(9)\n'
                                                       '  values[1]=8\n'
                                                       '  return next(cursor),list(cursor),values\n'
                                                       'print(Holder().run())\n',
 'reverse_list_shrink_latches_exhaustion': 'class Holder:\n'
                                           ' def run(self):\n'
                                           '  values=[1,2,3]\n'
                                           '  cursor=reversed(values)\n'
                                           '  values.pop()\n'
                                           '  print(next(cursor,"end"))\n'
                                           '  values.append(9)\n'
                                           '  return next(cursor,"still end"),values\n'
                                           'print(Holder().run())\n',
 'reverse_range_huge_length_without_materialization': 'class Holder:\n'
                                                      ' def run(self):\n'
                                                      '  cursor=reversed(range(-(1<<62),1<<62))\n'
                                                      '  return '
                                                      'next(cursor),next(cursor),next(cursor)\n'
                                                      'print(Holder().run())\n',
 'reverse_range_large_steps': 'class Holder:\n'
                              ' def run(self):\n'
                              '  return '
                              'list(reversed(range(-10**15,10**15,10**15-1))),list(reversed(range(10**15,-10**15,-10**15+1)))\n'
                              'print(Holder().run())\n',
 'shared_finite_builtin_source_families': 'class Holder:\n'
                                          ' def collect(self,source):return '
                                          'list(reversed(source))\n'
                                          'holder=Holder()\n'
                                          'print(holder.collect([1,2,3]),holder.collect((4,5)),holder.collect(range(1,8,2)),holder.collect("abcd"),holder.collect(b"ABC"))\n',
 'unicode_reverse_walks_codepoint_boundaries': 'class Holder:\n'
                                               ' def run(self,text):return '
                                               'list(reversed(text)),list(zip(text,reversed(text)))\n'
                                               'print(Holder().run("aé東京🙂é"))\n'}

class NativeReverseIteratorProofTests(unittest.TestCase):
    def test_ordinary_immediate_reverse_stream_keeps_direct_lowering(self):
        source='from collections import deque\nqueue=deque([1,2,3])\nfor value in reversed(queue):print(value)\nqueue.reverse()\nprint(queue)\n'
        with patch('py2fastrust.native_linked_frames.generate_linked',side_effect=AssertionError('ordinary reverse stream redirected')):
            result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeReverseIteratorExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise
    def compare(self,names,*,string_mode='ascii'):
        for name in names:
            with self.subTest(case=name):self.exercise(SOURCES[name],('',),string_mode=string_mode)
    def test_rotate_and_reverse_keep_shared_owner_and_cursor_stamps(self):
        self.compare(('circular_queue_class_and_aliases','rotate_zero_invalidates_forward_cursor','reverse_is_visible_to_both_cursor_directions'))
    def test_reverse_cursor_exhaustion_and_finite_sources(self):
        self.compare(('reversed_after_last_item_is_sticky','reversed_finite_deque_families_and_consumers'))
    def test_rotate_captures_receiver_before_argument_rebinding(self):
        self.compare(('rotate_captured_receiver_before_argument_rebind',))
    def test_reverse_list_keeps_initial_endpoint_and_reads_live_items(self):
        self.compare(('reverse_list_initial_endpoint_and_live_replacement','reverse_list_shrink_latches_exhaustion'))
    def test_reverse_range_does_not_materialize_or_require_ssize_length(self):
        self.compare(('reverse_range_huge_length_without_materialization','reverse_range_large_steps'))
    def test_selected_wide_integer_endpoint_boundaries(self):
        self.exercise('class Holder:\n def run(self):\n  low=-(1<<127)\n  high=(1<<127)-1\n  return list(reversed(range(low,high,high))),list(reversed(range(high,low,low)))\nprint(Holder().run())\n',('',),modes=('i128','bigint'))
        self.exercise('class Holder:\n def run(self):\n  low=-(10**120)\n  high=10**120\n  return list(reversed(range(low,high,10**119+7))),list(reversed(range(high,low,-10**119-3)))\nprint(Holder().run())\n',('',),modes=('bigint',))
    def test_canonical_reversed_class_identity_matches_actual_iterator_types(self):
        self.exercise('from collections import deque\nclass Holder:\n def run(self,source):return isinstance(reversed(source),reversed)\nholder=Holder()\nprint(reversed,str(reversed),repr(reversed))\nprint(isinstance(1,reversed),isinstance(reversed,list))\nprint(holder.run((1,2)),holder.run("abc"),holder.run(b"AB"),holder.run([1,2]),holder.run(range(3)),holder.run(deque([1,2])))\n',('',))
    def test_closed_native_sequence_families_share_one_source_provider(self):
        self.compare(('shared_finite_builtin_source_families',))
    def test_unicode_walks_backward_by_codepoints(self):
        self.compare(('unicode_reverse_walks_codepoint_boundaries',),string_mode='unicode')

if __name__=='__main__':unittest.main()
