"""Canonical builtin set update/clear preserve argument and pull boundaries."""
import unittest

import test_native_class_iterators as support

CASES={'ordinary_sources': 's={1}\n'
                     'result=s.update([2,3],(3,4),range(4,6))\n'
                     'print(result,sorted(s))\n'
                     'letters=set()\n'
                     "letters.update('aba',('c','a'))\n"
                     'print(sorted(letters))\n'
                     'octets=set()\n'
                     "octets.update(b'\\x01\\x02\\x01')\n"
                     'print(sorted(octets))\n',
 'dictionary_and_views': 's=set()\n'
                         'mapping={2:20,3:30}\n'
                         's.update(mapping,mapping.keys(),[4])\n'
                         'print(sorted(s))\n'
                         'pairs=set()\n'
                         'pairs.update(mapping.items(),[(4,40)])\n'
                         'print(sorted(pairs))\n',
 'argument_evaluation_before_iteration': 's={0}\n'
                                         'class Values:\n'
                                         ' def __init__(self,label,items):\n'
                                         '  self.label=label\n'
                                         '  self.items=items\n'
                                         ' def __iter__(self):\n'
                                         "  print('iterate',self.label,sorted(s))\n"
                                         '  return iter(self.items)\n'
                                         ' def __len__(self):\n'
                                         "  print('unexpected length hint')\n"
                                         '  return 9\n'
                                         'def make(label,items):\n'
                                         " print('make',label)\n"
                                         ' return Values(label,items)\n'
                                         "s.update(make('first',[1,2]),make('second',[3]))\n"
                                         'print(sorted(s))\n',
 'partial_before_later_noniterable': 's={1}\n'
                                     'def first():\n'
                                     ' yield 2\n'
                                     " print('first done',sorted(s))\n"
                                     'def bad():\n'
                                     " print('bad argument')\n"
                                     ' return 3\n'
                                     's.update(first(),bad())\n',
 'unhashable_after_partial_update': 's={1}\n'
                                    'def values():\n'
                                    ' yield 2\n'
                                    " print('partial',sorted(s))\n"
                                    ' yield []\n'
                                    " print('unreachable')\n"
                                    's.update(values())\n',
 'callback_clears_destination': 's={1}\n'
                                'def values():\n'
                                ' yield 2\n'
                                ' s.clear()\n'
                                " print('cleared',len(s))\n"
                                ' yield 3\n'
                                'print(s.update(values()),sorted(s))\n',
 'self_and_shared_sources': 's={1,2}\n'
                            'alias=s\n'
                            'print(s.update(s,[3],alias),s is alias,sorted(alias))\n'
                            'print(s.update(),sorted(s))\n',
 'owner_captured_before_argument_rebinding': 's={1}\n'
                                             'alias=s\n'
                                             'def other():\n'
                                             ' global s\n'
                                             ' s={9}\n'
                                             ' return [2]\n'
                                             's.update(other())\n'
                                             'print(sorted(alias),sorted(s),alias is s)\n',
 'keyword_error_evaluates_arguments_without_pulling': 's={1}\n'
                                                      'def values():\n'
                                                      " print('unexpected body')\n"
                                                      ' yield 2\n'
                                                      'def argument(label,value):\n'
                                                      ' print(label)\n'
                                                      ' return value\n'
                                                      "s.update(argument('positional',values()),bad=argument('keyword',[3]))\n",
 'clear_result_alias_and_argument_order': 's={1,2}\n'
                                          'alias=s\n'
                                          'print(s.clear(),len(alias),s is alias)\n'
                                          'def argument():\n'
                                          " print('argument')\n"
                                          ' return 3\n'
                                          's.clear(argument())\n',
 'clear_keyword_error': 's={1}\n'
                        'def argument():\n'
                        " print('keyword')\n"
                        ' return 3\n'
                        's.clear(bad=argument())\n',
 'generator_error_after_partial_mutation': 's={1}\n'
                                           'def values():\n'
                                           ' yield 2\n'
                                           " print('partial',sorted(s))\n"
                                           ' yield 1//0\n'
                                           's.update(values())\n',
 'map_filter_and_retained_expression': 's=set()\n'
                                       "s.update(map(int,['1','2','1']),filter(None,[0,3]),(x+4 "
                                       'for x in range(2)))\n'
                                       'print(sorted(s))\n',
 'tuple_keys_and_numeric_original_representative': 'pairs=set()\n'
                                                   "pairs.update([(1,'a'),(2,'b')],((1,'a'),))\n"
                                                   'print(sorted(pairs))\n'
                                                   'numbers={True}\n'
                                                   'numbers.update([1,2])\n'
                                                   'print(len(numbers),True in numbers,2 in '
                                                   'numbers)\n',
 'expanded_arguments_finish_before_updates': 's={1}\n'
                                             'def groups():\n'
                                             " print('expand',sorted(s))\n"
                                             ' yield [2]\n'
                                             " print('expand again',sorted(s))\n"
                                             ' yield (3,4)\n'
                                             'def later():\n'
                                             " print('later',sorted(s))\n"
                                             ' return [5]\n'
                                             's.update(*groups(),later())\n'
                                             'print(sorted(s))\n',
 'expanded_noniterable_fails_before_update': 's={1}\n'
                                             'def first():\n'
                                             " print('first argument')\n"
                                             ' return [2]\n'
                                             'def bad():\n'
                                             " print('bad expansion',sorted(s))\n"
                                             ' return 3\n'
                                             's.update(first(),*bad())\n',
 'expanded_clear_binding_error': 's={1}\n'
                                 'def arguments():\n'
                                 " print('expand',sorted(s))\n"
                                 ' yield 2\n'
                                 's.clear(*arguments())\n'}

CASES.update({'numeric_original_keys': 's={True}\n'
                          's.update([1,2])\n'
                          'print(sorted(s),len(s))\n'
                          's.update({False,3})\n'
                          'print(sorted(s))\n',
 'cross_family_set_aliases': 'def choose(flag):\n'
                             ' a={1,2}\n'
                             ' b={3,4}\n'
                             ' alias=a if flag else b\n'
                             ' a.update(alias,b)\n'
                             ' print(sorted(a),sorted(alias),sorted(b))\n'
                             'choose(True)\n'
                             'choose(False)\n',
 'source_cursor_shared': 'values=iter([2,3,4])\n'
                         's={1}\n'
                         'print(next(values))\n'
                         's.update(values,values)\n'
                         'print(sorted(s),next(values,None))\n',
 'iterable_source_mutation': 'items=[1,2]\n'
                             's=set()\n'
                             'def keep(x):\n'
                             ' if x<4:items.append(x+2)\n'
                             ' return x%2\n'
                             's.update(filter(keep,items))\n'
                             'print(sorted(s),items)\n',
 'custom_method_is_not_builtin': 'class Custom:\n'
                                 ' def update(self,*items):\n'
                                 "  print('custom',items)\n"
                                 '  return 17\n'
                                 ' def clear(self,label):\n'
                                 "  print('custom clear',label)\n"
                                 'print(Custom().update([1],[2]))\n'
                                 "Custom().clear('label')\n",
 'empty_and_zero_sources': 's=set()\nprint(s.update(),s.update((),[]),s.clear(),len(s))\n',
 'star_empty': 's={1}\nprint(s.update(*()),sorted(s))\nprint(s.clear(*()),len(s))\n',
 'single_star_binding': 's={1}\n'
                        'def bad():\n'
                        " print('before',sorted(s))\n"
                        ' return 3\n'
                        's.update(*bad())\n',
 'keyword_prevents_noniterable_sources': 's={1}\n'
                                         'def bad():\n'
                                         " print('argument')\n"
                                         ' return 3\n'
                                         's.update(bad(),name=[])\n',
 'nested_unhashable_key': 's={(1,)}\n'
                          'def values():\n'
                          ' yield (2,)\n'
                          " print('partial',sorted(s))\n"
                          ' yield ([],)\n'
                          's.update(values())\n'})

CASES.update({'factory_custom_expanded_receiver': 'class Custom:\n'
                                     ' def update(self,*items):\n'
                                     "  print('method',items)\n"
                                     '  return 8\n'
                                     'def factory():\n'
                                     " print('factory')\n"
                                     ' return Custom()\n'
                                     'print(factory().update(*[1,2]))\n',
 'late_construct_second_source': 's={0}\n'
                                 'first=[1]\n'
                                 'second=[2]\n'
                                 'def source():\n'
                                 ' yield 3\n'
                                 ' second.append(4)\n'
                                 " print('after first',sorted(s))\n"
                                 's.update(source(),second)\n'
                                 'print(sorted(s))\n',
 'clear_expanded_uninhabited_payload': 's={1}\n'
                                       'def arguments():\n'
                                       " print('expand',sorted(s))\n"
                                       ' yield []\n'
                                       's.clear(*arguments())\n',
 'noniterable_after_strings': "s={'a'}\n"
                              'def argument():\n'
                              " print('argument',sorted(s))\n"
                              ' return 7\n'
                              "s.update('bc',argument())\n",
 'unhashable_mapping_after_partial': 's={1}\n'
                                     'def source():\n'
                                     ' yield 2\n'
                                     " print('after',sorted(s))\n"
                                     ' yield {}\n'
                                     's.update(source())\n',
 'update_result_in_expression': 's={1}\nprint(s.update([2]) is None,sorted(s))\n'})

CASES.update({'sole_star_keyword_before_materialization': 's={1}\n'
                                             'def groups():\n'
                                             " print('pull',sorted(s))\n"
                                             ' yield [2]\n'
                                             'def keyword():\n'
                                             " print('keyword',sorted(s))\n"
                                             ' return 9\n'
                                             's.update(*groups(),bad=keyword())\n',
 'sole_bad_star_keyword_before_error': 's={1}\n'
                                       'def bad():\n'
                                       " print('argument')\n"
                                       ' return 3\n'
                                       'def keyword():\n'
                                       " print('keyword')\n"
                                       ' return 9\n'
                                       's.clear(*bad(),name=keyword())\n',
 'multiple_star_keyword_after_materialization': 's={1}\n'
                                                'def groups(label):\n'
                                                " print('pull',label)\n"
                                                ' yield [2]\n'
                                                'def keyword():\n'
                                                " print('keyword')\n"
                                                ' return 9\n'
                                                "s.update(*groups('first'),*groups('second'),bad=keyword())\n"})

CASES.update({'named_tuple_original_key_type': 'from typing import NamedTuple\n'
                                  'class Key(NamedTuple):\n'
                                  ' value:int\n'
                                  's=set()\n'
                                  's.update([Key(2),Key(1),Key(2)])\n'
                                  'print(sorted(s))\n',
 'unhashable_mapping_callback': 's={1}\n'
                                'def observe(value):\n'
                                " print('partial',sorted(s))\n"
                                ' return value\n'
                                's.update(map(observe,[2,{}]))\n'})

class SetMethodTests(unittest.TestCase):
    check=support.IteratorExecutionTests.check
    cases=CASES

    def test_ordinary_sources(self):
        self.check('ordinary_sources')

    def test_dictionary_and_views(self):
        self.check('dictionary_and_views')

    def test_argument_evaluation_before_iteration(self):
        self.check('argument_evaluation_before_iteration')

    def test_partial_before_later_noniterable(self):
        self.check('partial_before_later_noniterable')

    def test_unhashable_after_partial_update(self):
        self.check('unhashable_after_partial_update')

    def test_callback_clears_destination(self):
        self.check('callback_clears_destination')

    def test_self_and_shared_sources(self):
        self.check('self_and_shared_sources')

    def test_owner_captured_before_argument_rebinding(self):
        self.check('owner_captured_before_argument_rebinding')

    def test_keyword_error_evaluates_arguments_without_pulling(self):
        self.check('keyword_error_evaluates_arguments_without_pulling')

    def test_clear_result_alias_and_argument_order(self):
        self.check('clear_result_alias_and_argument_order')

    def test_clear_keyword_error(self):
        self.check('clear_keyword_error')

    def test_generator_error_after_partial_mutation(self):
        self.check('generator_error_after_partial_mutation')

    def test_map_filter_and_retained_expression(self):
        self.check('map_filter_and_retained_expression')

    def test_tuple_keys_and_numeric_original_representative(self):
        self.check('tuple_keys_and_numeric_original_representative')

    def test_expanded_arguments_finish_before_updates(self):
        self.check('expanded_arguments_finish_before_updates')

    def test_expanded_noniterable_fails_before_update(self):
        self.check('expanded_noniterable_fails_before_update')

    def test_expanded_clear_binding_error(self):
        self.check('expanded_clear_binding_error')

    def test_numeric_original_keys(self):
        self.check('numeric_original_keys')

    def test_cross_family_set_aliases(self):
        self.check('cross_family_set_aliases')

    def test_source_cursor_shared(self):
        self.check('source_cursor_shared')

    def test_iterable_source_mutation(self):
        self.check('iterable_source_mutation')

    def test_custom_method_is_not_builtin(self):
        self.check('custom_method_is_not_builtin')

    def test_empty_and_zero_sources(self):
        self.check('empty_and_zero_sources')

    def test_star_empty(self):
        self.check('star_empty')

    def test_single_star_binding(self):
        self.check('single_star_binding')

    def test_keyword_prevents_noniterable_sources(self):
        self.check('keyword_prevents_noniterable_sources')

    def test_nested_unhashable_key(self):
        self.check('nested_unhashable_key')

    def test_factory_custom_expanded_receiver(self):
        self.check('factory_custom_expanded_receiver')

    def test_late_construct_second_source(self):
        self.check('late_construct_second_source')

    def test_clear_expanded_uninhabited_payload(self):
        self.check('clear_expanded_uninhabited_payload')

    def test_noniterable_after_strings(self):
        self.check('noniterable_after_strings')

    def test_unhashable_mapping_source_generator_boundary(self):
        result=support.transpile(CASES['unhashable_mapping_after_partial'],support.TranspileOptions(license='none'))
        self.assertFalse(result.success)
        self.assertTrue(any('source generator retains' in diagnostic.message for diagnostic in result.diagnostics),result.diagnostics)

    def test_update_result_in_expression(self):
        self.check('update_result_in_expression')

    def test_sole_star_keyword_before_materialization(self):
        self.check('sole_star_keyword_before_materialization')

    def test_sole_bad_star_keyword_before_error(self):
        self.check('sole_bad_star_keyword_before_error')

    def test_multiple_star_keyword_after_materialization(self):
        self.check('multiple_star_keyword_after_materialization')

    def test_order_observers_are_not_admitted(self):
        sources=("values={1,2}\nfor value in values:print(value)\n",
                 "values={1,2}\nprint(list(values))\n",
                 "s=set()\ns.update(filter(None,{1,2}))\n")
        for source in sources:
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=support.transpile(source,support.TranspileOptions(integer=mode,license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(all(d.code=='E006' and d.line>0 for d in result.diagnostics),result.diagnostics)

    def test_unimplemented_hash_and_stored_methods_are_named(self):
        sources=("s=set()\ns.update([1.5])\n",
                 "s={1}\nupdate=s.update\nupdate([2])\n")
        for source in sources:
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=support.transpile(source,support.TranspileOptions(integer=mode,license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(all(d.code=='E006' and d.line>0 for d in result.diagnostics),result.diagnostics)
                    self.assertTrue(any('update' in d.message or 'hash' in d.message for d in result.diagnostics),result.diagnostics)

    def test_named_tuple_original_key_type(self):
        self.check('named_tuple_original_key_type')

    def test_unhashable_mapping_callback(self):
        self.check('unhashable_mapping_callback')

if __name__=="__main__":unittest.main()
