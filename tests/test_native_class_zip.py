"""Typed zip objects use shared concrete source state and ordered lazy pulls."""
import ast
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Model
import test_native_class_iterators as iterator_tests

CASES={'stored_zip_cursor': 'left=iter([1,2,3])\n'
                      'stream=zip(left,[10,20,30])\n'
                      'alias=stream\n'
                      'print(iter(alias) is stream)\n'
                      'print(next(alias),next(left),list(stream),list(alias))\n',
 'unicode_zip_text_bytes': "stream=zip('猫😀é',b'abc')\nprint(next(stream),list(stream))\n",
 'zip_callback_mutates_other_source': 'left=[1,2]\n'
                                      'right=[10]\n'
                                      'def visit(value):\n'
                                      ' right.append(value*10)\n'
                                      ' return value\n'
                                      'stream=zip(map(visit,left),right)\n'
                                      'print(list(stream),right)\n',
 'zip_class_fields_and_alias': 'class Pairing:\n'
                               ' def __init__(self):self.stream=zip([1,2],[3,4])\n'
                               ' def first(self):return next(self.stream)\n'
                               'item=Pairing()\n'
                               'saved=item.stream\n'
                               'print(item.first(),list(saved),list(item.stream))\n',
 'zip_deferred_callback_error_frames': 'def divide(value):\n'
                                       " print('call',value)\n"
                                       ' return 10//value\n'
                                       'stream=zip(map(divide,[1,0]),[3,4])\n'
                                       'print(next(stream))\n'
                                       'print(next(stream))\n',
 'zip_empty_later_keeps_source_effects': 'def visit(value):\n'
                                         " print('visit',value)\n"
                                         ' return value\n'
                                         'source=map(visit,[1,2,3])\n'
                                         'stream=zip(source,())\n'
                                         'print(list(stream),list(stream),next(source))\n',
 'zip_for_unpack_live_state': 'stream=zip([1,2,3],[4,5,6])\n'
                              'for a,b in stream:\n'
                              ' print(a,b)\n'
                              ' if a==1:break\n'
                              'print(list(stream))\n',
 'zip_invalid_source_argument_order': 'def mark(label,value):\n'
                                      ' print(label)\n'
                                      ' return value\n'
                                      "stream=zip(mark('left',[]),mark('right',3))\n"
                                      "print('unreachable')\n",
 'zip_repeated_same_source': 'source=iter([1,2,3,4,5])\n'
                             'stream=zip(source,source)\n'
                             "print(next(stream),list(stream),next(source,'done'))\n",
 'zip_saved_builtin_binding': 'combine=zip\n'
                              'zip=7\n'
                              'stream=combine([1,2],[3,4])\n'
                              'print(list(stream),zip)\n',
 'zip_shared_mutable_outputs': 'rows=[[1],[2]]\n'
                               'stream=zip(rows,[3,4])\n'
                               'first=next(stream)\n'
                               'first[0].append(9)\n'
                               'later=list(stream)\n'
                               'later[0][0].append(8)\n'
                               'print(rows,first,later)\n',
 'zip_shortest_partial_consumption': 'left=iter([1,2,3,4])\n'
                                     'right=iter([10])\n'
                                     'stream=zip(left,right)\n'
                                     'print(list(stream),next(left))\n'
                                     'print(list(stream),next(left,99))\n',
 'zip_single_source': 'stream=zip([1,2,3])\nprint(next(stream),list(stream))\n',
 'zip_strict_equal': "stream=zip([1,2],('a','b'),strict=True)\nprint(list(stream))\n",
 'zip_strict_longer': 'stream=zip([1],[3,4],strict=True)\n'
                      'print(next(stream))\n'
                      'print(next(stream))\n',
 'zip_strict_shorter': 'stream=zip([1,2],[3],strict=True)\n'
                       'print(next(stream))\n'
                       'print(next(stream))\n',
 'zip_strict_three_longer': 'stream=zip([],[],[3],strict=True)\nprint(next(stream))\n',
 'zip_strict_three_shorter': 'stream=zip([1],[2],[],strict=True)\nprint(next(stream))\n',
 'zip_three_mixed_sources': "stream=zip([1,2,3],('a','b'),range(10,15))\n"
                            'print(next(stream),list(stream),list(stream))\n',
 'zip_unknown_keyword_after_effects': 'def mark(value):\n'
                                      ' print(value)\n'
                                      ' return value\n'
                                      'stream=zip(mark([1]),bad=mark(7))\n',
 'zip_zero_sources': 'stream=zip()\n'
                     "print(list(stream),next(stream,'done'),list(stream))\n"
                     'print(list(zip(strict=True)))\n'}

CASES.update({'zip_builtin_type_error': 'saved=zip\nprint(abs(saved))\n',
 'zip_ids_and_aliases': 'stream=zip([1],[2])\n'
                        'alias=stream\n'
                        'other=zip([1],[2])\n'
                        'print(stream is alias,stream is '
                        'other,id(stream)==id(alias),id(stream)==id(other))\n',
 'zip_iterator_type_error': 'stream=zip([1],[2])\nprint(len(stream))\n',
 'zip_strict_captures_truth_once': 'flag=[]\n'
                                   'stream=zip([1],[2,3],strict=flag)\n'
                                   'flag.append(True)\n'
                                   'print(list(stream),flag)\n',
 'zip_strict_early_probe_order': 'def mark(value):\n'
                                 ' print(value)\n'
                                 ' return value\n'
                                 'left=map(mark,[])\n'
                                 'right=map(mark,[2])\n'
                                 'last=map(mark,[3])\n'
                                 'stream=zip(left,right,last,strict=True)\n'
                                 'print(next(stream))\n'})

CASES.update({'immediate_key_set': 'print(len(set(zip([1,2,1],[3,4,3]))))\n',
 'immediate_sorted': 'print(sorted(zip([3,1],[2,4])))\n',
 'immediate_unpack': 'first,second=zip([1,2],[3,4])\nprint(first,second)\n'})

CASES.update({'zip_builtin_namespace_capture': 'import builtins\n'
                                  'saved=builtins.zip\n'
                                  'builtins.zip=map\n'
                                  'stream=saved([1,2],[3,4])\n'
                                  'print(list(stream))\n',
 'zip_callback_returns_stream': 'def pair(value):return zip([value],[value+1])\n'
                                'streams=map(pair,[1,2])\n'
                                'for stream in streams:\n'
                                ' print(list(stream))\n',
 'zip_loop_observes_deferred_field_effect': 'class Box:\n'
                                            ' def __init__(self):self.value=0\n'
                                            'box=Box()\n'
                                            'def change(value):\n'
                                            ' box.value+=value\n'
                                            ' return value\n'
                                            'stream=zip(map(change,[1,2,3]),[4,5,6])\n'
                                            'for pair in stream:\n'
                                            ' print(box.value,pair)\n',
 'zip_nested_sources': 'inner=zip([1,2],[3,4])\nouter=zip(inner,range(3))\nprint(list(outer))\n',
 'zip_passed_to_function': 'def consume(stream):\n'
                           ' print(next(stream))\n'
                           ' return list(stream)\n'
                           'stream=zip([1,2],[3,4])\n'
                           'print(consume(stream),list(stream))\n',
 'zip_returned_from_function': 'def pair(values):return zip(values,[10,20,30])\n'
                               'stream=pair([1,2])\n'
                               'print(next(stream),list(stream))\n'})

CASES.update({'both_map_and_zip_branches': 'def choose(flag):\n'
                              ' if flag:return zip([1,2],[3,4])\n'
                              ' return map(lambda value:(value,value+2),[1,2])\n'
                              'print(list(choose(True)),list(choose(False)))\n',
 'iterator_and_eager_source': 'def choose(flag):\n'
                              ' if flag:return zip([1],[2])\n'
                              ' return [(3,4)]\n'
                              'print(list(choose(True)),list(choose(False)))\n',
 'map_and_filter_both_numeric': 'def choose(flag):\n'
                                ' if flag:return map(lambda value:value+1,[1,2])\n'
                                ' return filter(None,[0,3])\n'
                                'print(list(choose(True)),sum(choose(False)),sum(choose(True)),list(choose(False)))\n',
 'saved_map_overwritten_with_zip': 'import builtins\n'
                                   'saved=builtins.map\n'
                                   'builtins.map=zip\n'
                                   'print(list(saved(int,["1","2"])))\n'})


class ZipExecutionTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_additional_identity_truth_and_error_protocols(self):
        for name in ('zip_iterator_type_error','zip_builtin_type_error','zip_strict_captures_truth_once','zip_strict_early_probe_order','zip_ids_and_aliases'):
            with self.subTest(name=name):self.check(name)

    def test_immediate_consumers_keep_existing_native_paths(self):
        for name in ('immediate_sorted','immediate_key_set','immediate_unpack'):
            with self.subTest(name=name):self.check(name)

    def test_contexts_and_finite_callable_alternatives(self):
        for name in ('zip_returned_from_function','zip_passed_to_function','zip_callback_returns_stream','zip_nested_sources','zip_builtin_namespace_capture','zip_loop_observes_deferred_field_effect'):
            with self.subTest(name=name):self.check(name)

    def test_finite_iterator_alternatives_demand_and_capture_once(self):
        for name in ('both_map_and_zip_branches','map_and_filter_both_numeric','iterator_and_eager_source','saved_map_overwritten_with_zip'):
            with self.subTest(name=name):self.check(name)

    def test_shared_cursor_and_builtin_capture(self):
        for name in ('stored_zip_cursor','zip_saved_builtin_binding','zip_repeated_same_source','zip_class_fields_and_alias'):
            with self.subTest(name=name):self.check(name)

    def test_empty_single_and_multiple_sources(self):
        for name in ('zip_zero_sources','zip_single_source','zip_three_mixed_sources','zip_shortest_partial_consumption','zip_empty_later_keeps_source_effects'):
            with self.subTest(name=name):self.check(name)

    def test_strict_mismatch_protocol(self):
        for name in ('zip_strict_equal','zip_strict_shorter','zip_strict_longer','zip_strict_three_shorter','zip_strict_three_longer'):
            with self.subTest(name=name):self.check(name)

    def test_order_mutation_and_mixed_payloads(self):
        for name in ('zip_callback_mutates_other_source','zip_shared_mutable_outputs','unicode_zip_text_bytes','zip_for_unpack_live_state'):
            with self.subTest(name=name):self.check(name)

    def test_argument_and_deferred_errors(self):
        for name in ('zip_invalid_source_argument_order','zip_unknown_keyword_after_effects','zip_deferred_callback_error_frames'):
            with self.subTest(name=name):self.check(name)


class ZipMetadataTests(unittest.TestCase):
    def test_original_syntax_and_official_tables_are_retained(self):
        unit=parse_source(CASES['stored_zip_cursor'],'zip.py')
        before=ast.dump(unit.tree,include_attributes=True)
        original=unit.table
        model=Model(unit.tree,unit.filename,'i64',(),unit=unit).run()
        self.assertTrue(any(record.operation=='zip'for record in model.iterators.records))
        originals={id(node)for node in ast.walk(unit.tree)}
        self.assertTrue(all(id(record.node)in originals for record in model.iterators.records))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertIs(unit.table,original)

    def test_actual_reference_cycles_need_the_unfinished_collector(self):
        sources=(
            'class Holder:pass\nholder=Holder()\nitems=[holder]\nholder.stream=zip(items,[1])\nprint(next(holder.stream))\n',
            'items=[]\nstream=zip(items)\nitems.append(stream)\nprint(next(stream))\n',
        )
        for source in sources:
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename='cycle.py'))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')


if __name__=='__main__':unittest.main()
