"""Remainder list allocations retain their solved element storage."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
CASES={'append_text': 'first,*rest=range(4)\n'
                'rest.append("text")\n'
                'print(first,rest)\n',
 'append_none': 'first,*rest=[1,2,3]\nrest.append(None)\nprint(first,rest)\n',
 'tuple_future_type': 'first,*rest,last=(1,2,3,4)\n'
                      'rest.append("text")\n'
                      'print(first,rest,last)\n',
 'caller_mutates_returned_rest': 'def values():\n'
                                 ' first,*rest=range(4)\n'
                                 ' return rest\n'
                                 'rest=values()\n'
                                 'rest.append("text")\n'
                                 'print(rest)\n',
 'nested_prefix_error_after_outer_store': 'first="old"\n'
                                          'def source():\n'
                                          ' print(first)\n'
                                          ' return None\n'
                                          'first,(a,*rest)=(7,source())\n'
                                          'print(first,a,rest)\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class StarUnpackMutations(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_append_text(self):self.check('append_text')
    def test_append_none(self):self.check('append_none')
    def test_tuple_future_type(self):self.check('tuple_future_type')
    def test_caller_mutates_returned_rest(self):self.check('caller_mutates_returned_rest')
    def test_nested_prefix_error_after_outer_store(self):self.check('nested_prefix_error_after_outer_store')
