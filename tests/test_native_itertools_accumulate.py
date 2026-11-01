"""Lazy accumulated values share the generic value/call/type planners."""
import shutil
import unittest

import test_native_class_iterators as iterator_tests

CASES={'boolean_first_identity': 'from itertools import accumulate\n'
                           'print(list(accumulate([True,False,True])),list(accumulate([True],initial=False)))\n',
 'bound_method_callback': 'from itertools import accumulate\n'
                          'class Counter:\n'
                          ' def __init__(self):self.count=0\n'
                          ' def add(self,a,b):\n'
                          '  self.count+=1\n'
                          '  return a+b\n'
                          'c=Counter()\n'
                          'print(list(accumulate([1,2,3],c.add)),c.count)\n',
 'callback_capture_lazy': 'from itertools import accumulate\n'
                          'def yes(a,b):\n'
                          ' print("yes",a,b)\n'
                          ' return a+b\n'
                          'def no(a,b):return a-b\n'
                          'f=yes\n'
                          'stream=accumulate([2,3,4],f)\n'
                          'f=no\n'
                          'print("created",next(stream))\n'
                          'print(list(stream))\n',
 'callback_changes_total_type': 'from itertools import accumulate\n'
                                'def join(a,b):return str(a)+str(b)\n'
                                'print(list(accumulate([1,2,3],join)))\n',
 'callback_multiplication': 'from itertools import accumulate\n'
                            'def product(a,b):return a*b\n'
                            'print(list(accumulate([2,3,4],product,initial=1)))\n',
 'callback_none_is_a_value': 'from itertools import accumulate\n'
                             'def forget(a,b):return None\n'
                             'print(list(accumulate([1,2,3],forget)))\n',
 'callback_nonstop_error': 'from itertools import accumulate\n'
                           'def div(a,b):return a//b\n'
                           'print(list(accumulate([5,0,2],div)))\n',
 'callback_prefix_extrema': 'from itertools import accumulate\n'
                            'print(list(accumulate([3,1,7,4],max)),list(accumulate([3,1,7,4],min)))\n',
 'callback_stop_resume': 'from itertools import accumulate\n'
                         'def add(a,b):\n'
                         ' if b==2:return next(iter(()))\n'
                         ' return a+b\n'
                         'stream=accumulate([1,2,3],add)\n'
                         'print(list(stream),list(stream),list(stream))\n',
 'captured_lambda': 'from itertools import accumulate\n'
                    'def fold(delta):return list(accumulate([1,2,3],lambda a,b:a+b+delta))\n'
                    'print(fold(0),fold(2))\n',
 'classinfo_no_consumption': 'from itertools import accumulate\n'
                             'def add(a,b):\n'
                             ' print("call")\n'
                             ' return a+b\n'
                             'stream=accumulate([1,2],add)\n'
                             'print(isinstance(stream,accumulate),list(stream))\n',
 'default_prefix_sums': 'from itertools import accumulate\n'
                        'stream=accumulate([1,3,2,7])\n'
                        'print(next(stream),list(stream),list(stream))\n',
 'filter_optional_bound_method': 'class Decisions:\n'
                                 ' def __init__(self):self.limit=1\n'
                                 ' def keep(self,v):return v>self.limit\n'
                                 'def choose(predicate):return '
                                 'list(filter(predicate,[0,1,2,3]))\n'
                                 'obj=Decisions()\n'
                                 'print(choose(None),choose(obj.keep))\n',
 'filter_optional_closure': 'def choose(predicate):return list(filter(predicate,[0,1,2,3]))\n'
                            'def build(limit):\n'
                            ' def keep(v):return v>limit\n'
                            ' return keep\n'
                            'print(choose(None),choose(build(1)))\n',
 'finite_callback_alternatives': 'from itertools import accumulate\n'
                                 'def fold(func):return list(accumulate([1,2,3],func))\n'
                                 'print(fold(None),fold(max),fold(lambda a,b:a-b))\n',
 'finite_initial_alternatives': 'from itertools import accumulate\n'
                                'def fold(initial):return '
                                'list(accumulate([1,2],initial=initial))\n'
                                'print(fold(None),fold(4),fold(False))\n',
 'fold_reentrant_callback': 'from itertools import accumulate\n'
                            'def add(a,b):\n'
                            ' print("add",a,b)\n'
                            ' if b==2:print("inside",next(stream,99))\n'
                            ' return a+b\n'
                            'stream=accumulate([1,2,3,4],add)\n'
                            'print(list(stream))\n',
 'for_enumerate_comprehension': 'from itertools import accumulate,islice,repeat\n'
                                'print([v%3 for v in accumulate(islice(repeat(2),4))])\n'
                                'for i,v in enumerate(accumulate([1,2,3]),5):print(i,v)\n',
 'generator_body_pep479': 'from itertools import accumulate\n'
                          'def add(a,b):return next(x for x in [])\n'
                          'print(list(accumulate([1,2],add)))\n',
 'initial_and_empty': 'from itertools import accumulate\n'
                      'print(list(accumulate([],initial=4)),list(accumulate([],initial=None)),list(accumulate([1,2],initial=10)))\n',
 'initial_argument_source_mutation': 'from itertools import accumulate\n'
                                     'rows=[1,2,3]\n'
                                     'def initial():\n'
                                     ' rows.clear()\n'
                                     ' return 9\n'
                                     'print(list(accumulate(rows,initial=initial())),rows)\n',
 'initial_mutable_alias': 'from itertools import accumulate\n'
                          'first=[1]\n'
                          'rows=list(accumulate([[2],[3]],initial=first))\n'
                          'first.append(9)\n'
                          'print(rows,rows[0] is first)\n',
 'keyword_bindings': 'from itertools import accumulate\n'
                     'print(list(accumulate(iterable=[3,1,7],func=max,initial=2)))\n',
 'list_prefix_aliases': 'from itertools import accumulate\n'
                        'a=[1]\n'
                        'b=[2]\n'
                        'c=[3]\n'
                        'rows=list(accumulate([a,b,c]))\n'
                        'rows[0].append(9)\n'
                        'print(a,b,c,rows,rows[0] is a,rows[1] is a)\n',
 'noncallable_second': 'from itertools import accumulate\nprint(list(accumulate([4,5],3)))\n',
 'noncallable_singleton': 'from itertools import accumulate\n'
                          'print(list(accumulate([4],3)),list(accumulate([],3)))\n',
 'none_function': 'from itertools import accumulate\n'
                  'print(list(accumulate([1,2,3],None,initial=None)))\n',
 'recursive_callback': 'from itertools import accumulate\n'
                       'def add(a,b):\n'
                       ' if b>0:return add(a+1,b-1)\n'
                       ' return a\n'
                       'print(list(accumulate([1,2,3],add)))\n',
 'source_mutation': 'from itertools import accumulate\n'
                    'rows=[1,2]\n'
                    'def add(a,b):\n'
                    ' if b<4:rows.append(b+1)\n'
                    ' return a+b\n'
                    'stream=accumulate(rows,add)\n'
                    'print(list(stream),rows)\n',
 'source_reentrant_callback': 'from itertools import accumulate\n'
                              'def visit(v):\n'
                              ' print("source",v)\n'
                              ' if v==1:print("inside",next(stream,99))\n'
                              ' return v\n'
                              'stream=accumulate(map(visit,[1,2,3,4]))\n'
                              'print(list(stream))\n',
 'source_stop_fuses': 'from itertools import accumulate\n'
                      'def get(v):\n'
                      ' if v==2:return next(iter(()))\n'
                      ' return v\n'
                      'source=map(get,[1,2,3])\n'
                      'stream=accumulate(source)\n'
                      'print(list(stream),list(stream),list(source))\n',
 'stored_aliases': 'from itertools import accumulate\n'
                   'stream=accumulate([1,2,3])\n'
                   'alias=stream\n'
                   'print(iter(stream) is stream,next(alias),next(stream),list(alias))\n',
 'string_prefixes': 'from itertools import accumulate\n'
                    'print(list(accumulate(["ab","c","de"])))\n',
 'unicode_prefixes': 'from itertools import accumulate\n'
                     'print(list(accumulate(["猫","🐈","é"])))\n',
 'vararg_tuple_source': 'from itertools import accumulate\n'
                        'def prefix(*values):return list(accumulate(values))\n'
                        'print(prefix(),prefix(1,2,3),prefix(4))\n',
 'wrong_keyword_effects': 'from itertools import accumulate\n'
                          'def mark(v):\n'
                          ' print(v)\n'
                          ' return v\n'
                          'print(accumulate(mark([1,2]),function=mark(3)))\n'}


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class AccumulateTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_prefix_values_and_initial(self):
        for name in ('default_prefix_sums', 'initial_and_empty', 'boolean_first_identity', 'none_function', 'keyword_bindings', 'finite_initial_alternatives', 'vararg_tuple_source'):
            with self.subTest(name=name):self.check(name)

    def test_captured_callbacks(self):
        for name in ('callback_prefix_extrema', 'callback_multiplication', 'callback_capture_lazy', 'bound_method_callback', 'captured_lambda', 'finite_callback_alternatives', 'recursive_callback'):
            with self.subTest(name=name):self.check(name)

    def test_alias_and_payload_types(self):
        for name in ('stored_aliases', 'string_prefixes', 'list_prefix_aliases', 'initial_mutable_alias', 'callback_changes_total_type', 'callback_none_is_a_value', 'unicode_prefixes'):
            with self.subTest(name=name):self.check(name)

    def test_laziness_mutation_and_consumers(self):
        for name in ('source_mutation', 'initial_argument_source_mutation', 'for_enumerate_comprehension', 'classinfo_no_consumption', 'source_reentrant_callback', 'fold_reentrant_callback'):
            with self.subTest(name=name):self.check(name)

    def test_errors_and_resumable_stop(self):
        for name in ('callback_stop_resume', 'source_stop_fuses', 'callback_nonstop_error', 'noncallable_singleton', 'noncallable_second', 'wrong_keyword_effects', 'generator_body_pep479'):
            with self.subTest(name=name):self.check(name)

    def test_nullable_filter_callable_projection(self):
        for name in ('filter_optional_closure', 'filter_optional_bound_method'):
            with self.subTest(name=name):self.check(name)
