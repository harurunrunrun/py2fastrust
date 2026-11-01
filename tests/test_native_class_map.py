"""Compiled map objects preserve callback capture and multi-source pull order."""
import ast
import unittest
from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Model
import test_native_class_iterators as iterator_tests

CASES={'empty_later_source_still_advances_earlier': 'left=iter([1,2,3])\n'
                                              'stream=map(lambda a,b:a+b,left,())\n'
                                              'print(list(stream),next(left),list(stream),next(left,99))\n',
 'map_argument_order_and_invalid_source': 'def mark(label,value):\n'
                                          ' print(label)\n'
                                          ' return value\n'
                                          "stream=map(mark('callback',None),mark('first',[]),mark('second',3))\n"
                                          "print('unreachable')\n",
 'map_builtin_int_bytes_and_text': "stream=map(int,[b'12',b'-7'])\n"
                                   'print(next(stream),sum(stream))\n'
                                   "values=map(int,('15','-2'))\n"
                                   'print(list(values))\n',
 'map_callback_mutates_source': 'items=[1,2]\n'
                                'def update(value):\n'
                                ' if value<4:items.append(value+2)\n'
                                ' return value*10\n'
                                'stream=map(update,items)\n'
                                'print(list(stream),items)\n',
 'map_callback_type_error_deferred': 'def callback(a,b):return a+b\n'
                                     'stream=map(callback,[1])\n'
                                     "print('created')\n"
                                     'print(next(stream))\n',
 'map_exception_frames': 'def divide(value):\n'
                         " print('call',value)\n"
                         ' return 10//value\n'
                         'print(sum(map(divide,[1,0])))\n',
 'map_minimum_arity': "alias=map\nprint('before')\nalias(int)\n",
 'map_mixed_result_binding': 'def mix(value):return [value] if value else None\n'
                             'stream=map(mix,[0,1,2])\n'
                             'print(next(stream),list(stream))\n',
 'map_noncallable_lazy_error': "stream=map(None,[1])\nprint('created')\nprint(next(stream))\n",
 'map_output_shared_objects': 'def wrap(value):return [value]\n'
                              'stream=map(wrap,[1,2])\n'
                              'first=next(stream)\n'
                              'values=list(stream)\n'
                              'first.append(9)\n'
                              'values[0].append(8)\n'
                              'print(first,values)\n',
 'map_reentrant_state': 'def callback(value):\n'
                        " if value==1:print('inner',next(stream))\n"
                        ' return value*10\n'
                        'stream=map(callback,[1,2,3])\n'
                        'print(list(stream))\n',
 'map_saved_callback': 'def yes(value):return value+10\n'
                       'def no(value):return value-10\n'
                       'callback=yes\n'
                       'stream=map(callback,[1,2])\n'
                       'callback=no\n'
                       'print(list(stream))\n',
 'map_source_iterator_identity': 'source=iter([1,2,3])\n'
                                 'stream=map(lambda x:x+1,source)\n'
                                 'print(next(source),next(stream),next(source),list(stream))\n',
 'map_strict_equal_and_false': 'def add(a,b):return a+b\n'
                               'print(list(map(add,[1,2],[3,4],strict=True)))\n'
                               'print(list(map(add,[1],[3,4],strict=False)))\n',
 'map_strict_longer': 'def pair(a,b):return a+b\n'
                      'stream=map(pair,[1],[10,20],strict=True)\n'
                      'print(next(stream))\n'
                      'print(next(stream))\n',
 'map_strict_shorter': 'def pair(a,b):return a+b\n'
                       'stream=map(pair,[1,2],[10],strict=True)\n'
                       'print(next(stream))\n'
                       'print(next(stream))\n',
 'map_uninhabited_shortest_callback_arity': 'def bad(left,right):return left+right\n'
                                            'stream=map(bad,())\n'
                                            "print(list(stream),next(stream,'done'))\n",
 'map_unknown_keyword_after_argument_effects': 'def mark(value):\n'
                                               ' print(value)\n'
                                               ' return value\n'
                                               'stream=map(mark,[1],bad=mark(True))\n',
 'stored_map_builtin_alias': 'transform=map\n'
                             'map=7\n'
                             'stream=transform(lambda value:value*3,[1,2])\n'
                             'print(list(stream))\n',
 'stored_map_resume_and_alias': 'def twice(value):\n'
                                " print('map',value)\n"
                                ' return value*2\n'
                                'stream=map(twice,[1,2,3])\n'
                                'alias=stream\n'
                                "print('created',iter(stream) is stream)\n"
                                'print(next(alias),list(stream),list(alias))\n',
 'strict_empty_and_callback_cannot_run': 'def bad(a,b):return 1//0\n'
                                         'stream=map(bad,(),(),strict=True)\n'
                                         'print(list(stream))\n',
 'three_sources': 'def combine(a,b,c):return a*100+b*10+c\n'
                  'stream=map(combine,[1,2,3],(4,5),range(6,10))\n'
                  'print(next(stream),sum(stream),list(stream))\n',
 'three_strict_longer': 'stream=map(lambda a,b,c:a+b+c,[],[],[3],strict=True)\n'
                        'print(list(stream))\n',
 'three_strict_shorter': 'stream=map(lambda a,b,c:a+b+c,[1],[2],[],strict=True)\n'
                         'print(list(stream))\n',
 'two_sources_stop_shortest_consumption': 'def combine(left,right):\n'
                                          " print('combine',left,right)\n"
                                          ' return left+right\n'
                                          'left=iter([1,2,3,4])\n'
                                          'right=iter([10])\n'
                                          'stream=map(combine,left,right)\n'
                                          'print(list(stream),next(left))\n'
                                          'print(list(stream),next(left,99))\n',
 'unicode_cursor_map': "def decorate(value):return '['+value+']'\n"
                       "stream=map(decorate,'猫😀é')\n"
                       'print(next(stream),list(stream),list(stream))\n'}

CASES.update({'empty_input_and_callback_alias': 'def identity(value):return value\n'
                                   'source=[]\n'
                                   'alias=source\n'
                                   'callback=identity\n'
                                   'stream=map(callback,alias)\n'
                                   'source=None\n'
                                   'alias.append(5)\n'
                                   'callback=7\n'
                                   'print(list(stream),source,alias)\n',
 'empty_list_none_alias_rebinding': 'def identity(value):return value\n'
                                    'items=[]\n'
                                    'alias=items\n'
                                    'bound=identity(None)\n'
                                    'print(bound)\n'
                                    'bound=identity(alias)\n'
                                    'print(bound is items)\n'
                                    'bound=7\n'
                                    'alias.append(4)\n'
                                    'print(items,bound)\n',
 'empty_result_callback_and_rebinding': 'def collect(callback,source):return '
                                        'list(map(callback,source))\n'
                                        'def keep(value):return [] if value else None\n'
                                        'items=collect(keep,[0,1])\n'
                                        'saved=items\n'
                                        'items=None\n'
                                        'print(saved,items)\n',
 'empty_source_join_maintains_earlier_reference': 'def identity(value):return value\n'
                                                  'saved=[]\n'
                                                  'first=identity(None)\n'
                                                  'second=identity(saved)\n'
                                                  'stream=map(bool,[first,second])\n'
                                                  'print(list(stream))\n'
                                                  'saved.append(3)\n'
                                                  'print(second,saved)\n'})


class MapExecutionTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_stored_cursors_and_lifetimes(self):
        for name in ('stored_map_resume_and_alias','map_saved_callback','map_source_iterator_identity','stored_map_builtin_alias'):
            with self.subTest(name=name):self.check(name)

    def test_multiple_sources_and_strictness(self):
        for name in ('two_sources_stop_shortest_consumption','three_sources','map_strict_shorter','map_strict_longer','map_strict_equal_and_false','empty_later_source_still_advances_earlier','three_strict_shorter','three_strict_longer','strict_empty_and_callback_cannot_run'):
            with self.subTest(name=name):self.check(name)

    def test_callback_results_mutation_and_reentry(self):
        for name in ('map_callback_mutates_source','map_output_shared_objects','map_mixed_result_binding','map_reentrant_state','map_builtin_int_bytes_and_text','unicode_cursor_map'):
            with self.subTest(name=name):self.check(name)

    def test_lazy_errors_and_argument_order(self):
        for name in ('map_uninhabited_shortest_callback_arity','map_noncallable_lazy_error','map_exception_frames','map_argument_order_and_invalid_source','map_callback_type_error_deferred','map_unknown_keyword_after_argument_effects','map_minimum_arity'):
            with self.subTest(name=name):self.check(name)

    def test_empty_partial_storage_aliases_and_rebinding(self):
        for name in ('empty_list_none_alias_rebinding','empty_result_callback_and_rebinding','empty_input_and_callback_alias','empty_source_join_maintains_earlier_reference'):
            with self.subTest(name=name):self.check(name)


CYCLES={'map_callback_instance_cycle': 'class Holder:\n'
                                ' def __init__(self):self.items=[1]\n'
                                'def install(holder):\n'
                                ' def callback(value):return holder\n'
                                ' holder.stream=map(callback,holder.items)\n'
                                'holder=Holder()\n'
                                'install(holder)\n'
                                'print(holder.stream is not None)\n',
 'map_source_list_cycle': 'items=[]\n'
                          'stream=map(bool,items)\n'
                          'items.append(stream)\n'
                          'print(next(stream))\n'}


class MapMetadataTests(unittest.TestCase):
    def test_partial_storage_proofs_are_inference_only(self):
        from py2fastrust.native_class_storage import shared_element
        from py2fastrust.native_classes import Cell,merge,ClassUnsupported
        from py2fastrust.native_types import ListType,kind_tag
        node=ast.parse('[]').body[0]
        self.assertFalse(shared_element(ListType(None)))
        self.assertTrue(shared_element(ListType('none')))
        self.assertNotEqual(kind_tag(ListType(None)),kind_tag(ListType('none')))
        with self.assertRaises(ClassUnsupported):merge(Cell('list',(Cell(),)),Cell('none'),node)
        combined=merge(Cell('list',(Cell(),)),Cell('none'),node,allow_unresolved=True)
        self.assertEqual(combined.root().tag,'union')

    def test_real_ownership_cycles_keep_the_required_collector_boundary(self):
        from py2fastrust import transpile,TranspileOptions
        for name,source in CYCLES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(result.diagnostics)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertIn('cycle',result.diagnostics[0].message)
                    self.assertGreater(result.diagnostics[0].line,0)

    def test_callback_call_arguments_keep_the_original_ast(self):
        unit=parse_source(CASES['three_sources'],'map_case.py')
        before=ast.dump(unit.tree,include_attributes=True);table=unit.table
        model=Model(unit.tree,unit.filename,'i64',(),unit=unit);model.run()
        records=[record for record in model.iterators.records if record.operation=='map']
        self.assertEqual(len(records),1)
        self.assertEqual(len(records[0].input_types),3)
        self.assertTrue(records[0].demands)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertIs(unit.table,table)
