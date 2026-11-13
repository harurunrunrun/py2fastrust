"""Actual canonical providers publish absent or checked iterator hint protocols."""
from functools import partial
import unittest
from unittest.mock import patch

import test_native_annotations_assertions as support
from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_iterator_hints import ABSENT

CASES = {'accumulate_alias': ('from itertools import accumulate as running\nvalues=[0]\nvalues.extend(running([3,1,4]))\nprint(values)\n', ('',)), 'accumulate_callback_order': ("import itertools\nvalues=[10]\ndef fold(a,b):\n print('fold',a,b,values)\n return a+b\nstream=itertools.accumulate((2,5,7),fold,initial=1)\nprint(next(stream))\nvalues.extend(stream)\nprint(values)\n", ('',)), 'no_inner_hint_through_accumulate': ("import itertools\nclass Items:\n def __iter__(self):\n  print('iter')\n  return iter((2,3))\n def __len__(self):\n  print('unvisited length')\n  return -1\nvalues=[0]\nvalues.extend(itertools.accumulate(Items()))\nprint(values)\n", ('',)), 'chain_islice_pairwise': ('from itertools import chain,islice,pairwise\nvalues=[9]\nvalues.extend(islice(chain((2,3),(4,5)),1,4,2))\nprint(values)\npairs=[]\npairs.extend(pairwise((2,4,8)))\nprint(pairs)\n', ('',)), 'product_and_choices': ('from itertools import product,combinations,permutations,combinations_with_replacement\nvalues=[]\nvalues.extend(product((1,2),repeat=2))\nvalues.extend(combinations((3,4,5),2))\nvalues.extend(permutations((6,7),2))\nvalues.extend(combinations_with_replacement((8,9),2))\nprint(values)\n', ('',)), 'repeat_partial_alias': ('from itertools import repeat\nrow=[1]\nstream=repeat(row,4)\nprint(next(stream))\nvalues=[]\nvalues.extend(stream)\nrow.append(7)\nprint(values,list(stream))\n', ('',)), 'repeat_huge_hint_error': ('from itertools import repeat\nvalues=[]\nvalues.extend(repeat(7,9223372036854775807))\n', ('',)), 'reverse_range_partial': ('stream=reversed(range(-7,13,3))\nprint(next(stream))\nvalues=[99]\nvalues.extend(stream)\nprint(values,list(stream))\n', ('',)), 'reverse_list_live_shrink': ('values=[1,2,3,4]\nstream=reversed(values)\nprint(next(stream))\nvalues.pop()\nvalues.pop()\nresult=[9]\nresult.extend(stream)\nprint(result)\n', ('',)), 'reverse_tuple_and_bytes': ("result=[]\nresult.extend(reversed((2,4,6)))\nresult.extend(reversed(b'Az'))\nprint(result)\n", ('',)), 'forward_list_live': ('values=[1,2,3]\nstream=iter(values)\nprint(next(stream))\nvalues.append(4)\nresult=[]\nresult.extend(stream)\nprint(result)\n', ('',)), 'deque_forward_reverse': ('from collections import deque\nvalues=deque((1,2,3))\nstream=iter(values)\nprint(next(stream))\nresult=[]\nresult.extend(stream)\nreverse=reversed(values)\nprint(next(reverse))\nresult.extend(reverse)\nprint(result)\n', ('',)), 'array_forward_reverse': ("from array import array\nvalues=array('q',[2,4,6])\nstream=iter(values)\nprint(next(stream))\nresult=[]\nresult.extend(stream)\nresult.extend(reversed(values))\nprint(result)\n", ('',)), 'bytearray_forward_reverse': ("values=bytearray(b'abc')\nstream=iter(values)\nprint(next(stream))\nvalues.append(100)\nresult=[]\nresult.extend(stream)\nresult.extend(reversed(values))\nprint(result)\n", ('',)), 'reverse_range_hint_overflow': ('values=[]\nvalues.extend(reversed(range(-9223372036854775807,9223372036854775807)))\n', ('',))}

UNICODE = "values=[]\nstream=reversed('Aβ🙂Z')\nprint(next(stream))\nvalues.extend(stream)\nprint(values)\n"

DICT_BOUNDARY = 'values={1:2,3:4}\nstream=iter(values)\nprint(next(stream))\nresult=[]\nresult.extend(stream)\nprint(result)\n'

DICT_MUTATION_THROUGH_SOURCE = '''mapping={1:10,2:20,3:30}
stream=iter(mapping)
print(next(stream))
class Source:
 def __iter__(self):return stream
 def __len__(self):
  del mapping[2]
  mapping[4]=40
  return 2
values=[]
values.extend(Source())
print(values)
'''

class IteratorHintExecutionTests(unittest.TestCase):
    def test_dictionary_lookup_callback_does_not_create_a_cursor(self):
        source='weights={1:7,2:11}\nvalues=[]\nvalues.extend(map(lambda key:weights[key],(2,1)))\nprint(values)\n'
        support.AnnotationAndAssertionExecutionTests.compare(self,source,('',))

    def test_unicode_reverse_cursor_counts_remaining_codepoints(self):
        with patch.object(support,'TranspileOptions',partial(TranspileOptions,string_mode='unicode')):
            support.AnnotationAndAssertionExecutionTests.compare(self,UNICODE,('',))

class IteratorHintMetadataTests(unittest.TestCase):
    def test_callback_global_cursor_is_not_an_owned_field_proof(self):
        source='''mapping = {1:10, 2:20, 3:30}
stream = iter(mapping)
print(next(stream))
def pull(ignored):
    return next(stream)
class Source:
    def __iter__(self):
        return map(pull, range(2))
    def __len__(self):
        del mapping[2]
        mapping[4] = 40
        return 2
values = []
values.extend(Source())
print(values)
'''
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==14
                                and 'mutation-safe dictionary iterator position' in d.message
                                for d in result.diagnostics),result.diagnostics)

    def test_source_wrapper_does_not_hide_unsafe_dictionary_cursor(self):
        for integer in ('i64','i128','bigint'):
            result=transpile(DICT_MUTATION_THROUGH_SOURCE,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==11
                                and 'mutation-safe dictionary iterator position' in d.message
                                for d in result.diagnostics),result.diagnostics)

    def test_canonical_map_dependency_does_not_hide_dictionary_cursor(self):
        source='values=[]\nvalues.extend(map(abs,iter({-3:0,2:0})))\nprint(values)\n'
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==2
                                and 'mutation-safe dictionary iterator position' in d.message
                                for d in result.diagnostics),result.diagnostics)

    def test_dictionary_remaining_position_is_not_guessed(self):
        for integer in ('i64','i128','bigint'):
            result=transpile(DICT_BOUNDARY,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==5 and 'remaining-position' in d.message for d in result.diagnostics),result.diagnostics)

    def test_unknown_record_never_inherits_absence_from_operation_name(self):
        from types import SimpleNamespace
        from py2fastrust.native_iterator_hints import emit
        from py2fastrust.native_classes import ClassUnsupported
        from py2fastrust.native import _Expression
        import ast
        node=ast.parse('values.extend(stream)').body[0].value
        for spelling in ('map','itertools_accumulate','source_generator','unknown'):
            record=SimpleNamespace(operation=spelling,hint_protocol=None)
            with self.assertRaises(ClassUnsupported):
                emit(SimpleNamespace(),node,_Expression('cursor',SimpleNamespace(record=record)))

    def test_absence_is_a_provider_certificate_not_a_pull_callback_flag(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_classes import Model
        source='def fold(a,b):return a+b\nvalues=[0]\nvalues.extend(map(abs,(-1,2)))\n'
        unit=build_program(source,'hint.py').main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        records=[r for r in model.iterators.records if r.operation=='map']
        self.assertTrue(records)
        self.assertTrue(all(r.hint_protocol is ABSENT for r in records))

def _case(values):
    def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*values)
    return test
for _name,_values in CASES.items():
    setattr(IteratorHintExecutionTests,'test_'+_name,_case(_values))
if __name__=='__main__':unittest.main()
