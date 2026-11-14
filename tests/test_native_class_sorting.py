"""Captured sorting callbacks retain stable order, effects and shared identity."""
import unittest
import test_native_module_linking as support


CASES={'bound_method_key_once_stable': 'class Ranker:\n'
                                 '    def __init__(self):self.calls=0\n'
                                 '    def rank(self,item):\n'
                                 '        self.calls+=1\n'
                                 '        print("key",item,self.calls)\n'
                                 '        return item%2\n'
                                 'ranker=Ranker()\n'
                                 'callback=ranker.rank\n'
                                 'values=[4,1,2,3]\n'
                                 'print(sorted(values,key=callback,reverse=True))\n'
                                 'values.sort(key=callback)\n'
                                 'print(values,ranker.calls)\n',
 'bound_temporary_receiver_and_key_default': 'class Ranker:\n'
                                             '    def __init__(self,bias):self.bias=bias\n'
                                             '    def rank(self,item,scale=2):return '
                                             '-item*scale+self.bias\n'
                                             'callback=Ranker(7).rank\n'
                                             'values=[4,1,2,3]\n'
                                             'values.sort(key=callback)\n'
                                             'print(values)\n',
 'closure_key_captures_current_cell': 'class Marker:pass\n'
                                      'def factory():\n'
                                      '    bias=3\n'
                                      '    def key(item):return item%bias\n'
                                      '    bias=2\n'
                                      '    return key\n'
                                      'key=factory()\n'
                                      'values=[4,1,2,3]\n'
                                      'print(sorted(values,key=key))\n',
 'compiled_key_default_alias_stable_reverse': 'class Marker:pass\n'
                                              'def order(item,offset=0):\n'
                                              '    print("key",item)\n'
                                              '    return item[0]+offset\n'
                                              'saved=order\n'
                                              'values=[(2,9),(1,8),(2,7),(1,6)]\n'
                                              'print(sorted(values,key=saved,reverse=True))\n'
                                              'values.sort(key=saved)\n'
                                              'print(values)\n',
 'empty_noncallable_key_skips_call': 'class Marker:pass\n'
                                     'values=[]\n'
                                     'values.sort(key=42)\n'
                                     'print(values,sorted((),key=42))\n',
 'key_error_before_modified_error': 'class Marker:pass\n'
                                    'values=[3,1,2]\n'
                                    'def order(item):\n'
                                    '    print(item,len(values))\n'
                                    '    values.append(9)\n'
                                    '    return 10//(item-1)\n'
                                    'values.sort(key=order)\n',
 'key_none_alternatives': 'class Marker:pass\n'
                          'def key(item):return -item\n'
                          'for flag in (True,False):\n'
                          '    selected=key if flag else None\n'
                          '    print(sorted([3,1,2],key=selected))\n',
 'key_retains_original_callee_during_rebind': 'class Marker:pass\n'
                                              'def other(item):\n'
                                              '    print("other")\n'
                                              '    return -item\n'
                                              'def original(item):\n'
                                              '    global key\n'
                                              '    key=other\n'
                                              '    print("original",item)\n'
                                              '    return item\n'
                                              'key=original\n'
                                              'print(sorted([3,1,2],key=key))\n'
                                              'print(sorted([3,1,2],key=key))\n',
 'lambda_tuple_key_lamps': 'class Marker:pass\n'
                           'lamps=[(4,9),(2,3),(4,7),(2,3)]\n'
                           'lamps.sort(key=lambda rc:(-rc[0],rc[1]))\n'
                           'print(lamps)\n',
 'list_empty_during_key_callbacks': 'class Marker:pass\n'
                                    'values=[3,1,2]\n'
                                    'alias=values\n'
                                    'def order(item):\n'
                                    '    print("key",item,len(alias))\n'
                                    '    return item\n'
                                    'values.sort(key=order)\n'
                                    'print(values,alias,values is alias)\n',
 'mixed_unorderable_key_error': 'class Marker:pass\nvalues=[1,"a"]\nprint(sorted(values))\n',
 'mutation_append_pop_is_detected': 'class Marker:pass\n'
                                    'values=[3,1,2]\n'
                                    'def order(item):\n'
                                    '    print(item,len(values))\n'
                                    '    values.append(9)\n'
                                    '    values.pop()\n'
                                    '    return item\n'
                                    'values.sort(key=order)\n',
 'nested_mutable_keys_preserve_identity': 'class Holder:\n'
                                          '    def __init__(self,rank,name):\n'
                                          '        self.rank=rank\n'
                                          '        self.name=name\n'
                                          'def key(item):return item.rank\n'
                                          'a=Holder([2],"a")\n'
                                          'b=Holder([1],"b")\n'
                                          'c=Holder([2],"c")\n'
                                          'values=[a,b,c]\n'
                                          'values.sort(key=key)\n'
                                          'print([item.name for item in values],values[1] is '
                                          'a,values[2] is c)\n',
 'noncallable_key_one_item_error': 'class Marker:pass\nvalues=[1]\nvalues.sort(key=42)\n',
 'none_keys_unorderable': 'class Marker:pass\nvalues=[None,None]\nprint(sorted(values))\n',
 'plain_sorted_preserves_input': 'class Marker:pass\na=[5,1,3,1]\nb=sorted(a)\nprint(a,b,a is b)\n',
 'reverse_truth_after_materialization': 'class Marker:pass\n'
                                        'reverse=[]\n'
                                        'def choose(x):\n'
                                        '    reverse.append(1)\n'
                                        '    return True\n'
                                        'source=filter(choose,[3,1,2])\n'
                                        'print(sorted(source,reverse=reverse))\n',
 'sort_bad_keyword_after_argument_effect': 'class Marker:pass\n'
                                           'def mark():\n'
                                           '    print("keyword")\n'
                                           '    return 1\n'
                                           'values=[2,1]\n'
                                           'values.sort(unknown=mark())\n',
 'sort_callback_invalidates_loop_field_cache': 'class Box:\n'
                                               '    def __init__(self):self.value=0\n'
                                               'box=Box()\n'
                                               'def choose(x):\n'
                                               '    box.value+=1\n'
                                               '    return x\n'
                                               'for i in range(3):\n'
                                               '    print(box.value)\n'
                                               '    values=[2,1]\n'
                                               '    values.sort(key=choose)\n'
                                               '    print(box.value)\n',
 'sorted_alias_builtin_len': 'class Marker:pass\n'
                             'from builtins import sorted as ordered\n'
                             'values=["aaa","b","cc","d"]\n'
                             'print(ordered(values,key=len,reverse=True))\n',
 'sorted_callback_invalidates_loop_field_cache': 'class Box:\n'
                                                 '    def __init__(self):self.value=0\n'
                                                 'box=Box()\n'
                                                 'def choose(x):\n'
                                                 '    box.value+=1\n'
                                                 '    return x\n'
                                                 'for i in range(3):\n'
                                                 '    print(box.value)\n'
                                                 '    values=sorted([2,1],key=choose)\n'
                                                 '    print(box.value)\n',
 'sorted_materializes_before_keys': 'class Marker:pass\n'
                                    'values=[3,1,2]\n'
                                    'def order(item):\n'
                                    '    values.append(8)\n'
                                    '    print("key",item,len(values))\n'
                                    '    return item\n'
                                    'result=sorted(values,key=order)\n'
                                    'print(result,values)\n',
 'tuple_none_prefix_uses_equality': 'class Marker:pass\n'
                                    'values=[(None,4),(None,1),(None,2)]\n'
                                    'print(sorted(values))\n',
 'unknown_keyword_after_materialization': 'class Marker:pass\n'
                                          'def choose(x):\n'
                                          '    print("item",x)\n'
                                          '    return True\n'
                                          'def mark():\n'
                                          '    print("keyword")\n'
                                          '    return 9\n'
                                          'source=filter(choose,[3,1,2])\n'
                                          'print(sorted(source,unknown=mark()))\n'}


class NativeClassSortingTests(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise


def _test(source):
    def test(self):self.exercise({'main.py':source})
    return test


for _name,_source in CASES.items():
    setattr(NativeClassSortingTests,'test_'+_name,_test(_source))


class RequiredSortingProtocolTests(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise

    def test_original_required_float_ordering_executes_against_cpython(self):
        source='class Marker:pass\nprint(sorted([1.0,2.0]))\n'
        self.exercise({'main.py':source})
