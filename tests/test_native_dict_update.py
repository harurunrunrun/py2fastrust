"""Canonical typed dictionary update phases and unchanged CP-first histories."""
import unittest
import test_native_annotations_assertions as support
from py2fastrust import TranspileOptions,transpile

CASES = {'mapping_replace_append': ('mapping={1:[10],2:[20]}\nrow=[30]\nsource={2:row,3:row}\nprint(mapping.update(source))\nrow.append(7)\nprint(mapping,mapping[2] is source[2],mapping[2] is mapping[3])\n', ('',)), 'empty_mapping_alias_self': ('mapping={1:10,2:20}\nalias=mapping\nprint(mapping.update(alias),mapping)\nprint(mapping.update(),mapping)\n', ('',)), 'keywords_and_mapping': ("mapping={'a':1,'b':2}\nprint(mapping.update({'b':7,'c':8},b=9,d=10))\nprint(mapping)\n", ('',)), 'pair_list': ('mapping={1:10}\nprint(mapping.update([(2,20),(1,11),(3,30)]))\nprint(mapping)\n', ('',)), 'integer_row_lists': ('mapping={1:10}\nrows=[[2,20],[1,11],[3,30]]\nmapping.update(rows)\nprint(mapping)\n', ('',)), 'pair_generator_effects': ("mapping={1:10}\ndef pairs():\n for i in range(2,5):\n  print('yield',i,mapping)\n  yield i,i*10\nmapping.update(pairs())\nprint(mapping)\n", ('',)), 'row_too_long_partial': ("mapping={0:1}\ndef watch(row):\n print('row',row,mapping)\n return row\nmapping.update(map(watch,[(1,2),(3,4,5)]))\n", ('',)), 'row_too_short_partial': ("mapping={0:1}\ndef watch(row):\n print('row',row,mapping)\n return row\nmapping.update(map(watch,[(1,2),(3,)]))\n", ('',)), 'unhashable_pair_partial': ("mapping={0:1}\ndef watch(row):\n print('row',mapping)\n return row\nmapping.update(map(watch,[(1,2),([3],4)]))\n", ('',)), 'owner_argument_order': ("mapping={1:10}\noriginal=mapping\ndef receiver():\n print('receiver')\n return mapping\ndef argument():\n global mapping\n print('argument')\n mapping={8:80}\n return {2:20}\nprint(receiver().update(argument()))\nprint(original,mapping)\n", ('',)), 'arity_all_effects': ("mapping={'a':1}\ndef effect(value):\n print('effect',value,mapping)\n return value\nmapping.update(effect({'b':2}),effect({'c':3}),d=effect(4))\n", ('',)), 'keyword_effects_before_iteration': ("mapping={'a':1}\ndef pairs():\n print('iter',mapping)\n yield 'b',2\ndef value():\n print('keyword',mapping)\n return 9\nmapping.update(pairs(),c=value())\nprint(mapping)\n", ('',)), 'bound_owner_identity': ('mapping={1:10}\nmethod=mapping.update\nalias=method\nfresh=mapping.update\nprint(method is alias,method is fresh,method==fresh)\nmapping={9:90}\nprint(method({2:20}),fresh({3:30}),mapping)\n', ('',)), 'bound_keyword_update': ("mapping={'a':1}\nmethod=mapping.update\nprint(method(b=2,a=3),mapping)\n", ('',)), 'defaultdict_no_missing': ("from collections import defaultdict\ndef factory():\n print('factory')\n return 0\nmapping=defaultdict(factory,{1:10})\nmethod=mapping.update\nprint(method({2:20}),mapping[1],mapping[2])\n", ('',)), 'counter_additive_control': ('from collections import Counter\ncounts=Counter({1:2})\ncounts.update({1:3,2:4})\nprint(counts[1],counts[2])\n', ('',)), 'bool_key_representative': ('class Holder:\n def __init__(self):self.mapping={True:[1]}\nholder=Holder()\nrow=[9]\nholder.mapping.update({1:row})\nprint(holder.mapping,list(holder.mapping)[0] is True,holder.mapping[True] is row)\n', ('',)), 'custom_outer_keys_absent': ("mapping={0:1}\nclass Pairs:\n def __iter__(self):\n  print('outer iter',mapping)\n  return iter(((1,2),(3,4)))\n def __len__(self):\n  print('outer length should not run')\n  return 99\nmapping.update(Pairs())\nprint(mapping)\n", ('',)), 'pair_iterator_failure_partial': ("mapping={0:1}\ndef rows():\n yield 1,2\n print('before error',mapping)\n yield 1//0,3\nmapping.update(rows())\n", ('',)), 'kwargs_only_self_geometry': ('mapping=dict(a=1,b=2,c=3,d=4,e=5)\ncursor=iter(mapping)\nprint(next(cursor))\nmapping.update(mapping,f=6)\nprint(mapping)\nprint(list(cursor))\n', ('',)), 'peer_pair_update_then_compaction': ('mapping = {}\nmapping.update(((1,10), (2,20), (3,30), (4,40), (5,50)))\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[1]\nmapping[6] = 60\nprint(list(cursor))\n', ('',)), 'peer_cleared_values_rebuilt_before_pull': ('mapping = dict(((1,10), (2,20), (3,30)))\ncursor = iter(mapping.values())\nprint(next(cursor))\nmapping.clear()\nmapping.update(((4,40), (5,50), (6,60)))\nprint(list(cursor))\n', ('',)), 'canonical_iterator_rows': ('mapping={9:90}\nfirst=iter((1,2))\nsecond=iter((3,4))\nmapping.update((first,second))\nprint(mapping,next(first,-1),next(second,-1))\n', ('',)), 'actual_dynamic_tuple_rows': ('mapping={9:90}\nrow=tuple(range(2))\nmapping.update((row,))\nprint(mapping,row)\n', ('',)), 'bytes_rows': ("mapping={}\nmapping.update((b'ab',b'cd'))\nprint(mapping)\n", ('',)), 'text_rows': ("mapping={}\nmapping.update(('ab','cd'))\nprint(mapping)\n", ('',)), 'noniterable_outer': ("mapping={1:2}\nprint('before')\nmapping.update(None)\n", ('',)), 'peer_mapping_update_then_reinsert_yielded': ('source = {1:10, 2:20, 3:30, 4:40, 5:50}\nmapping = {}\nmapping.update(source)\ncursor = iter(mapping.values())\nprint(next(cursor))\nold = mapping.pop(1)\nmapping[1] = old + 1\nprint(list(cursor))\n', ('',))}
BOUNDARIES = {'noniterable_pair_notes': ('mapping={1:10}\nmapping.update((3,))\n', 'exception-note'), 'custom_keys_boundary': ('class Source:\n def keys(self):return (1,2,3)\n def __getitem__(self,key):return key*10\n def __iter__(self):return iter(((9,90),))\nmapping={}\nmapping.update(Source())\nprint(mapping)\n', 'keys'), 'custom_row_iterator': ("mapping={0:1}\nclass Row:\n def __init__(self,a,b):self.a=a;self.b=b\n def __iter__(self):\n  print('row iter',mapping)\n  return iter((self.a,self.b))\n def __len__(self):\n  print('row len',mapping)\n  return 2\nmapping.update((Row(1,2),Row(3,4)))\nprint(mapping)\n", 'pair'), 'inner_iterator_exhaust_before_length_error': ("mapping={0:1}\ndef row():\n for i in range(3):\n  print('pull',i,mapping)\n  yield i\nmapping.update((row(),))\n", 'pair')}

class DictUpdateExecutionTests(unittest.TestCase):
    pass

class DictUpdateBoundaryTests(unittest.TestCase):
    def test_remaining_protocols_are_named_and_positioned(self):
        for name,(source,reason)in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code=='E006'and d.line>0 and reason in d.message for d in result.diagnostics),result.diagnostics)

    def test_immediate_update_has_no_allocated_mapping_method_wrapper(self):
        source=CASES['bool_key_representative'][0]
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('struct NativeMappingMethod_',result.rust_source)


def _case(values):
    def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*values)
    return test

for _name,_values in CASES.items():
    setattr(DictUpdateExecutionTests,'test_'+_name,_case(_values))

if __name__=='__main__':unittest.main()
