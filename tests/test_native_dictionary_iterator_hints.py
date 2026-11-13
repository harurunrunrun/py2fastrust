"""Typed dictionary cursors retain CP entry positions and remaining budgets."""
import unittest
from unittest.mock import patch
import test_native_annotations_assertions as support
from py2fastrust import TranspileOptions,transpile
import test_native_iterator_hints as old_hints

CASES = {'partial_keys_alias': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping)\nalias=stream\nprint(next(alias))\nvalues=[99]\nvalues.extend(stream)\nprint(values,next(alias,-1))\n', ('',)), 'views_live_values': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping.values())\nprint(next(stream))\nmapping[2]=27\nvalues=[]\nvalues.extend(stream)\nprint(values)\n', ('',)), 'views_items_alias': ('mapping={1:10,2:20,3:30}\nview=mapping.items()\nstream=iter(view)\nprint(next(stream))\nmapping={9:90}\nvalues=[]\nvalues.extend(stream)\nprint(values,list(view))\n', ('',)), 'growth_before_extend': ('mapping={1:10,2:20}\nstream=iter(mapping)\nprint(next(stream))\nmapping[3]=30\nvalues=[99]\nvalues.extend(stream)\n', ('',)), 'shrink_before_extend': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping.keys())\nprint(next(stream))\ndel mapping[3]\nvalues=[]\nvalues.extend(stream)\n', ('',)), 'replace_unread_same_size': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping)\nprint(next(stream))\ndel mapping[2]\nmapping[4]=40\nvalues=[]\nvalues.extend(stream)\nprint(values)\n', ('',)), 'replace_yielded_same_size': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping)\nprint(next(stream))\ndel mapping[1]\nmapping[4]=40\nvalues=[]\ndef observe(key):\n print(key,values)\n return key\nvalues.extend(map(observe,stream))\n', ('',)), 'clear_rebuild_same_size': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping)\nprint(next(stream))\nmapping.clear()\nmapping[4]=40\nmapping[5]=50\nmapping[6]=60\nvalues=[]\nvalues.extend(stream)\nprint(values)\n', ('',)), 'resize_compaction_same_size': ('mapping={1:10,2:20,3:30,4:40,5:50}\nstream=iter(mapping)\nprint(next(stream))\ndel mapping[1]\nmapping[6]=60\nvalues=[]\nvalues.extend(stream)\nprint(values)\n', ('',)), 'last_yield_before_growth': ('mapping={1:10}\nstream=iter(mapping)\nprint(next(stream))\nmapping[2]=20\nvalues=[]\nvalues.extend(stream)\n', ('',)), 'exhausted_after_growth': ('mapping={1:10}\nstream=iter(mapping)\nprint(list(stream))\nmapping[2]=20\nvalues=[99]\nvalues.extend(stream)\nprint(values,next(stream,-1))\n', ('',)), 'keys_values_items_separate': ("mapping={'a':2,'b':4,'c':6}\nkeys=iter(mapping.keys())\nvalues=iter(mapping.values())\nitems=iter(mapping.items())\nprint(next(keys),next(values),next(items))\na=[]\nb=[]\nc=[]\na.extend(keys)\nb.extend(values)\nc.extend(items)\nprint(a,b,c)\n", ('',)), 'peer_copied_unread_entry_replaced': ("source = {10:'a', 20:'b', 30:'c', 40:'d'}\nmapping = source.copy()\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[20]\nmapping[50] = 'e'\nprint(list(cursor))\n", ('',)), 'peer_temporary_size_change_restored_before_pull': ('mapping = {1:10, 2:20, 3:30}\ncursor = iter(mapping.items())\nprint(next(cursor))\nmapping[99] = 990\ndel mapping[2]\nprint(list(cursor))\n', ('',)), 'peer_live_values_and_shared_rows': ('mapping = {1:[1], 2:[2], 3:[3]}\ncursor = iter(mapping.values())\nprint(next(cursor))\nmapping[2].append(20)\nmapping[3] = [30]\nprint(list(cursor))\n', ('',)), 'peer_dense_copy_growth': ('source = {0:0, 1:10, 2:20, 3:30, 4:40}\ndel source[0]\nmapping = source.copy()\ncursor = iter(mapping.items())\nprint(next(cursor))\ndel mapping[1]\nmapping[9] = 90\nprint(list(cursor))\n', ('',))}

GUARD_CASES = {'root_source_hint_mutation': ('mapping={1:10,2:20,3:30}\nstream=iter(mapping)\nprint(next(stream))\nclass Source:\n def __iter__(self):return stream\n def __len__(self):\n  del mapping[2]\n  mapping[4]=40\n  return 2\nvalues=[]\nvalues.extend(Source())\nprint(values)\n', ('',)), 'root_callback_global_cursor': ('mapping = {1:10, 2:20, 3:30}\nstream = iter(mapping)\nprint(next(stream))\ndef pull(ignored):\n    return next(stream)\nclass Source:\n    def __iter__(self):\n        return map(pull, range(2))\n    def __len__(self):\n        del mapping[2]\n        mapping[4] = 40\n        return 2\nvalues = []\nvalues.extend(Source())\nprint(values)\n', ('',)), 'repeat_dictionary_payload': ('from itertools import repeat\npayload={1:2}\nvalues=[]\nvalues.extend(repeat(payload,2))\npayload[1]=9\nprint(values,values[0] is values[1])\n', ('',))}

FLAVOR_CASES = {'clean_oversized_constructor': ('source = {0: 10, 0: 11, 1: 12, 2: 13, 3: 14, 4: 15}\nmapping = dict(source)\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[0]\nmapping[9] = 19\nprint(list(cursor))\n', ('',)), 'defaultdict_sparse_copy': ('from collections import defaultdict\nsource = defaultdict(int, {0: 10, 1: 11, 2: 12, 3: 13, 4: 14})\ndel source[0]\nmapping = source.copy()\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[1]\nmapping[9] = 19\nprint(list(cursor))\n', ('',)), 'defaultdict_oversized_mapping_origin': ('from collections import defaultdict\nsource = {0: 10, 0: 11, 1: 12, 2: 13, 3: 14, 4: 15}\nmapping = defaultdict(int, source)\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[0]\nmapping[9] = 19\nprint(list(cursor))\n', ('',)), 'defaultdict_keyword_origin': ("from collections import defaultdict\nmapping = defaultdict(int, a=1, b=2, c=3, d=4, e=5, f=6)\ndel mapping['a']\ncursor = iter(mapping.values())\nprint(next(cursor))\ndel mapping['b']\nmapping['g'] = 7\nprint(list(cursor))\n", ('',)), 'counter_sparse_copy': ('from collections import Counter\nsource = Counter({0: 10, 1: 11, 2: 12, 3: 13, 4: 14})\ndel source[0]\nmapping = source.copy()\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[1]\nmapping[9] = 19\nprint(list(cursor))\n', ('',)), 'counter_oversized_mapping_origin': ('from collections import Counter\nsource = {0: 10, 0: 11, 1: 12, 2: 13, 3: 14, 4: 15}\nmapping = Counter(source)\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping[0]\nmapping[9] = 19\nprint(list(cursor))\n', ('',)), 'keyword_merge_before_copy': ("source = dict(a=10, b=11, c=12, d=13, e=14)\nsource.popitem()\nmapping = dict(source, e=14)\ncursor = iter(mapping)\nprint(next(cursor))\ndel mapping['a']\nmapping['z'] = 19\nprint(list(cursor))\n", ('',))}

class DictionaryCursorExecutionTests(unittest.TestCase):
    pass

class DictionaryCursorBoundaryTests(unittest.TestCase):
    def test_original_dictionary_hint_boundary_now_executes_unchanged(self):
        support.AnnotationAndAssertionExecutionTests.compare(self,old_hints.DICT_BOUNDARY,('',))


    def test_reverse_dictionary_requires_its_actual_reverse_provider(self):
        source='mapping={1:10,2:20}\nvalues=[]\nvalues.extend(reversed(mapping))\nprint(values)\n'
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==3 and 'reverse' in d.message for d in result.diagnostics),result.diagnostics)

    def test_original_defaultdict_origin_now_executes_unchanged(self):
        source='from collections import defaultdict\nmapping=defaultdict(int,{1:10,2:20,3:30})\nstream=iter(mapping)\nvalues=[]\nvalues.extend(stream)\nprint(values)\n'
        support.AnnotationAndAssertionExecutionTests.compare(self,source,('',))

    def test_uncursored_defaultdict_keeps_owner_trait_without_positions(self):
        source='from collections import defaultdict\nvalues=defaultdict(list)\nvalues[1].append(7)\nprint(values[1])\n'
        for optimize in (False,True):
            with patch.object(support,'TranspileOptions',side_effect=lambda **options:TranspileOptions(optimize=optimize,**options)):
                support.AnnotationAndAssertionExecutionTests.compare(self,source,('',))

    def test_keyword_copy_popitem_preserves_original_source_and_cursor_error(self):
        source=FLAVOR_CASES['keyword_merge_before_copy'][0]
        support.AnnotationAndAssertionExecutionTests.compare(self,source,('',))

    def test_custom_keys_constructor_origin_stays_explicit(self):
        source='class Source:\n def keys(self):return (1,2,3)\n def __getitem__(self,key):return key*10\n def __iter__(self):return iter(((9,90),))\nmapping=dict(Source())\nstream=iter(mapping)\nvalues=[]\nvalues.extend(stream)\nprint(values)\n'
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and 'origin' in d.message for d in result.diagnostics),result.diagnostics)

    def test_chunked_literal_position_origin_is_specific(self):
        source='mapping={'+','.join(str(i)+':'+str(i)for i in range(40))+'}\nstream=iter(mapping)\nvalues=[]\nvalues.extend(stream)\n'
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==1 and 'presizing' in d.message for d in result.diagnostics),result.diagnostics)

def _case(values):
    def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*values)
    return test
for _name,_values in CASES.items():
    setattr(DictionaryCursorExecutionTests,'test_'+_name,_case(_values))
for _name,_values in GUARD_CASES.items():
    setattr(DictionaryCursorExecutionTests,'test_'+_name,_case(_values))

for _name,_values in FLAVOR_CASES.items():
    if _name=='keyword_merge_before_copy':continue
    setattr(DictionaryCursorExecutionTests,'test_'+_name,_case(_values))

if __name__=='__main__':unittest.main()
