"""Eager native exports consume original generators directly into typed sinks."""
import shutil
import unittest

from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'counter_body_error_frames': 'from collections import Counter\n'
                              'print(Counter(1//x for x in [1,0]))\n',
 'counter_constructor': 'from collections import Counter\n'
                        'print(Counter(x%3 for x in [1,2,3,4,5,6]))\n',
 'counter_constructor_alias': 'from collections import Counter\n'
                              'make=Counter\n'
                              'Counter=3\n'
                              'print(make(x for x in "abaca"))\n',
 'counter_constructor_later_arguments': 'from collections import Counter\n'
                                        'rows=["a"]\n'
                                        'def later():\n'
                                        ' rows.append("b")\n'
                                        ' return 3\n'
                                        'print(Counter((x for x in rows),c=later()))\n',
 'counter_dynamic_size_error': 'from collections import Counter\n'
                               'c=Counter([1,2])\n'
                               'def visit(x):\n'
                               ' c[3]=1\n'
                               ' return x\n'
                               'c.update(visit(x) for x in c)\n',
 'counter_empty_generator': 'from collections import Counter\nprint(Counter(x for x in []))\n',
 'counter_generator_pep479': 'from collections import Counter\n'
                             'print(Counter(next(iter(())) for x in [1]))\n',
 'counter_loop_and_bound_receiver': 'from collections import Counter\n'
                                    'class Bag:\n'
                                    ' def __init__(self):self.counts=Counter()\n'
                                    ' def add(self,rows):self.counts.update(x%3 for x in '
                                    'rows)\n'
                                    'bag=Bag()\n'
                                    'for rows in [[1,2],[2,3,4]]:bag.add(rows)\n'
                                    'print(bag.counts)\n',
 'counter_recursive_callback': 'from collections import Counter\n'
                               'def solve(v):\n'
                               ' if v:return solve(v-1)+1\n'
                               ' return 0\n'
                               'print(Counter(solve(v)%2 for v in [1,2,3]))\n',
 'counter_subtract': 'from collections import Counter\n'
                     'c=Counter("abac")\n'
                     'c.subtract(x for x in "abbc")\n'
                     'print(c,c.total())\n',
 'counter_update': 'from collections import Counter\n'
                   'c=Counter([1,2,1])\n'
                   'c.update(x%2 for x in [1,2,3,4])\n'
                   'print(c)\n',
 'counter_update_body_error': 'from collections import Counter\n'
                              'c=Counter([1])\n'
                              'print("before",c)\n'
                              'c.update(1//x for x in [1,0])\n',
 'counter_update_later_keywords': 'from collections import Counter\n'
                                  'c=Counter("aba")\n'
                                  'rows=["a"]\n'
                                  'def later():\n'
                                  ' rows.append("b")\n'
                                  ' return 5\n'
                                  'c.update((x for x in rows),c=later())\n'
                                  'print(c)\n',
 'counter_update_self_keys': 'from collections import Counter\n'
                             'c=Counter("abac")\n'
                             'c.update(x for x in c)\n'
                             'print(c)\n',
 'finite_counter_list_factories': 'from collections import Counter\n'
                                  'def collect(make):return make(x%3 for x in [1,2,3,4])\n'
                                  'print(collect(Counter),collect(list))\n',
 'finite_sum_list_factories': 'def collect(make):return make(x%3 for x in [1,2,3,4])\n'
                              'print(collect(sum),collect(list))\n'}

BOUNDARIES={'lazy_member_not_assumed_eager': 'from itertools import accumulate\n'
                                  'print(list(accumulate(x for x in [1,2])))\n',
 'stored_generator_still_requires_state': 'from collections import Counter\n'
                                          'stream=(x for x in [1,2])\n'
                                          'print(Counter(stream))\n',
 'user_function_not_assumed_eager': 'def retain(source):return source\n'
                                    'stream=retain(x for x in [1,2])\n'
                                    'print(list(stream))\n',
 'user_method_not_assumed_eager': 'class Holder:\n'
                                  ' def update(self,source):self.saved=source\n'
                                  'holder=Holder()\n'
                                  'holder.update(x for x in [1,2])\n'
                                  'print(list(holder.saved))\n'}


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class EagerMemberGeneratorTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_constructors_and_actual_aliases(self):
        for name in ('counter_constructor', 'counter_empty_generator', 'counter_constructor_alias', 'finite_counter_list_factories', 'finite_sum_list_factories'):
            with self.subTest(name=name):self.check(name)

    def test_ordered_arguments_and_methods(self):
        for name in ('counter_constructor_later_arguments', 'counter_update', 'counter_subtract', 'counter_update_self_keys', 'counter_update_later_keywords', 'counter_loop_and_bound_receiver'):
            with self.subTest(name=name):self.check(name)

    def test_body_errors_mutation_and_recursive_calls(self):
        for name in ('counter_body_error_frames', 'counter_update_body_error', 'counter_generator_pep479', 'counter_recursive_callback', 'counter_dynamic_size_error'):
            with self.subTest(name=name):self.check(name)

    def test_suspension_and_user_methods_keep_explicit_boundaries(self):
        for name,source in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none',filename='boundary.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code=='E006'and 'generator'in d.message for d in result.diagnostics),result.diagnostics)
