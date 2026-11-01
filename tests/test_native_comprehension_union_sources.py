"""Comprehensions use common registered cursors for finite iterable alternatives."""
import unittest
import test_native_class_iterators as iterator_tests

CASES={'empty_variable_tuple': 'def collect(source):return [x+1 for x in source]\n'
                         'def f(*args):return collect(args)\n'
                         'print(collect([1]),f(),f(2))\n',
 'enumerate_union': 'def collect(source):return [(i,x+1) for i,x in enumerate(source,2)]\n'
                    'def f(*args):return collect(args)\n'
                    'print(collect([1,2]),f(3,4))\n',
 'list_and_range': 'class Marker:pass\n'
                   'def collect(source):return [x*2 for x in source]\n'
                   'print(collect([1,2]),collect(range(3)))\n',
 'live_list_union_alias': 'def collect(source):return [row for row in source]\n'
                          'def f(*args):return collect(args)\n'
                          'values=[[1],[2]]\n'
                          'left=collect(values)\n'
                          'right=f(values[0],values[1])\n'
                          'left[0].append(3)\n'
                          'print(values,left,right)\n',
 'nested_union_sources': 'def collect(source):return [(a,b) for a in range(2) for b in source]\n'
                         'def f(*args):return collect(args)\n'
                         'print(collect([1,2]),f(3,4))\n',
 'nullable_noniterable_error': 'class Marker:pass\n'
                               'def collect(source):return [x+1 for x in source]\n'
                               'print(collect([1,2]))\n'
                               'print(collect(None))\n',
 'original_varargs_list': 'def collect(source):\n'
                          ' return [x+1 for x in source]\n'
                          'def f(*args):return collect(args)\n'
                          'print(collect([1,2]),f(3,4))\n',
 'text_and_bytes': 'class Marker:pass\n'
                   'def collect(source):return [str(x) for x in source]\n'
                   'print(collect("ab"),collect(b"cd"))\n'}

class ComprehensionUnionSourceTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_sources_and_nested_producers(self):
        for name in ('original_varargs_list','enumerate_union','nested_union_sources','list_and_range','text_and_bytes'):
            with self.subTest(name=name):self.check(name)

    def test_error_empty_source_and_shared_mutable_payloads(self):
        for name in ('nullable_noniterable_error','live_list_union_alias','empty_variable_tuple'):
            with self.subTest(name=name):self.check(name)

if __name__=='__main__':unittest.main()
