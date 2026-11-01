"""Captured extrema keys/defaults preserve candidate identity and source effects."""
import unittest
import test_native_class_iterators as execution


CASES = {'argmin_indices': 'values=[8,3,3,9]\n'
                   'print(min(range(len(values)),key=lambda i:values[i]))\n'
                   'print(max(range(len(values)),key=lambda i:values[i]))\n',
 'callback_error_frames': 'def rank(value):\n'
                          " print('key',value)\n"
                          ' return 10//value\n'
                          'print(min([2,0,1],key=rank))\n',
 'closure_and_bound_keys': 'def make(offset):\n'
                           ' def key(value):return abs(value-offset)\n'
                           ' return key\n'
                           'class Box:\n'
                           ' def key(self,value):return -value\n'
                           'box=Box()\n'
                           'print(min([1,4,7],key=make(5)),min([1,4,7],key=box.key))\n',
 'default_is_not_keyed': 'def key(value):\n'
                         " print('key',value)\n"
                         ' return -value\n'
                         "print(min([],key=key,default='not keyed'))\n",
 'default_unkeyed': "class Marker:pass\nprint(min([],default=7),max([1,3,2],default='unused'))\n",
 'empty_default_identity': 'fallback=[9]\n'
                           'result=min([],key=lambda x:1//0,default=fallback)\n'
                           'print(result,result is fallback)\n',
 'empty_error': 'class Marker:pass\nprint(min(()))\n',
 'float_literal_values': 'print(min([1.5,-3.0,2.5],key=abs),max([1.5,-3.0,2.5],key=abs))\n',
 'generator_body_stop_iteration': 'cursor=iter([1])\n'
                                  'print(max((next(cursor)for unused in range(2)),key=lambda '
                                  'x:x))\n',
 'generator_callback_stop_iteration': 'cursor=iter([1])\n'
                                      'def rank(value):return next(cursor)\n'
                                      'print(min((value for value in [1,2]),key=rank))\n',
 'generator_default': "print(min((n*n for n in range(0)),default='empty',key=abs))\n"
                      'print(max((n*n for n in range(4)),default=None,key=lambda x:-x))\n',
 'invalid_default_positional': 'def mark(value):print(value);return value\n'
                               'print(min(mark(1),mark(2),default=mark(3)))\n',
 'invalid_keyword': 'def mark(value):print(value);return value\n'
                    'print(max(mark([1]),wrong=mark(2)))\n',
 'invalid_zero_args': 'def mark(value):print(value);return value\n'
                      'min(key=mark(None),default=mark(1))\n',
 'iterable_string_keys': "values=['bbb','a','cc']\n"
                         'print(min(values,key=len),max(values,key=len))\n',
 'key_and_default_capture': 'rank=abs\n'
                            'def later():\n'
                            ' global rank\n'
                            ' rank=0\n'
                            " print('default')\n"
                            ' return 9\n'
                            'print(min([-3,2],key=rank,default=later()),rank)\n',
 'key_called_once_and_ties': 'def key(value):\n'
                             " print('key',value)\n"
                             ' return value%2\n'
                             'print(min([3,1,5],key=key),max([2,4,6],key=key))\n',
 'key_mutates_prior_candidate': 'rows=[[1],[2]]\n'
                                'def key(row):\n'
                                ' if row is rows[1]:rows[0].append(8)\n'
                                ' return len(row)\n'
                                'answer=min(rows,key=key)\n'
                                'print(answer,answer is rows[0],rows)\n',
 'key_none_and_captured_alias': 'class Marker:pass\n'
                                'choose=min\n'
                                'min=0\n'
                                'print(choose([3,1,2],key=None),min)\n',
 'key_result_none_error': "print('before')\nprint(min([1,2],key=lambda x:None))\n",
 'key_wrong_signature': 'def rank():return 1\nprint(max([1],key=rank))\n',
 'mapping_view_candidates': "mapping={'a':[2,3],'b':[1],'c':[4,5]}\n"
                            'result=max(mapping.items(),key=lambda pair:len(pair[1]))\n'
                            'result[1].append(9)\n'
                            'print(result,mapping)\n',
 'mutable_candidate_identity': 'rows=[[1,2],[9],[4,5]]\n'
                               'answer=max(rows,key=len)\n'
                               'answer.append(7)\n'
                               'print(rows,answer is rows[0])\n',
 'mutable_key_alias': 'shared=[0]\n'
                      'def key(value):\n'
                      ' shared[0]=value\n'
                      ' return shared\n'
                      'print(min([3,1,2],key=key),shared)\n',
 'noncallable_empty_key': 'print(min([],key=0,default=99))\n',
 'noncallable_nonempty_key': "print('before')\nprint(max([1],key=False))\n",
 'noniterable_error_after_arguments': 'def mark(value):print(value);return value\n'
                                      'min(mark(3),key=mark(None),default=mark(9))\n',
 'optional_key': 'def choose(key):return min([3,-1,2],key=key)\nprint(choose(None),choose(abs))\n',
 'positional_key': 'print(min(3,1,2,key=lambda x:-x),max(-3,1,2,key=abs))\n',
 'recursive_key': 'def fib(n):\n'
                  ' if n<2:return n\n'
                  ' return fib(n-1)+fib(n-2)\n'
                  'print(max([2,4,3],key=fib))\n',
 'source_mutation_during_key': 'values=[3]\n'
                               'def key(value):\n'
                               ' if len(values)<4:values.append(value-1)\n'
                               " print('key',value)\n"
                               ' return value\n'
                               'print(min(values,key=key),values)\n',
 'unicode_keys': "values=['猫猫','é','😀😀😀']\nprint(min(values,key=len),max(values,key=len))\n",
 'varargs_candidates': 'def choose(*values):return max(values,key=lambda x:-x,default=99)\n'
                       'print(choose(),choose(3,1,2))\n'}


CASES.update({'empty_object_key': 'class Key:\n'
                     " def __init__(self):print('created')\n"
                     'print(min([],key=lambda value:Key(),default=9))\n',
 'multiple_object_keys': 'class Key:\n'
                         " def __init__(self):print('created')\n"
                         'print(min([3,1,2],key=lambda value:Key()))\n',
 'single_object_key': 'class Key:\n'
                      " def __init__(self):print('created')\n"
                      'print(max([3],key=lambda value:Key()))\n'})


class NativeExtremaTests(unittest.TestCase):
    cases=CASES
    check=execution.IteratorExecutionTests.check

    def test_default_object_comparison_is_deferred_until_needed(self):
        for name in ('empty_object_key', 'single_object_key', 'multiple_object_keys'):
            with self.subTest(name=name):self.check(name)

    def test_basic(self):
        for name in ('positional_key', 'iterable_string_keys', 'argmin_indices', 'empty_default_identity', 'generator_default', 'default_unkeyed', 'default_is_not_keyed', 'key_called_once_and_ties', 'mutable_candidate_identity', 'mutable_key_alias', 'source_mutation_during_key'):
            with self.subTest(name=name):self.check(name)

    def test_ordering(self):
        for name in ('key_and_default_capture', 'callback_error_frames', 'generator_callback_stop_iteration', 'generator_body_stop_iteration', 'noncallable_empty_key', 'noncallable_nonempty_key', 'key_result_none_error', 'key_none_and_captured_alias', 'closure_and_bound_keys', 'optional_key', 'recursive_key'):
            with self.subTest(name=name):self.check(name)

    def test_binding_and_context(self):
        for name in ('varargs_candidates', 'mapping_view_candidates', 'unicode_keys', 'float_literal_values', 'invalid_default_positional', 'invalid_keyword', 'invalid_zero_args', 'noniterable_error_after_arguments', 'empty_error', 'key_wrong_signature', 'key_mutates_prior_candidate'):
            with self.subTest(name=name):self.check(name)

if __name__=='__main__':unittest.main()
