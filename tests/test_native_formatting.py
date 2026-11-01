"""Native formatting compares untouched ordinary Python sources with CPython."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'basic_fields': 'count=12\nname="answer"\nprint(f"{name}: {count}")\n',
 'bool_and_none': 'for value in [True,False,None]:print(f"{value}",f"{value!r}")\n'
                  'print(f"{True:04d}")\n',
 'captured_format_callable': 'def apply(callback,value,spec):return callback(value,spec)\n'
                             'print(apply(format,123,"08d"))\n',
 'closure_fields': 'def make(n):\n'
                   ' def render():return f"[{n:05d}]"\n'
                   ' return render\n'
                   'render=make(23)\n'
                   'print(render())\n',
 'container_fields': 'values=[1,True,None]\n'
                     'mapping={"a":[2]}\n'
                     'print(f"{values}|{mapping}|{(1,\'x\')}|{b\'AZ\'}")\n',
 'container_nonempty_spec': 'print(f"{[1]:10}")\n',
 'conversion_error_order': 'row=[1]\n'
                           'def specification():\n'
                           ' row.append(2)\n'
                           ' return "d"\n'
                           'print(f"{row!r:{specification()}}")\n',
 'debug_fields': 'value=17\ntext="hello"\nprint(f"{value=}",f"{text=}",f"{value + 3 = :04d}")\n',
 'dynamic_width_precision': 'number=12.34567\n'
                            'width=14\n'
                            'precision=3\n'
                            'print(f"{number:0{width}.{precision}f}")\n',
 'empty_specs': 'print(f"{True:}",f"{3:}",f"{1.25:}",format(None,""),format([1],""))\n',
 'field_order': 'def mark(label,value):\n'
                ' print(label)\n'
                ' return value\n'
                'print(f"{mark(\'first\',7):03d}-{mark(\'second\',9)}")\n',
 'float_precision': 'for number in [0.0,-0.0,1.25,-123.456,0.00001,1e20]:\n'
                    ' print(f"{number:.9f}",f"{number:.3e}",f"{number:.4g}")\n',
 'format_builtin_alias': 'from builtins import format as present\n'
                         'print(present(1234,"#016_x"),present(1.25,".2f"),present("abc",">7s"))\n',
 'format_default_argument': 'print(format(17),format(True),format(1.25),format("text"))\n',
 'format_error_frame': 'def render(n):return f"{n:qq}"\nprint(render(17))\n',
 'format_keyword_error': 'def mark(value):print(value);return value\n'
                         'print(format(mark(7),format_spec=mark("d")))\n',
 'format_missing_argument': 'format()\n',
 'format_spec_type_error': 'def mark(value):print(value);return value\n'
                           'print(format(mark(7),mark(3)))\n',
 'int_float_presentation': 'print(f"{1234:.2f}",format(-1234,".3e"),f"{True:.1f}")\n',
 'integer_widths': 'for n in [0,17,-17,1234567]:\n'
                   ' print(f"{n:08d}",f"{n:+#012x}",f"{n:,}",f"{n:^12}")\n',
 'invalid_float_spec': 'print("before")\nprint(f"{1.25:d}")\n',
 'invalid_integer_spec': 'print("before")\nprint(f"{17:qq}")\n',
 'invalid_string_sign': 'print(f"{\'text\':+8s}")\n',
 'nested_fstrings': 'left=3\nright=7\nprint(f"[{f\'{left}+{right}\'}]={left+right}")\n',
 'passed_class_fields': 'class Result:\n'
                        ' def __init__(self,n):self.value=n\n'
                        ' def render(self):return f"answer={self.value:05d}"\n'
                        'print(Result(17).render())\n',
 'plain_field_after_spec_mutation': 'row=[1]\n'
                                    'def specification():\n'
                                    ' row.append(2)\n'
                                    ' return ""\n'
                                    'print(f"{row:{specification()}}",row)\n',
 'repr_before_spec_mutation': 'row=[1]\n'
                              'def specification():\n'
                              ' row.append(2)\n'
                              ' return ""\n'
                              'print(f"{row!r:{specification()}}",row)\n',
 'unicode_repr_str_ascii': 'value="猫é\\n"\nprint(f"{value!s}|{value!r}|{value!a}")\n',
 'unicode_string_formats': 'for value in ["","abc","猫🐈é"]:\n'
                           ' print(repr(f"{value:>8.2s}"),repr(f"{value:💠^8s}"))\n',
 'value_before_spec': 'def mark(label,value):\n'
                      ' print(label)\n'
                      ' return value\n'
                      'print(f"{mark(\'value\',7):0{mark(\'width\',4)}d}")\n'}

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class FormattingTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_basic_fields(self):self.check('basic_fields')

    def test_integer_widths(self):self.check('integer_widths')

    def test_float_precision(self):self.check('float_precision')

    def test_dynamic_width_precision(self):self.check('dynamic_width_precision')

    def test_debug_fields(self):self.check('debug_fields')

    def test_unicode_repr_str_ascii(self):self.check('unicode_repr_str_ascii')

    def test_format_builtin_alias(self):self.check('format_builtin_alias')

    def test_captured_format_callable(self):self.check('captured_format_callable')

    def test_passed_class_fields(self):self.check('passed_class_fields')

    def test_closure_fields(self):self.check('closure_fields')

    def test_field_order(self):self.check('field_order')

    def test_value_before_spec(self):self.check('value_before_spec')

    def test_repr_before_spec_mutation(self):self.check('repr_before_spec_mutation')

    def test_plain_field_after_spec_mutation(self):self.check('plain_field_after_spec_mutation')

    def test_container_fields(self):self.check('container_fields')

    def test_unicode_string_formats(self):self.check('unicode_string_formats')

    def test_bool_and_none(self):self.check('bool_and_none')

    def test_nested_fstrings(self):self.check('nested_fstrings')

    def test_empty_specs(self):self.check('empty_specs')

    def test_format_default_argument(self):self.check('format_default_argument')

    def test_int_float_presentation(self):self.check('int_float_presentation')

    def test_invalid_integer_spec(self):self.check('invalid_integer_spec')

    def test_invalid_float_spec(self):self.check('invalid_float_spec')

    def test_invalid_string_sign(self):self.check('invalid_string_sign')

    def test_container_nonempty_spec(self):self.check('container_nonempty_spec')

    def test_format_spec_type_error(self):self.check('format_spec_type_error')

    def test_format_missing_argument(self):self.check('format_missing_argument')

    def test_format_keyword_error(self):self.check('format_keyword_error')

    def test_format_error_frame(self):self.check('format_error_frame')

    def test_conversion_error_order(self):self.check('conversion_error_order')


EXTRA_CASES={'class_field_specification_effects': 'class Box:\n'
                                      ' def __init__(self):self.n=3\n'
                                      'box=Box()\n'
                                      'def specification():\n'
                                      ' box.n+=4\n'
                                      ' return "03d"\n'
                                      'print(f"{box.n:{specification()}} {box.n}")\n',
 'finite_value_alternatives': 'def render(value):return f"value={value}|repr={value!r}"\n'
                              'print(render(3),render(True),render(None),render(1.25),render([2]),render("ok"))\n',
 'float_dynamic_presentations': 'def render(n,spec):return format(n,spec)\n'
                                'for n in [0.0,-0.0,1.25,123456.75,-0.0001]:\n'
                                ' for spec in ["", "+012.2f", ".3E", "#.4g", ",.2f", "z.1f", '
                                '".1%"]:\n'
                                '  print(repr(render(n,spec)))\n',
 'float_inf_fields': 'for number in '
                     '[1e400,-1e400]:print(f"{number}",f"{number:+08.2F}",f"{number:.2e}")\n',
 'format_callee_alias': 'render=format\n'
                        'format=lambda value,spec="":"replacement"\n'
                        'print(render(17,"04d"),format(17))\n',
 'format_excess_arguments': 'def mark(v):\n print(v)\n return v\nformat(mark(1),mark(2),mark(3))\n',
 'format_int_precision_error': 'print(format(17,".2d"))\n',
 'format_string_width_overflow': 'print(format("a","9223372036854775808s"))\n',
 'format_width_overflow': 'print(format(1.25,"9223372036854775808f"))\n',
 'integer_character': 'for number in '
                      '[0,65,127]:print(repr(format(number,"c")),repr(format(number,"^5c")))\n',
 'integer_dynamic_radices': 'def render(n,spec):return format(n,spec)\n'
                            'for n in [0,1,-31,1234567]:\n'
                            ' for spec in ["", "#b", "#o", "#x", "#X", "+012_d", "^14d", '
                            '"*=+12d"]:\n'
                            '  print(repr(render(n,spec)))\n',
 'invalid_float_multi_spec': 'print(format(1.25,"qq"))\n',
 'invalid_format_spec_none': 'def show(value,spec):return format(value,spec)\n'
                             'print(show(3,"03d"))\n'
                             'print(show(4,None))\n',
 'invalid_string_multi_spec': 'print(format("a","qq"))\n',
 'repr_callee_alias': 'render=repr\n'
                      'repr=lambda value:"replacement"\n'
                      'print(render([1,True,None]),repr(3))\n',
 'string_dynamic_formats': 'def render(value,spec):return format(value,spec)\n'
                           'for value in ["", "abc", "123456"]:\n'
                           ' for spec in ["", "s", "08s", "*^9.4s", "<8.2", ">7"]:\n'
                           '  print(repr(render(value,spec)))\n',
 'unicode_ascii_nested': 'from builtins import ascii as present\n'
                         'print(present(["猫", "é", "🐈"]),f"{[\'猫\',\'é\',\'🐈\']!a}")\n',
 'unicode_decimal_widths': 'print(repr(format(17,"٠٨d")),repr(format(1.25,"٨.٢f")),repr(format("猫","🐈^٥s")))\n',
 'unsupported_source_format_protocol': 'class Box:\n'
                                       ' def __format__(self,spec):return "custom"+spec\n'
                                       'print(f"{Box():03}")\n',
 'unsupported_source_repr_protocol': 'class Box:\n'
                                     ' def __repr__(self):return "custom"\n'
                                     'print(f"{Box()!r}")\n'}

class FormattingExtraTests(unittest.TestCase):
    cases=EXTRA_CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_integer_dynamic_radices(self):self.check('integer_dynamic_radices')

    def test_integer_character(self):self.check('integer_character')

    def test_float_dynamic_presentations(self):self.check('float_dynamic_presentations')

    def test_float_inf_fields(self):self.check('float_inf_fields')

    def test_string_dynamic_formats(self):self.check('string_dynamic_formats')

    def test_unicode_decimal_widths(self):self.check('unicode_decimal_widths')

    def test_class_field_specification_effects(self):self.check('class_field_specification_effects')

    def test_finite_value_alternatives(self):self.check('finite_value_alternatives')

    def test_format_callee_alias(self):self.check('format_callee_alias')

    def test_repr_callee_alias(self):self.check('repr_callee_alias')

    def test_unicode_ascii_nested(self):self.check('unicode_ascii_nested')

    def test_invalid_float_multi_spec(self):self.check('invalid_float_multi_spec')

    def test_invalid_string_multi_spec(self):self.check('invalid_string_multi_spec')

    def test_invalid_format_spec_none(self):self.check('invalid_format_spec_none')

    def test_format_excess_arguments(self):self.check('format_excess_arguments')

    def test_format_width_overflow(self):self.check('format_width_overflow')

    def test_format_string_width_overflow(self):self.check('format_string_width_overflow')

    def test_format_int_precision_error(self):self.check('format_int_precision_error')

    def test_unsupported_source_format_protocol(self):
        from py2fastrust import transpile,TranspileOptions
        from unittest.mock import patch
        for mode in ('i64','i128','bigint'):
            with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
                result=transpile(self.cases['unsupported_source_format_protocol'],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            detail=' '.join(str(value)for value in result.diagnostics)
            self.assertIn('protocol dispatch',detail)
            self.assertIn('__format__',detail)

    def test_unsupported_source_repr_protocol(self):
        from py2fastrust import transpile,TranspileOptions
        from unittest.mock import patch
        for mode in ('i64','i128','bigint'):
            with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
                result=transpile(self.cases['unsupported_source_repr_protocol'],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            detail=' '.join(str(value)for value in result.diagnostics)
            self.assertIn('protocol dispatch',detail)
            self.assertIn('__repr__',detail)


class FormattingHelperSelectionTests(unittest.TestCase):
    def test_unreached_format_fields_do_not_select_typed_frames(self):
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_frame_selection import select_frames
        parsed=parse_source('def unused():return f"{undefined}"\nprint(1)\n','unused_field.py')
        self.assertFalse(select_frames(parsed).required)

    def test_plain_fields_do_not_emit_unused_formatters_or_unicode_tables(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            for string_mode in ('ascii','unicode'):
                result=transpile('position=17\nprint(f"{position}")\n',TranspileOptions(integer=mode,string_mode=string_mode,license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertNotIn('NativeFormatSpec',result.rust_source)
                self.assertNotIn('native_format_float',result.rust_source)
                self.assertNotIn('NATIVE_FORMAT_ZEROES',result.rust_source)
                self.assertNotIn('UNICODE LICENSE',result.rust_source)

    def test_formatting_default_ascii_has_no_unicode_data(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            result=transpile('print(f"{17:08d}")\n',TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('NATIVE_FORMAT_ZEROES',result.rust_source)
            self.assertNotIn('UNICODE LICENSE',result.rust_source)
