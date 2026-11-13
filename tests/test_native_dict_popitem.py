"""Canonical dict popitem preserves owners, signatures and typed tuple values."""
import unittest
import test_native_annotations_assertions as support
from py2fastrust import TranspileOptions,transpile

CASES = {'ordinary_lifo_queries': ('mapping={3:30,1:10,2:20}\nprint(mapping.popitem(),mapping.popitem(),mapping)\nmapping[4]=40\nprint(mapping.popitem(),mapping.popitem(),mapping)\n', ('',)), 'empty_error': ("class Holder:\n def __init__(self):self.mapping={}\nholder=Holder()\nprint('before')\nholder.mapping.popitem()\n", ('',)), 'framed_rows_alias': ('class Holder:\n def __init__(self):self.mapping={1:[3],2:[4]}\nholder=Holder()\nshared=holder.mapping[2]\nkey,row=holder.mapping.popitem()\nrow.append(7)\nprint(key,row,shared,row is shared,holder.mapping)\n', ('',)), 'receiver_before_arguments': ("mapping={1:10}\nold=mapping\ndef owner():\n print('owner')\n return mapping\ndef argument():\n global mapping\n print('argument')\n mapping={2:20}\n return 9\nowner().popitem(argument())\n", ('',)), 'keywords_before_error': ('mapping={1:10}\ndef effect(value):\n print(value,mapping)\n return value\nmapping.popitem(effect(1),flag=effect(2))\n', ('',)), 'keyword_only_error': ("mapping={1:10}\ndef effect():\n print('keyword',mapping)\n return 1\nmapping.popitem(last=effect())\n", ('',)), 'bound_alias_identity': ('mapping={1:10,2:20}\nmethod=mapping.popitem\nalias=method\nfresh=mapping.popitem\nprint(method is alias,method is fresh,method==fresh)\nmapping={9:90}\nprint(alias(),fresh(),mapping)\n', ('',)), 'bound_argument_rebinding': ("mapping={1:10,2:20}\nmethod=mapping.popitem\ndef change():\n global mapping\n mapping={7:70}\n print('change')\n return 5\nmethod(change())\n", ('',)), 'bound_empty_error': ('mapping={1:10}\nmethod=mapping.popitem\nprint(method())\nmethod()\n', ('',)), 'bool_original_key': ('class Holder:\n def __init__(self):self.mapping={True:[1]}\nholder=Holder()\nholder.mapping[1]=[9]\nprint(holder.mapping.popitem())\n', ('',)), 'counter_builtin': ("from collections import Counter\nmapping=Counter(a=2,b=0,c=-1)\nprint(mapping.popitem(),mapping.popitem(),mapping)\nmapping['z']=4\nmethod=mapping.popitem\nprint(method(),mapping)\n", ('',)), 'defaultdict_no_factory': ("from collections import defaultdict\ndef factory():\n print('factory')\n return []\nmapping=defaultdict(factory,{1:[7],2:[8]})\nmethod=mapping.popitem\nprint(method(),mapping.popitem())\nprint('empty')\nmethod()\n", ('',)), 'counter_invalid_arguments': ('from collections import Counter\nmapping=Counter({1:3})\ndef effect():\n print(mapping)\n return 1\nmapping.popitem(effect())\n', ('',)), 'defaultdict_invalid_keywords': ('from collections import defaultdict\nmapping=defaultdict(int,{1:3})\ndef effect():\n print(dict(mapping))\n return 1\nmapping.popitem(option=effect())\n', ('',)), 'distinct_receiver_aliases': ('first={1:10}\nsecond={2:20}\nmethod=first.popitem\nother=second.popitem\nprint(method==other,method is other)\nprint(method(),other())\n', ('',)), 'custom_same_name': ('class Source:\n def popitem(self,last=True):return last,7\nsource=Source()\nprint(source.popitem(last=False))\n', ('',)), 'error_argument_precedes_binding': ("mapping={1:10}\ndef effect():\n print('effect')\n return 1//0\nmapping.popitem(effect())\n", ('',)), 'pop_reinsert_live_cursor': ('mapping={1:10,2:20,3:30}\ncursor=iter(mapping.items())\nprint(next(cursor))\nprint(mapping.popitem())\nmapping[4]=40\nvalues=[]\nvalues.extend(cursor)\nprint(values)\n', ('',)), 'peer_keyword_merge_before_copy': ("source = dict(a=10, b=11, c=12, d=13, e=14)\nsource.popitem()\nmapping = dict(source, e=14)\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping['a']\nmapping['z'] = 19\nprint(list(cursor))\n", ('',)), 'peer_popitem_retains_consumed_budget': ('mapping = {0:10, 1:11, 2:12, 3:13, 4:14}\nprint(mapping.popitem())\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[0]\nmapping[9] = 19\nprint(list(cursor))\n', ('',))}

class DictPopitemExecutionTests(unittest.TestCase):
    pass

ORIGIN_BOUNDARIES = {'direct_custom_keys': 'class Source:\n def keys(self):return (1,2,3)\n def __getitem__(self,key):return key*10\n def __iter__(self):return iter(((9,90),))\nmapping=dict(Source())\nprint(mapping.popitem())\n', 'stored_custom_keys': 'class Source:\n def keys(self):return (1,2,3)\n def __getitem__(self,key):return key*10\n def __iter__(self):return iter(((9,90),))\nmapping=dict(Source())\nmethod=mapping.popitem\nprint(method())\n'}

class DictPopitemLoweringTests(unittest.TestCase):
    def test_immediate_framed_operation_has_no_bound_callable_wrapper(self):
        source=CASES['framed_rows_alias'][0]
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('native_dict_popitem(',result.rust_source)
            self.assertNotIn('struct NativeMappingMethod_',result.rust_source)

    def test_actual_custom_keys_constructor_origins_remain_positioned_boundaries(self):
        for source in ORIGIN_BOUNDARIES.values():
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer))
                self.assertFalse(result.success)
                self.assertTrue(any(d.code=='E006'and d.line==6 and 'origin' in d.message for d in result.diagnostics),result.diagnostics)

    def test_unrelated_mapping_methods_keep_named_diagnostics(self):
        source='class Owner:\n def __init__(self):self.value={1:2}\nowner=Owner()\nowner.value.update(((3,4),))\n'
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and 'update' in d.message and d.line==4 for d in result.diagnostics),result.diagnostics)


def _case(values):
    def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*values)
    return test

for _name,_values in CASES.items():
    setattr(DictPopitemExecutionTests,'test_'+_name,_case(_values))

if __name__=='__main__':unittest.main()
