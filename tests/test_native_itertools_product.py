"""Cartesian pool capture and result iteration use concrete native state."""
import shutil
import unittest

import test_native_class_iterators as iterator_tests

CASES={'argument_order': 'from itertools import product\n'
                   'def mark(label,v):\n'
                   ' print(label)\n'
                   ' return v\n'
                   'print(list(product(mark("first",[1,2]),mark("second",[3]),repeat=mark("repeat",1))))\n',
 'basic_pools': 'from itertools import product\nprint(list(product([1,2],"ab")))\n',
 'callable_alias': 'import itertools as tools\n'
                   'make=tools.product\n'
                   'print(list(make([1,2],repeat=2)),isinstance(make([1]),make))\n',
 'captured_pools_ignore_appends': 'from itertools import product\n'
                                  'rows=[1,2]\n'
                                  'stream=product(rows,[3])\n'
                                  'rows.append(9)\n'
                                  'print(list(stream),rows)\n',
 'constructor_source_error': 'from itertools import product\n'
                             'def get(v):return 1//v\n'
                             'stream=product(map(get,[1,0,3]))\n'
                             'print("unreachable")\n',
 'dynamic_rank_comprehension_unpack': 'from itertools import product\n'
                                      'def pairs(rank):return [a+b for a,b in '
                                      'product([1,2],repeat=rank)]\n'
                                      'print(pairs(2))\n',
 'dynamic_rank_unpack_arity_error': 'from itertools import product\n'
                                    'def pairs(rank):return [a+b for a,b in '
                                    'product([1,2],repeat=rank)]\n'
                                    'print(pairs(1))\n',
 'empty_pool': 'from itertools import product\n'
               'print(list(product([],range(2))),list(product([1],[],[3])))\n',
 'empty_pool_still_consumes_later': 'from itertools import product\n'
                                    'def mark(v):\n'
                                    ' print("pull",v)\n'
                                    ' return v\n'
                                    'stream=product([],map(mark,[1,2]))\n'
                                    'print("created",list(stream))\n',
 'fixed_boolean_integer_positions': 'from itertools import product\n'
                                    'rows=list(product([True,False],[2,3]))\n'
                                    'print(rows,[a+b for a,b in rows])\n',
 'fixed_repeat_field_pattern': 'from itertools import product\n'
                               'rows=list(product([True],[3],repeat=2))\n'
                               'print(rows,rows[0][0],rows[0][1],rows[0][2],rows[0][3])\n',
 'float_repeat': 'from itertools import product\nprint(list(product([1],repeat=1.5)))\n',
 'generator_body_error_frames': 'from itertools import product\n'
                                'print(list(product((1//v for v in [1,0]),[4])))\n',
 'generator_capture_before_later_arguments': 'from itertools import product\n'
                                             'rows=[1,2]\n'
                                             'def later():\n'
                                             ' rows.append(3)\n'
                                             ' return [4]\n'
                                             'print(list(product((v*2 for v in '
                                             'rows),later())))\n',
 'generator_constructor_still_runs': 'from itertools import product\n'
                                     'def source():\n'
                                     ' print("source")\n'
                                     ' return [1,2]\n'
                                     'print(list(product((v*2 for v in source()),repeat=0)))\n',
 'generator_zero_repeat_skips_body': 'from itertools import product\n'
                                     'print(list(product((1//v for v in [0]),repeat=0)))\n',
 'generic_tuple_sequence_comprehension': 'def total(*rows):return [a+b for a,b in '
                                         'map(tuple,rows)]\n'
                                         'print(total([1,2],[3,4]))\n',
 'generic_tuple_sequence_mutable_alias': 'def visit(*rows):return [a.append(9) or b for a,b in '
                                         'map(tuple,rows)]\n'
                                         'a=[1]\n'
                                         'b=[2]\n'
                                         'print(visit([a,b]),a,b)\n',
 'generic_tuple_sequence_unpack_error': 'def total(*rows):return [a+b for a,b in '
                                        'map(tuple,rows)]\n'
                                        'print(total([1]))\n',
 'heterogeneous_fixed_repeat': 'from itertools import product\n'
                               'rows=list(product([[1]],[2],repeat=1))\n'
                               'rows[0][0].append(7)\n'
                               'print(rows)\n',
 'initial_generator_argument': 'from itertools import product\n'
                               'rows=[1,2]\n'
                               'print(list(product((v*2 for v in rows),[3,4])))\n',
 'invalid_repeat_before_source_pull': 'from itertools import product\n'
                                      'def get(v):\n'
                                      ' print("pull",v)\n'
                                      ' return v\n'
                                      'print(list(product(map(get,[1,2]),repeat=-1)))\n',
 'loops_and_comprehensions': 'from itertools import product\n'
                             'print([a*b for a,b in product([1,2],[3,4])])\n'
                             'for index,pair in '
                             'enumerate(product(range(2),range(2)),5):print(index,pair)\n',
 'middle_generator_argument': 'from itertools import product\n'
                              'print(list(product([1],(x for x in [2,3]),[4,5])))\n',
 'mutable_payload_identity': 'from itertools import product\n'
                             'row=[1]\n'
                             'items=list(product([row],[2,3]))\n'
                             'items[0][0].append(8)\n'
                             'print(row,items,items[0][0] is items[1][0])\n',
 'negative_repeat': 'from itertools import product\nprint(list(product([1],repeat=-1)))\n',
 'nested_tuple_positions': 'from itertools import product\n'
                           'print(list(product([(1,2)],[(True,False)])))\n',
 'none_repeat': 'from itertools import product\nprint(list(product([1],repeat=None)))\n',
 'noniterable_source': 'from itertools import product\nprint(list(product([1],3)))\n',
 'partial_aliases': 'from itertools import product\n'
                    'stream=product([1,2],[3,4])\n'
                    'alias=stream\n'
                    'print(iter(stream) is '
                    'stream,next(alias),next(stream),list(alias),list(stream))\n',
 'repeated_pool_materialized_once': 'from itertools import product\n'
                                    'def mark(v):\n'
                                    ' print("pull",v)\n'
                                    ' return v\n'
                                    'stream=product(map(mark,[1,2]),repeat=2)\n'
                                    'print("created",list(stream))\n',
 'runtime_repeat': 'from itertools import product\n'
                   'def bits(n):return list(product([0,1],repeat=n))\n'
                   'print(bits(0),bits(2),bits(3))\n',
 'second_generator_argument': 'from itertools import product\n'
                              'print(list(product([1,2],(x*3 for x in [3,4]))))\n',
 'source_stop_is_materialization_end': 'from itertools import product\n'
                                       'def get(v):\n'
                                       ' if v==2:return next(iter(()))\n'
                                       ' return v\n'
                                       'source=map(get,[1,2,3])\n'
                                       'print(list(product(source,[4])),list(source))\n',
 'unicode_pools': 'from itertools import product\nprint(list(product("猫🐈","😀é")))\n',
 'unknown_keyword_effects': 'from itertools import product\n'
                            'def mark(v):\n'
                            ' print(v)\n'
                            ' return v\n'
                            'print(product(mark([1]),other=mark(2)))\n',
 'zero_inputs': 'from itertools import product\n'
                'print(list(product()),list(product(repeat=0)),list(product(repeat=3)))\n',
 'zero_repeat_does_not_consume': 'from itertools import product\n'
                                 'def mark(v):\n'
                                 ' print("pull",v)\n'
                                 ' return v\n'
                                 'source=map(mark,[1,2])\n'
                                 'print(list(product(source,repeat=0)),list(source))\n',
 'zero_repeat_noniterable': 'from itertools import product\nprint(list(product(3,repeat=0)))\n',
 'zero_repeat_unknown_body_is_unreached': 'from itertools import product\n'
                                          'print(list(product((unknown(x) for x in '
                                          '[1]),repeat=0)))\n'}


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ProductTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_pool_values_and_zero_dimensions(self):
        for name in ('basic_pools', 'zero_inputs', 'empty_pool', 'runtime_repeat', 'partial_aliases', 'fixed_boolean_integer_positions', 'nested_tuple_positions'):
            with self.subTest(name=name):self.check(name)

    def test_capture_mutation_and_shared_payloads(self):
        for name in ('zero_repeat_does_not_consume', 'zero_repeat_noniterable', 'repeated_pool_materialized_once', 'empty_pool_still_consumes_later', 'argument_order', 'captured_pools_ignore_appends', 'mutable_payload_identity', 'source_stop_is_materialization_end', 'heterogeneous_fixed_repeat', 'fixed_repeat_field_pattern'):
            with self.subTest(name=name):self.check(name)

    def test_generator_inputs_and_ordered_effects(self):
        for name in ('initial_generator_argument', 'generator_capture_before_later_arguments', 'generator_body_error_frames', 'generator_zero_repeat_skips_body', 'generator_constructor_still_runs', 'second_generator_argument', 'middle_generator_argument', 'zero_repeat_unknown_body_is_unreached'):
            with self.subTest(name=name):self.check(name)

    def test_errors_and_constructor_validation(self):
        for name in ('constructor_source_error', 'invalid_repeat_before_source_pull', 'noniterable_source', 'negative_repeat', 'none_repeat', 'float_repeat', 'unknown_keyword_effects'):
            with self.subTest(name=name):self.check(name)

    def test_loops_and_tuple_sequence_unpacking(self):
        for name in ('loops_and_comprehensions', 'unicode_pools', 'callable_alias', 'dynamic_rank_comprehension_unpack', 'dynamic_rank_unpack_arity_error', 'generic_tuple_sequence_comprehension', 'generic_tuple_sequence_unpack_error', 'generic_tuple_sequence_mutable_alias'):
            with self.subTest(name=name):self.check(name)
