"""Unresolved shared allocation payloads retain their actual element cell."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
CASES={'tuple_events': 'events=[]\n'
                 'def record(a,b):\n'
                 ' events.append((a,b))\n'
                 ' return a-b\n'
                 'record(3,2)\n'
                 'print(sum(i+a*10+b for i,(a,b) in enumerate(events)))\n',
 'nested_events': 'events=[]\n'
                  'def record(a):events.append([a])\n'
                  'record(7)\n'
                  'print(events)\n',
 'global_list_alias': 'events=[]\n'
                      'other=events\n'
                      'def record(a):events.append((a,a+1))\n'
                      'record(7)\n'
                      'other.append((9,10))\n'
                      'print(events,other,events is other)\n',
 'nested_comprehension': 'events=[]\n'
                         'def record(a):events.append((a,a+1))\n'
                         'record(4)\n'
                         'print([a+b+i for i,(a,b) in enumerate(events)])\n',
 'empty_no_calls': 'events=[]\n'
                   'def record(a):events.append((a,a+1))\n'
                   'print(events)\n',
 'nested_payload_alias': 'events=[]\n'
                         'a=[3]\n'
                         'def record(value):events.append((7,value))\n'
                         'record(a)\n'
                         'for k,value in events:value.append(k)\n'
                         'print(a,events)\n',
 'cross_function_append': 'events=[]\n'
                          'def record(a):events.append((a,a+1))\n'
                          'def solve():\n'
                          ' record(4)\n'
                          ' return [a+b+i for i,(a,b) in enumerate(events)]\n'
                          'print(solve())\n',
 'zero_trip': 'events=[]\n'
              'def record(a):events.append((a,a+1))\n'
              'for i in range(0):record(i)\n'
              'print([a+b for a,b in events])\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class GlobalEmptyAllocations(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_tuple_events(self):self.check('tuple_events')
    def test_nested_events(self):self.check('nested_events')
    def test_global_list_alias(self):self.check('global_list_alias')
    def test_nested_comprehension(self):self.check('nested_comprehension')
    def test_empty_no_calls(self):self.check('empty_no_calls')
    def test_nested_payload_alias(self):self.check('nested_payload_alias')
    def test_cross_function_append(self):self.check('cross_function_append')
    def test_zero_trip(self):self.check('zero_trip')
