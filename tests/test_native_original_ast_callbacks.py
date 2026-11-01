"""Captured callbacks retain original source evaluation and callable identities."""
import unittest
import ast
from unittest.mock import patch
import test_native_explicit_raise as raise_tests
CASES={'scalar_map': 'print(list(map(lambda value:value*3-1,[1,2,3])))\n',
 'nested_rows': 'rows=[[1,2],[3,4]]\n'
                'print(sum(sum(map(lambda value:value*2,row))for row in '
                'rows))\n',
 'generator_default_snapshot': 'rows=[[1,2],[3]]\n'
                               'print(sum(sum(map(lambda '
                               'value,offset=index:value+offset,row))for '
                               'index,row in enumerate(rows)))\n',
 'default_evaluated_once': 'def mark():\n'
                           ' print("default")\n'
                           ' return 7\n'
                           'print(list(map(lambda '
                           'value,offset=mark():value+offset,[1,2,3])))\n',
 'construction_argument_order': 'def mark():\n'
                                ' print("default")\n'
                                ' return 7\n'
                                'def source():\n'
                                ' print("source")\n'
                                ' return [1,2]\n'
                                'print(list(map(lambda '
                                'value,offset=mark():value+offset,source())))\n',
 'consumer_argument_order': 'def mark():\n'
                            ' print("default")\n'
                            ' return 7\n'
                            'def source():\n'
                            ' print("source")\n'
                            ' return [1,2]\n'
                            'def later():\n'
                            ' print("later")\n'
                            ' return 10\n'
                            'print(sum(map(lambda '
                            'value,offset=mark():(print("body",value),value+offset)[1],source()),later()))\n',
 'empty_default_still_runs': 'def mark():\n'
                             ' print("default")\n'
                             ' return 7\n'
                             'print(list(map(lambda '
                             'value,offset=mark():value+offset,[])))\n',
 'bad_default_before_source': 'def source():\n'
                              ' print("source")\n'
                              ' return [1,2]\n'
                              'print(list(map(lambda '
                              'value,unused=int("bad"):value,source())))\n',
 'generator_target_default_length': 'rows=[[1],[2,3]]\n'
                                    'print(sum(sum(map(lambda '
                                    'value,size=len(row):value+size,row))for '
                                    'row in rows))\n',
 'free_generator_target': 'rows=[[1],[2,3]]\n'
                          'print(sum(sum(map(lambda value:value+index,row))for '
                          'index,row in enumerate(rows)))\n',
 'global_read_stays_current': 'offset=2\n'
                              'print(list(map(lambda '
                              'value:value+offset,[1,2,3])))\n',
 'scalar_filter': 'print(list(filter(lambda value:value%2,[0,1,2,3,4])))\n',
 'filter_defaults_once': 'def mark():\n'
                         ' print("default")\n'
                         ' return 2\n'
                         'print(list(filter(lambda '
                         'value,limit=mark():value>limit,[1,2,3,4])))\n',
 'filter_body_effects': 'print(list(filter(lambda '
                        'value:(print("body",value),value%2)[1],[1,2,3])))\n',
 'none_predicate_result': 'print(list(filter(lambda value:None,[1,2,3])))\n',
 'positional_keyword_defaults': 'print(list(map(lambda '
                                'value,/,*,scale=3:value*scale,[1,2])))\n',
 'bool_map': 'print(list(map(lambda value:value>1,[0,1,2])))\n',
 'string_map': 'print(list(map(lambda value:value+"!",["a","bb"])))\n',
 'float_list_map': 'print(list(map(lambda value:value/2,[1,2,3])))\n',
 'float_sum_needs_compatible_consumer': 'print(sum(map(lambda '
                                        'value:value/2,[1,2,3])))\n',
 'tuple_argument_map': 'print(list(map(lambda '
                       'pair:pair[0]+pair[1],[(1,2),(3,4)])))\n',
 'math_captured_reference': 'from math import isqrt as root\n'
                            'print(list(map(root,[0,1,8,16])))\n',
 'math_filter_reference': 'from math import isqrt as root\n'
                          'print(list(filter(root,[0,1,8,16])))\n',
 'source_function_reference': 'def triple(value):return value*3\n'
                              'print(sum(map(triple,[1,2,3])))\n',
 'lambda_calls_source_function': 'def triple(value):return value*3\n'
                                 'print(sum(map(lambda '
                                 'value:triple(value),[1,2,3])))\n',
 'static_map_alias': 'apply=map\n'
                     'print(list(apply(lambda value:value+3,[1,2])))\n',
 'shadowed_map': 'def map(function,values):return [function(9)]\n'
                 'print(map(lambda value:value+3,[1,2]))\n',
 'mutable_default_shared': 'print(list(map(lambda '
                           'value,cache=[]:(cache.append(value),len(cache))[1],[1,2,3])))\n',
 'variadic_lambda': 'print(list(map(lambda '
                    '*values:sum(values),[1,2],[3,4])))\n',
 'bad_callback_binding_laziness': 'print(list(map(lambda a,b:a+b,[])))\n'
                                  'print(list(map(lambda a,b:a+b,[1])))\n',
 'body_error_source_frames': 'print(list(map(lambda '
                             'value:10//(value-2),[1,2,3])))\n',
 'callback_stop_is_exhaustion': 'print(list(map(lambda '
                                'value:next(iter(())),[1,2])))\n',
 'generator_default_stop_cause': 'print(sum(sum(map(lambda '
                                 'value,unused=next(iter(())):value,[1]))for '
                                 'unused in range(1)))\n',
 'callee_capture_before_source_rebind': 'apply=map\n'
                                        'def source():\n'
                                        ' global apply\n'
                                        ' apply=7\n'
                                        ' return [1,2]\n'
                                        'print(list(apply(lambda '
                                        'value:value+3,source())),apply)\n',
 'source_call_mutates_input': 'values=[1,2,3]\n'
                              'def change(value):\n'
                              ' if value==1:values.append(4)\n'
                              ' return value*2\n'
                              'print(list(map(lambda '
                              'value:change(value),values)),values)\n'}
class OriginalAstCallbacks(unittest.TestCase):
    exercise=raise_tests.NativeRaiseExecutionTests.exercise
    def test_scalar_map(self):self.exercise(CASES['scalar_map'],'')
    def test_nested_rows(self):self.exercise(CASES['nested_rows'],'')
    def test_generator_default_snapshot(self):self.exercise(CASES['generator_default_snapshot'],'')
    def test_default_evaluated_once(self):self.exercise(CASES['default_evaluated_once'],'')
    def test_construction_argument_order(self):self.exercise(CASES['construction_argument_order'],'')
    def test_consumer_argument_order(self):self.exercise(CASES['consumer_argument_order'],'')
    def test_empty_default_still_runs(self):self.exercise(CASES['empty_default_still_runs'],'')
    def test_bad_default_before_source(self):self.exercise(CASES['bad_default_before_source'],'')
    def test_generator_target_default_length(self):self.exercise(CASES['generator_target_default_length'],'')
    def test_free_generator_target(self):self.exercise(CASES['free_generator_target'],'')
    def test_global_read_stays_current(self):self.exercise(CASES['global_read_stays_current'],'')
    def test_scalar_filter(self):self.exercise(CASES['scalar_filter'],'')
    def test_filter_defaults_once(self):self.exercise(CASES['filter_defaults_once'],'')
    def test_filter_body_effects(self):self.exercise(CASES['filter_body_effects'],'')
    def test_none_predicate_result(self):self.exercise(CASES['none_predicate_result'],'')
    def test_positional_keyword_defaults(self):self.exercise(CASES['positional_keyword_defaults'],'')
    def test_bool_map(self):self.exercise(CASES['bool_map'],'')
    def test_string_map(self):self.exercise(CASES['string_map'],'')
    def test_float_list_map(self):self.exercise(CASES['float_list_map'],'')
    def test_float_sum_needs_compatible_consumer(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            with self.subTest(integer=mode):
                result=transpile(CASES['float_sum_needs_compatible_consumer'],TranspileOptions(integer=mode,filename='main.py'))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertIn("call 'sum'",result.diagnostics[0].message)
                self.assertEqual(result.diagnostics[0].line,1)
    def test_tuple_argument_map(self):self.exercise(CASES['tuple_argument_map'],'')
    def test_math_captured_reference(self):self.exercise(CASES['math_captured_reference'],'')
    def test_math_filter_reference(self):self.exercise(CASES['math_filter_reference'],'')
    def test_source_function_reference(self):self.exercise(CASES['source_function_reference'],'')
    def test_lambda_calls_source_function(self):self.exercise(CASES['lambda_calls_source_function'],'')
    def test_static_map_alias(self):self.exercise(CASES['static_map_alias'],'')
    def test_shadowed_map(self):self.exercise(CASES['shadowed_map'],'')
    def test_mutable_default_shared(self):self.exercise(CASES['mutable_default_shared'],'')
    def test_variadic_lambda(self):self.exercise(CASES['variadic_lambda'],'')
    def test_bad_callback_binding_laziness(self):self.exercise(CASES['bad_callback_binding_laziness'],'')
    def test_body_error_source_frames(self):self.exercise(CASES['body_error_source_frames'],'')
    def test_callback_stop_is_exhaustion(self):self.exercise(CASES['callback_stop_is_exhaustion'],'')
    def test_generator_default_stop_cause(self):self.exercise(CASES['generator_default_stop_cause'],'')
    def test_callee_capture_before_source_rebind(self):self.exercise(CASES['callee_capture_before_source_rebind'],'')
    def test_source_call_mutates_input(self):self.exercise(CASES['source_call_mutates_input'],'')

PARSER_CASES={'text': 'print(int("bad"))\n',
 'saved': 'parse=int\nprint(parse(" 4_ "))\n',
 'quote': 'print(int("can\'t"))\n',
 'controls': 'print(int("12\\x1c"))\n',
 'bytes': 'print(int(b"bad"))\n',
 'codepoint': 'print(list(map(int,"1x")))\n',
 'unicode': 'print(int("に"))\n'}
REVIEW_CASES={'default_once_before_source': 'events=[]\n'
                               'def default():events.append("default");return '
                               '7\n'
                               'def source():events.append("source");return '
                               '[1,2]\n'
                               'values=map(lambda '
                               'item,offset=default():item+offset,source())\n'
                               'print(events)\n'
                               'print(list(values))\n'
                               'print(events)\n',
 'nested_constructor_order': 'events=[]\n'
                             'def mark(name):events.append(name);return 1\n'
                             'values=map(lambda '
                             'item,offset=mark("outer"):item+offset,map(lambda '
                             'item,offset=mark("inner"):item+offset,[1]))\n'
                             'print(events)\n'
                             'print(list(values))\n'
                             'print(events)\n',
 'empty_invalid_lazy_binding': 'print(list(map(lambda '
                               'left,right:left+right,[])))\n'
                               'print(list(filter(lambda *,item:item,[])))\n'}

class OriginalAstCallbackParserErrors(unittest.TestCase):
    exercise=raise_tests.NativeRaiseExecutionTests.exercise
    def test_text(self):self.exercise(PARSER_CASES['text'],"",string_mode='ascii')
    def test_saved(self):self.exercise(PARSER_CASES['saved'],"",string_mode='ascii')
    def test_quote(self):self.exercise(PARSER_CASES['quote'],"",string_mode='ascii')
    def test_controls(self):self.exercise(PARSER_CASES['controls'],"",string_mode='ascii')
    def test_bytes(self):self.exercise(PARSER_CASES['bytes'],"",string_mode='ascii')
    def test_codepoint(self):self.exercise(PARSER_CASES['codepoint'],"",string_mode='ascii')
    def test_unicode(self):self.exercise(PARSER_CASES['unicode'],"",string_mode='unicode')

class OriginalAstCallbackIndependentReview(unittest.TestCase):
    exercise=raise_tests.NativeRaiseExecutionTests.exercise
    def test_default_once_before_source(self):self.exercise(REVIEW_CASES['default_once_before_source'],"")
    def test_nested_constructor_order(self):self.exercise(REVIEW_CASES['nested_constructor_order'],"")
    def test_empty_invalid_lazy_binding(self):self.exercise(REVIEW_CASES['empty_invalid_lazy_binding'],"")

class OriginalAstCallbackPlans(unittest.TestCase):
    def test_proved_immediate_callbacks_keep_ordinary_rust_selection(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_frame_selection import select_frames
        from py2fastrust import transpile,TranspileOptions
        for name in ('scalar_map','nested_rows','default_evaluated_once','scalar_filter','tuple_argument_map'):
            source=CASES[name];unit=build_program(source,'callback.py').main
            before=ast.dump(unit.tree,include_attributes=True)
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    selected=select_frames(unit,integer=mode)
                    self.assertFalse(selected.required,selected.reasons)
                    self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
                    with patch('py2fastrust.native_classes.try_generate_classes',side_effect=AssertionError('unexpected frame route')),patch('ast.copy_location',side_effect=AssertionError('synthesized callback source AST')):
                        result=transpile(source,TranspileOptions(integer=mode,filename=unit.filename))
                    self.assertTrue(result.success,result.diagnostics)
            unit.check_identity(source,unit.filename)

    def test_unproved_effects_and_aliases_select_typed_storage_before_emission(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_frame_selection import select_frames
        for name in ('free_generator_target','global_read_stays_current','mutable_default_shared','callback_stop_is_exhaustion','generator_default_stop_cause','source_call_mutates_input','callee_capture_before_source_rebind','float_list_map'):
            unit=build_program(CASES[name],'callback.py').main
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):self.assertTrue(select_frames(unit,integer=mode).required)

PROJECTION_CASES={'conditional_scalars': 'print(list(map(lambda x:True if x else 4,[0,1,2])))\n',
 'tuple_results': 'print(list(map(lambda x:(x,x+1),[1,2,3])))\n',
 'nested_maps': 'print(list(map(lambda x:x+3,map(lambda '
                'x,y=2:x*y,[1,2,3]))))\n',
 'text_items': 'print(list(map(lambda x:x+"!","abc")))\n',
 'bytes_items': 'print(list(filter(lambda x:x%2,b"abc")))\n',
 'tuple_default': 'print(list(map(lambda x,pair=(3,4):x+pair[0],[1,2])))\n',
 'source_returns_error': 'def divide(x):return 9//(x-2)\n'
                         'print(list(map(divide,[1,2,3])))\n',
 'tuple_source_filter': 'print(list(filter(lambda '
                        'pair:pair[0]>pair[1],[(1,2),(3,1)])))\n',
 'short_circuit_body': 'print(list(map(lambda x:x and 7,[0,1,2])))\n',
 'lambda_default_callee_shadow': 'def operate(x):return x+4\n'
                                 'print(list(map(lambda '
                                 'operate:operate*2,[1,2])))\n',
 'negative_power_typed': 'print(list(map(lambda x:x**-1,[1,2])))\n',
 'float_identity_typed': 'x=float("nan")\n'
                         'values=[x]\n'
                         'print(list(map(lambda y:y==y,values)))\n'}

class OriginalAstCallbackProjections(unittest.TestCase):
    exercise=raise_tests.NativeRaiseExecutionTests.exercise
    def test_conditional_scalars(self):self.exercise(PROJECTION_CASES['conditional_scalars'],"")
    def test_tuple_results(self):self.exercise(PROJECTION_CASES['tuple_results'],"")
    def test_nested_maps(self):self.exercise(PROJECTION_CASES['nested_maps'],"")
    def test_text_items(self):self.exercise(PROJECTION_CASES['text_items'],"")
    def test_bytes_items(self):self.exercise(PROJECTION_CASES['bytes_items'],"")
    def test_tuple_default(self):self.exercise(PROJECTION_CASES['tuple_default'],"")
    def test_source_returns_error(self):self.exercise(PROJECTION_CASES['source_returns_error'],"")
    def test_tuple_source_filter(self):self.exercise(PROJECTION_CASES['tuple_source_filter'],"")
    def test_short_circuit_body(self):self.exercise(PROJECTION_CASES['short_circuit_body'],"")
    def test_lambda_default_callee_shadow(self):self.exercise(PROJECTION_CASES['lambda_default_callee_shadow'],"")
    def test_float_identity_typed(self):self.exercise(PROJECTION_CASES['float_identity_typed'],"")
    def test_negative_power_retains_its_existing_numeric_boundary(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            result=transpile(PROJECTION_CASES['negative_power_typed'],TranspileOptions(integer=mode,filename='main.py'))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn("operator '**'",result.diagnostics[0].message)
            self.assertEqual(result.diagnostics[0].line,1)

CALL_CAPABILITY_CASES={'str_none': 'print(list(map(lambda x:str(x),[None,1])))\n',
 'int_none': 'print(list(map(lambda x:int(x),[None,1])))\n',
 'abs_bytes': 'print(list(map(lambda x:abs(x),[b"2"])))\n',
 'len_number': 'print(list(map(lambda x:len(x),[1])))\n',
 'pow_int': 'print(list(map(lambda x:pow(x,2),[1,2])))\n',
 'len_tuple': 'print(list(map(lambda x:len(x),[(1,2),(3,4)])))\n',
 'source_str_none': 'def text(x):return str(x)\n'
                    'print(list(map(lambda x:text(x),[None,1])))\n',
 'source_int_none': 'def number(x):return int(x)\n'
                    'print(list(map(lambda x:number(x),[None,1])))\n'}

class OriginalAstCallbackCallCapabilities(unittest.TestCase):
    exercise=raise_tests.NativeRaiseExecutionTests.exercise
    def test_str_none(self):self.exercise(CALL_CAPABILITY_CASES['str_none'],"")
    def test_int_none(self):self.exercise(CALL_CAPABILITY_CASES['int_none'],"")
    def test_abs_bytes(self):self.exercise(CALL_CAPABILITY_CASES['abs_bytes'],"")
    def test_len_number(self):self.exercise(CALL_CAPABILITY_CASES['len_number'],"")
    def test_pow_int(self):self.exercise(CALL_CAPABILITY_CASES['pow_int'],"")
    def test_len_tuple(self):self.exercise(CALL_CAPABILITY_CASES['len_tuple'],"")
    def test_source_str_none(self):self.exercise(CALL_CAPABILITY_CASES['source_str_none'],"")
    def test_source_int_none(self):self.exercise(CALL_CAPABILITY_CASES['source_int_none'],"")
    def test_unproved_unary_operands_use_typed_call_storage(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_frame_selection import select_frames
        for name in ('str_none','int_none','source_str_none','source_int_none'):
            unit=build_program(CALL_CAPABILITY_CASES[name],'callback.py').main
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):self.assertTrue(select_frames(unit,integer=mode).required)
