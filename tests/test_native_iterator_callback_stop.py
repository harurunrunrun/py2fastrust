"""Callback StopIteration ends a pull without fusing resumable adapters."""
import shutil
import unittest

import test_native_class_iterators as iterator_tests

CASES={'filter_next_default_resume': 'def keep(value):\n'
                               ' if value==1:return next(iter(()))\n'
                               ' return value\n'
                               'stream=filter(keep,[1,2,3])\n'
                               'print(next(stream,99),next(stream),list(stream))\n',
 'filter_nonstop_exception_unchanged': 'def keep(value):\n'
                                       ' print(value)\n'
                                       ' return 10//value\n'
                                       'print(list(filter(keep,[1,0])))\n',
 'filter_over_resumable_filter': 'def keep(value):\n'
                                 ' if value==2:return next(iter(()))\n'
                                 ' return value\n'
                                 'source=filter(keep,[1,2,3])\n'
                                 'stream=filter(None,source)\n'
                                 'print(list(stream),list(stream),list(source))\n',
 'filter_over_resumable_map': 'def call(value):\n'
                              ' if value==2:return next(iter(()))\n'
                              ' return value\n'
                              'source=map(call,[1,2,3])\n'
                              'stream=filter(None,source)\n'
                              'print(list(stream),list(stream),list(source))\n',
 'filter_resume_after_stop': 'def keep(value):\n'
                             ' if value==2:return next(iter(()))\n'
                             ' return value%2\n'
                             'stream=filter(keep,[1,2,3,4])\n'
                             'print(list(stream),list(stream),list(stream))\n',
 'gen_source_map_stop_is_exhaustion': 'source=iter([1])\n'
                                      'def read(unused):return next(source)\n'
                                      'print(sum(value for value in map(read,range(3))))\n',
 'generator_body_pep479_is_not_swallowed': 'source=iter([1])\n'
                                           'def call(unused):return sum(next(source) for '
                                           'value in range(3))\n'
                                           'print(list(map(call,[0])))\n',
 'map_next_default_resume': 'def call(value):\n'
                            ' if value==1:return next(iter(()))\n'
                            ' return value\n'
                            'stream=map(call,[1,2,3])\n'
                            'print(next(stream,99),next(stream),list(stream))\n',
 'map_nonstop_exception_unchanged': 'def call(value):\n'
                                    ' print(value)\n'
                                    ' return 10//value\n'
                                    'print(list(map(call,[1,0])))\n',
 'map_original': 'source=iter([1])\n'
                 'def read(unused):return next(source)\n'
                 'print(list(map(read,[0,1,2])))\n',
 'map_resume_after_stop': 'def call(value):\n'
                          ' if value==2:return next(iter(()))\n'
                          ' return value*10\n'
                          'stream=map(call,[1,2,3])\n'
                          'print(list(stream),list(stream),list(stream))\n',
 'map_strict_after_callback_stop': 'def call(a,b):\n'
                                   ' if a==2:return next(iter(()))\n'
                                   ' return a+b\n'
                                   'stream=map(call,[1,2,3],[10,20],strict=True)\n'
                                   'print(list(stream))\n'
                                   'print(list(stream))\n',
 'recursive_bottom_map_callback': 'def stop(depth):\n'
                                  ' if depth:return stop(depth-1)\n'
                                  ' return next(iter(()))\n'
                                  'stream=map(stop,[5,4])\n'
                                  'print(list(stream),list(stream))\n',
 'recursive_filter_callback': 'def keep(value):\n'
                              ' if value>1:return keep(value-1)\n'
                              ' if value:return next(iter(()))\n'
                              ' return True\n'
                              'stream=filter(keep,[0,2,0])\n'
                              'print(list(stream),list(stream))\n',
 'zip_strict_detects_stopped_map': 'def stop(value):return next(iter(()))\n'
                                   'stream=zip(map(stop,[1]),[2],strict=True)\n'
                                   'print(list(stream))\n'}


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IteratorCallbackStopTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_map_callback_stop_and_resume(self):
        for name in ('map_original','map_resume_after_stop','map_next_default_resume',
                     'map_strict_after_callback_stop'):
            with self.subTest(name=name):self.check(name)

    def test_filter_callback_stop_and_nested_resume(self):
        for name in ('filter_resume_after_stop','filter_next_default_resume',
                     'filter_over_resumable_map','filter_over_resumable_filter'):
            with self.subTest(name=name):self.check(name)

    def test_recursive_callbacks_and_other_errors(self):
        for name in ('recursive_bottom_map_callback','recursive_filter_callback',
                     'map_nonstop_exception_unchanged','filter_nonstop_exception_unchanged'):
            with self.subTest(name=name):self.check(name)

    def test_generator_and_strict_zip_protocol_boundaries(self):
        for name in ('gen_source_map_stop_is_exhaustion', 'zip_strict_detects_stopped_map'):
            with self.subTest(name=name):self.check(name)

    def test_generator_body_has_complete_pep479_chain(self):
        import test_native_explicit_raise as raise_tests
        raise_tests.NativeRaiseExecutionTests.exercise(self,CASES['generator_body_pep479_is_not_swallowed'],'')
