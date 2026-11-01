"""Canonical native members preserve captured calls and Python effects."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'bind_duplicate_initial': 'from functools import reduce\nreduce(lambda a,b:a+b,[1],0,initial=9)\n',
 'bind_four_args': 'from functools import reduce\nreduce(lambda a,b:a+b,[1],0,9)\n',
 'bind_no_args': 'from functools import reduce\nreduce()\n',
 'bind_one_arg': 'from functools import reduce\nreduce(lambda a,b:a+b)\n',
 'bind_positional_only_keywords': 'from functools import reduce\n'
                                  'reduce(function=lambda a,b:a+b,iterable=[1],initial=0)\n',
 'bind_unknown_keyword': 'from functools import reduce\nreduce(lambda a,b:a+b,[1],initializer=0)\n',
 'boolean_first_value_and_gcd_result': 'from functools import reduce\n'
                                       'from math import gcd\n'
                                       'print(reduce(gcd,[True]),reduce(gcd,[True,2]),reduce(lambda '
                                       'a,b:a&b,[True,False]))\n',
 'bound_method_callback': 'from functools import reduce\n'
                          'class Counter:\n'
                          ' def __init__(self):self.calls=0\n'
                          ' def add(self,a,b):\n'
                          '  self.calls+=1\n'
                          '  return a+b\n'
                          'c=Counter()\n'
                          'print(reduce(c.add,[1,2,3],0),c.calls)\n',
 'builtin_extrema': 'from functools import reduce\n'
                    'print(reduce(max,[3,7,2,7]),reduce(min,range(5),99))\n',
 'callback_exception_frames': 'from functools import reduce\n'
                              'def fail(a,b):return a//b\n'
                              'print(reduce(fail,[2,0],8))\n',
 'callback_field_effects': 'from functools import reduce\n'
                           'class Box:\n'
                           ' def __init__(self):self.value=0\n'
                           'box=Box()\n'
                           'def add(a,b):\n'
                           ' box.value+=b\n'
                           ' return a+b\n'
                           'for i in range(2):\n'
                           ' print(box.value,reduce(add,[1,2],0),box.value)\n',
 'callback_reentrant_source': 'from functools import reduce\n'
                              'source=iter([1,2,3,4])\n'
                              'def add(a,b):\n'
                              ' print(a,b)\n'
                              ' if b==1:print("taken",next(source))\n'
                              ' return a+b\n'
                              'print(reduce(add,source,0),list(source))\n',
 'callback_stop_iteration': 'from functools import reduce\n'
                            'def stop(a,b):return next(iter(()))\n'
                            'reduce(stop,[1,2],0)\n',
 'captured_constructor_alias': 'from functools import reduce as fold\n'
                               'original=fold\n'
                               'fold=lambda callback,values,initial=0:99\n'
                               'print(original(lambda a,b:a+b,[1,2,3],0),fold(None,[]))\n',
 'changed_accumulator_type': 'from functools import reduce\n'
                             'print(reduce(lambda a,b:str(a)+str(b),[1,2,3]))\n',
 'changed_result_type_method': 'from functools import reduce\n'
                               'text=reduce(lambda a,b:str(a)+str(b),[1,2,3])\n'
                               'print(text.split("2"))\n',
 'closure_callback': 'from functools import reduce\n'
                     'def fold(delta):\n'
                     ' def combine(a,b):return a+b+delta\n'
                     ' return reduce(combine,[1,2,3],0)\n'
                     'print(fold(1),fold(2))\n',
 'empty_initial_identity': 'from functools import reduce\n'
                           'seed=[9]\n'
                           'answer=reduce(None,[],seed)\n'
                           'print(answer is seed,answer)\n',
 'empty_initial_none': 'from functools import reduce\n'
                       'print(reduce(None,[],None),reduce(3,[],initial=None))\n',
 'empty_without_initial': 'from functools import reduce\nreduce(None,[])\n',
 'explicit_none_initial': 'from functools import reduce\n'
                          'def combine(a,b):return b if a is None else a+b\n'
                          'print(reduce(combine,[2,3],None))\n',
 'finite_callback_alternatives': 'from functools import reduce\n'
                                 'def fold(callback):return reduce(callback,[1,2,3],4)\n'
                                 'print(fold(max),fold(lambda a,b:a+b))\n',
 'finite_source_families': 'from functools import reduce\n'
                           'def total(source):return reduce(lambda a,b:a+int(b),source,0)\n'
                           'print(total([1,2]),total((3,4)),total(range(3)),total(b"12"),total("34"))\n',
 'gcd_builtin_member': 'from functools import reduce\n'
                       'from math import gcd\n'
                       'print(reduce(gcd,[48,18,30]),reduce(gcd,range(6,19,6),0))\n',
 'generator_body_after_arguments': 'from functools import reduce\n'
                                   'def mark(label,value):\n'
                                   ' print(label)\n'
                                   ' return value\n'
                                   'print(reduce(mark("callback",lambda '
                                   'a,b:a+b),(mark("body",v)for v in '
                                   'mark("source",[1,2])),mark("initial",0)))\n',
 'generator_body_stop_pep479': 'from functools import reduce\n'
                               'reduce(lambda a,b:a+b,(next(iter(()))for v in [1]),0)\n',
 'generator_callback_stop_propagates': 'from functools import reduce\n'
                                       'def stop(a,b):return next(iter(()))\n'
                                       'reduce(stop,(v for v in [1,2]),0)\n',
 'generator_capture_before_initial': 'from functools import reduce\n'
                                     'values=[1,2]\n'
                                     'def initial():\n'
                                     ' values.append(3)\n'
                                     ' return 10\n'
                                     'print(reduce(lambda a,b:a+b,(v for v in '
                                     'values),initial()))\n',
 'generator_direct_sink': 'from functools import reduce\n'
                          'print(reduce(lambda a,b:a+b,(v*v for v in range(6)),0))\n',
 'initial_keyword': 'from functools import reduce\n'
                    'print(reduce(lambda a,b:a+b,[2,3],initial=10))\n',
 'initializer_clears_source': 'from functools import reduce\n'
                              'values=[1,2,3]\n'
                              'def initial():\n'
                              ' values.clear()\n'
                              ' return 9\n'
                              'print(reduce(None,values,initial()),values)\n',
 'list_addition_does_not_mutate_seed': 'from functools import reduce\n'
                                       'from operator import add\n'
                                       'seed=[]\n'
                                       'result=reduce(add,[[1],[2],[3]],seed)\n'
                                       'print(result,seed,result is seed)\n',
 'mutable_accumulator_identity': 'from functools import reduce\n'
                                 'seed=[]\n'
                                 'def append(acc,value):\n'
                                 ' acc.append(value)\n'
                                 ' return acc\n'
                                 'answer=reduce(append,range(4),seed)\n'
                                 'print(answer is seed,seed,answer)\n',
 'noniterable': 'from functools import reduce\nreduce(None,3,0)\n',
 'nullable_initial_and_none_result': 'from functools import reduce\n'
                                     'def combine(a,b):return None\n'
                                     'print(reduce(combine,[1,2],5))\n'
                                     'print(reduce(combine,[],5))\n',
 'operator_alias_and_shadow': 'from functools import reduce\n'
                              'from operator import mul as operation\n'
                              'saved=operation\n'
                              'operation=lambda a,b:99\n'
                              'print(reduce(saved,[2,3,4],1),reduce(operation,[2,3],1))\n',
 'operator_product_and_bits': 'from functools import reduce\n'
                              'from operator import mul,or_,and_,xor\n'
                              'print(reduce(mul,[2,3,4],1),reduce(or_,[1,2,8],0),reduce(and_,[15,11,7]),reduce(xor,[1,2,3,4],0))\n',
 'qualified_module_and_parameter': 'import functools as tools\n'
                                   'def apply(operation,callback,values,seed):return '
                                   'operation(callback,values,seed)\n'
                                   'print(apply(tools.reduce,lambda a,b:a|b,[1,4,16],0))\n',
 'recursive_callback': 'from functools import reduce\n'
                       'def add(a,b):\n'
                       ' if b:return add(a+1,b-1)\n'
                       ' return a\n'
                       'print(reduce(add,[1,2,3],0))\n',
 'single_item_identity': 'from functools import reduce\n'
                         'item=[1]\n'
                         'print(reduce(None,[item]) is item,reduce(3,[item]) is item)\n',
 'single_unsupported_callback_body': 'from functools import reduce\n'
                                     'def unused(a,b):return eval("unreachable")\n'
                                     'print(reduce(unused,[7]))\n',
 'single_wrong_arity_callback': 'from functools import reduce\n'
                                'def bad(a):return a\n'
                                'print(reduce(bad,[7]),reduce(bad,[],8))\n',
 'source_exception_frames': 'from functools import reduce\n'
                            'def fail(v):return 1//v\n'
                            'print(reduce(lambda a,b:a+b,map(fail,[1,0]),0))\n',
 'source_mutation_during_callback': 'from functools import reduce\n'
                                    'values=[1,2]\n'
                                    'def add(a,b):\n'
                                    ' if b<4:values.append(b+2)\n'
                                    ' return a+b\n'
                                    'print(reduce(add,values,0),values)\n',
 'source_product_and_order': 'from functools import reduce\n'
                             'def combine(a,b):\n'
                             ' print(a,b)\n'
                             ' return a*b\n'
                             'print(reduce(combine,[2,3,4],1))\n',
 'source_stop_and_resumption': 'from functools import reduce\n'
                               'def visit(v):\n'
                               ' print("source",v)\n'
                               ' if v==2:return next(iter(()))\n'
                               ' return v\n'
                               'source=map(visit,[1,2,3,4])\n'
                               'print(reduce(lambda a,b:a+b,source,0),list(source))\n',
 'string_accumulator': 'from functools import reduce\n'
                       'print(reduce(lambda a,b:a+b,["a","b","c"],"start:"))\n',
 'unicode_string_fold': 'from functools import reduce\n'
                        'print(reduce(lambda a,b:a+b,["猫","🐈","é"],""))\n',
 'wrong_arity_callback_called': 'from functools import reduce\n'
                                'def bad(a):return a\n'
                                'reduce(bad,[1,2])\n',
 'wrong_callback_none_called': 'from functools import reduce\nreduce(None,[1,2])\n',
 'wrong_callback_with_initial': 'from functools import reduce\nreduce(3,[1],None)\n'}

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ReduceTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_gcd_builtin_member(self):self.check('gcd_builtin_member')

    def test_operator_product_and_bits(self):self.check('operator_product_and_bits')

    def test_source_product_and_order(self):self.check('source_product_and_order')

    def test_builtin_extrema(self):self.check('builtin_extrema')

    def test_string_accumulator(self):self.check('string_accumulator')

    def test_changed_accumulator_type(self):self.check('changed_accumulator_type')

    def test_changed_result_type_method(self):self.check('changed_result_type_method')

    def test_mutable_accumulator_identity(self):self.check('mutable_accumulator_identity')

    def test_single_item_identity(self):self.check('single_item_identity')

    def test_empty_initial_identity(self):self.check('empty_initial_identity')

    def test_empty_initial_none(self):self.check('empty_initial_none')

    def test_empty_without_initial(self):self.check('empty_without_initial')

    def test_explicit_none_initial(self):self.check('explicit_none_initial')

    def test_single_wrong_arity_callback(self):self.check('single_wrong_arity_callback')

    def test_single_unsupported_callback_body(self):self.check('single_unsupported_callback_body')

    def test_wrong_arity_callback_called(self):self.check('wrong_arity_callback_called')

    def test_wrong_callback_none_called(self):self.check('wrong_callback_none_called')

    def test_wrong_callback_with_initial(self):self.check('wrong_callback_with_initial')

    def test_initial_keyword(self):self.check('initial_keyword')

    def test_captured_constructor_alias(self):self.check('captured_constructor_alias')

    def test_qualified_module_and_parameter(self):self.check('qualified_module_and_parameter')

    def test_bound_method_callback(self):self.check('bound_method_callback')

    def test_closure_callback(self):self.check('closure_callback')

    def test_recursive_callback(self):self.check('recursive_callback')

    def test_generator_direct_sink(self):self.check('generator_direct_sink')

    def test_generator_capture_before_initial(self):self.check('generator_capture_before_initial')

    def test_generator_body_after_arguments(self):self.check('generator_body_after_arguments')

    def test_generator_callback_stop_propagates(self):self.check('generator_callback_stop_propagates')

    def test_generator_body_stop_pep479(self):self.check('generator_body_stop_pep479')

    def test_source_stop_and_resumption(self):self.check('source_stop_and_resumption')

    def test_callback_stop_iteration(self):self.check('callback_stop_iteration')

    def test_callback_exception_frames(self):self.check('callback_exception_frames')

    def test_source_exception_frames(self):self.check('source_exception_frames')

    def test_source_mutation_during_callback(self):self.check('source_mutation_during_callback')

    def test_initializer_clears_source(self):self.check('initializer_clears_source')

    def test_callback_reentrant_source(self):self.check('callback_reentrant_source')

    def test_callback_field_effects(self):self.check('callback_field_effects')

    def test_finite_source_families(self):self.check('finite_source_families')

    def test_nullable_initial_and_none_result(self):self.check('nullable_initial_and_none_result')

    def test_boolean_first_value_and_gcd_result(self):self.check('boolean_first_value_and_gcd_result')

    def test_list_addition_does_not_mutate_seed(self):self.check('list_addition_does_not_mutate_seed')

    def test_operator_alias_and_shadow(self):self.check('operator_alias_and_shadow')

    def test_finite_callback_alternatives(self):self.check('finite_callback_alternatives')

    def test_unicode_string_fold(self):self.check('unicode_string_fold')

    def test_bind_no_args(self):self.check('bind_no_args')

    def test_bind_one_arg(self):self.check('bind_one_arg')

    def test_bind_four_args(self):self.check('bind_four_args')

    def test_bind_unknown_keyword(self):self.check('bind_unknown_keyword')

    def test_bind_positional_only_keywords(self):self.check('bind_positional_only_keywords')

    def test_bind_duplicate_initial(self):self.check('bind_duplicate_initial')

    def test_noniterable(self):self.check('noniterable')


SINGLE_CASES={'single_callback_changes_to_list': 'from functools import reduce\n'
                                    'print(reduce(lambda a,b:[a,b],[1,2]))\n',
 'single_callback_with_initial_changes_to_list': 'from functools import reduce\n'
                                                 'print(reduce(lambda a,b:[a,b],[2],1))\n',
 'single_operator_true_division': 'from functools import reduce\n'
                                  'from operator import truediv\n'
                                  'print(reduce(truediv,[12,3]))\n'}

class ReduceSingleCallbackTests(unittest.TestCase):
    cases=SINGLE_CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_single_callback_changes_to_list(self):self.check('single_callback_changes_to_list')

    def test_single_callback_with_initial_changes_to_list(self):self.check('single_callback_with_initial_changes_to_list')

    def test_single_operator_true_division(self):self.check('single_operator_true_division')
