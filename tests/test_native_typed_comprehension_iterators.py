"""Synchronous comprehension sources share captured typed iterator adapters."""
import unittest
import test_native_class_iterators as iterator_tests

CASES={'callback_error_frames': 'class Marker:pass\n'
                          'def divide(value):\n'
                          ' print(value)\n'
                          ' return 10//value\n'
                          'print([value for value in map(divide,[1,0])])\n',
 'callback_mutates_live_source': 'class Marker:pass\n'
                                 'values=[1,2]\n'
                                 'def change(value):\n'
                                 ' if value<3:values.append(value+2)\n'
                                 ' return value\n'
                                 'print([value for value in map(change,values)],values)\n',
 'direct_lambda_callback': 'class Marker:pass\n'
                           'print([value for value in map(lambda value:value+3,[1,2])])\n',
 'direct_source_callback': 'class Marker:pass\n'
                           'def twice(value):return value*2\n'
                           'print([value for value in map(twice,[1,2,3]) if value>2])\n',
 'direct_zip_unpack': 'class Marker:pass\nprint([a+b for a,b in zip([1,2],[3,4])])\n',
 'nested_capture_uses_current_target': 'class Marker:pass\n'
                                       'print([(a,b) for a in range(2) for b in map(lambda '
                                       'value:value+a,[1,2])])\n',
 'nested_zip_map_filter': 'class Marker:pass\n'
                          'print([(a,b) for a,b in zip(map(lambda '
                          'x:x+1,[1,2,3]),filter(None,[0,4,5]))])\n',
 'unicode_callback_comprehension': 'class Marker:pass\n'
                                   'print([value for value in map(lambda x:x+x,"猫😀")])\n'}


class TypedComprehensionIteratorTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_callbacks_and_zip_sources(self):
        for name in ('direct_source_callback','direct_lambda_callback','direct_zip_unpack','nested_zip_map_filter'):
            with self.subTest(name=name):self.check(name)

    def test_effects_scope_errors_and_text(self):
        for name in ('callback_error_frames','unicode_callback_comprehension','nested_capture_uses_current_target','callback_mutates_live_source'):
            with self.subTest(name=name):self.check(name)


if __name__=='__main__':unittest.main()
