"""Explicit integer bases preserve captured identities, errors and width policy."""
import ast
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import try_generate_classes
import test_native_class_iterators as execution
import test_native_iterator_reductions as width_execution

CASES = {'all_radices': 'for base in range(2,37):\n print(int("10",base),int("-10",base),int(b"+10",base))\n',
 'argument_order': 'def mark(name,value):\n'
                   ' print(name)\n'
                   ' return value\n'
                   'print(int(mark("text","ff"),base=mark("base",16)))\n',
 'bad_keyword': 'int("10",bad=2)\n',
 'base_boolean': 'print(int("0",False))\nprint(int("1",True))\n',
 'base_extreme': 'print(int("10",9223372036854775807))\n',
 'base_negative': 'print(int("10",-2))\n',
 'base_too_large': 'print(int("10",37))\n',
 'base_too_small': 'print(int("10",1))\n',
 'base_without_text': 'int(base=2)\n',
 'binding_effects': 'def mark(name,value):\n'
                    ' print(name)\n'
                    ' return value\n'
                    'int(mark("first","1"),mark("base",2),bad=mark("bad",3))\n',
 'bytes_and_keywords': 'print(int(b" \\t-1_f\\r\\n",16),int("10101",base=2),int(b"ZZ",base=36))\n',
 'captured_callback': 'def parse(operation,text,base):return operation(text,base)\n'
                      'print(parse(int,"101",2),parse(int,b"ff",16))\n',
 'class_field': 'class Parse:\n'
                ' def __init__(self):self.operation=int\n'
                ' def convert(self,text,base):return self.operation(text,base)\n'
                'print(Parse().convert("beef",16))\n',
 'double_underscore': 'print(int("0x__1",16))\n',
 'duplicate_base': 'int("10",2,base=3)\n',
 'empty': 'print(int("",2))\n',
 'error_frame': 'def parse(text,base):return int(text,base)\nprint(parse("102",2))\n',
 'excess_positionals': 'int("10",2,3)\n',
 'invalid_base_before_source_type': 'print(int(None,1))\n',
 'invalid_bytes': 'print(int(b"\\xff",16))\n',
 'invalid_digit': 'print(int("102",2))\n',
 'leading_underscore': 'print(int("_10",2))\n',
 'leading_zero_auto': 'print(int("0010",0))\n',
 'multi_source_map': 'print(list(map(int,["11","11","11"],[2,8,16])))\n',
 'one_argument_unchanged': 'print(int(),int("1_234"),int(b"-17"),int(True),int(-1.5))\n',
 'positional_only_text': 'int(string="10",base=2)\n',
 'prefixes': 'for text,base in '
             '[("0xff",0),("-0B101",0),("+0o77",8),("0b11",16),("0X_Ff",16),("0_0",0),("000",0),("010",8)]:\n'
             ' print(int(text,base))\n',
 'saved_identity': 'parse=int\nint=5\nprint(parse("abc",16),int)\n',
 'trailing_underscore': 'print(int("10_",2))\n',
 'unicode_ascii_only_letters': '# pytors: --string-mode unicode\nprint(int("ＦＦ",16))\n',
 'unicode_digits': '# pytors: --string-mode unicode\n'
                   'for text,base in [("١٢",10),("１２",16),("٠xＦ",16),("𝟘b١٠",0)]:\n'
                   ' print(int(text,base))\n',
 'unicode_prefixes': '# pytors: --string-mode unicode\n'
                     'print(int("٠x١f",0),int("０o７７",8),int("\u2003-١_٢\u3000",16))\n',
 'unicode_whitespace': '# pytors: --string-mode unicode\nprint(int("\x85\xa0-١f\u2028\u3000",16))\n',
 'union_payloads': 'def parse(text,base):return int(text,base)\nprint(parse("11",2),parse(b"ff",16))\n',
 'whitespace_separator': 'print(int("\\x1c1",16))\n',
 'wrong_base_float': 'print(int("10",1.5))\n',
 'wrong_base_none': 'print(int("10",None))\n',
 'wrong_base_text': 'print(int("10","2"))\n',
 'wrong_string_float': 'print(int(1.5,2))\n',
 'wrong_string_integer': 'print(int(12,2))\n',
 'wrong_string_none': 'print(int(None,2))\n'}

class IntegerBaseCapabilityTests(unittest.TestCase):
    def test_original_ast_and_nodes_are_preserved(self):
        source="parse=int\nprint(parse('ff',16))\n"
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(try_generate_classes(source,'main.py','i64',unit=unit))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_custom_base_index_protocol_is_positioned(self):
        source="class Base:\n def __index__(self):return 16\nprint(int('ff',Base()))\n"
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('__index__',result.diagnostics[0].message)

    def test_ascii_parser_does_not_emit_unicode_data(self):
        for mode in ('i64','i128','bigint'):
            result=transpile("print(int(input(),16))\n",TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('UNICODE LICENSE V3',result.rust_source)
            self.assertNotIn('NATIVE_FIXED_INT_ZEROES',result.rust_source)


class IntegerBaseExecutionTests(unittest.TestCase):
    cases=CASES
    check=execution.IteratorExecutionTests.check

    def test_all_radices(self):
        self.check('all_radices')

    def test_argument_order(self):
        self.check('argument_order')

    def test_bad_keyword(self):
        self.check('bad_keyword')

    def test_base_boolean(self):
        self.check('base_boolean')

    def test_base_extreme(self):
        self.check('base_extreme')

    def test_base_negative(self):
        self.check('base_negative')

    def test_base_too_large(self):
        self.check('base_too_large')

    def test_base_too_small(self):
        self.check('base_too_small')

    def test_base_without_text(self):
        self.check('base_without_text')

    def test_binding_effects(self):
        self.check('binding_effects')

    def test_bytes_and_keywords(self):
        self.check('bytes_and_keywords')

    def test_captured_callback(self):
        self.check('captured_callback')

    def test_class_field(self):
        self.check('class_field')

    def test_double_underscore(self):
        self.check('double_underscore')

    def test_duplicate_base(self):
        self.check('duplicate_base')

    def test_empty(self):
        self.check('empty')

    def test_error_frame(self):
        self.check('error_frame')

    def test_excess_positionals(self):
        self.check('excess_positionals')

    def test_invalid_base_before_source_type(self):
        self.check('invalid_base_before_source_type')

    def test_invalid_bytes(self):
        self.check('invalid_bytes')

    def test_invalid_digit(self):
        self.check('invalid_digit')

    def test_leading_underscore(self):
        self.check('leading_underscore')

    def test_leading_zero_auto(self):
        self.check('leading_zero_auto')

    def test_multi_source_map(self):
        self.check('multi_source_map')

    def test_one_argument_unchanged(self):
        self.check('one_argument_unchanged')

    def test_positional_only_text(self):
        self.check('positional_only_text')

    def test_prefixes(self):
        self.check('prefixes')

    def test_saved_identity(self):
        self.check('saved_identity')

    def test_trailing_underscore(self):
        self.check('trailing_underscore')

    def test_unicode_ascii_only_letters(self):
        self.check('unicode_ascii_only_letters')

    def test_unicode_digits(self):
        self.check('unicode_digits')

    def test_unicode_prefixes(self):
        self.check('unicode_prefixes')

    def test_unicode_whitespace(self):
        self.check('unicode_whitespace')

    def test_union_payloads(self):
        self.check('union_payloads')

    def test_whitespace_separator(self):
        self.check('whitespace_separator')

    def test_wrong_base_float(self):
        self.check('wrong_base_float')

    def test_wrong_base_none(self):
        self.check('wrong_base_none')

    def test_wrong_base_text(self):
        self.check('wrong_base_text')

    def test_wrong_string_float(self):
        self.check('wrong_string_float')

    def test_wrong_string_integer(self):
        self.check('wrong_string_integer')

    def test_wrong_string_none(self):
        self.check('wrong_string_none')


class IntegerBaseWidthTests(unittest.TestCase):
    setUpClass=classmethod(width_execution.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass=classmethod(width_execution.NativeIteratorReductionTests.tearDownClass.__func__)
    compile=width_execution.NativeIteratorReductionTests.compile
    compare=width_execution.NativeIteratorReductionTests.compare

    def test_result_normalization_after_long_integral_text(self):
        values=[('1'+'0'*16,16),('-8000000000000000',16),('z'*800,36),('1'+'0'*128,2)]
        source='for text,base in '+repr(values)+':\n print(int(text,base))\n'
        for mode in ('i64','i128','bigint'):
            for optimized in (False,True):
                self.compare(self.compile(source,mode,optimized),mode=mode,wrapping=True)

    def test_base_literals_normalize_before_conversion(self):
        for bits,mode in ((64,'i64'),(128,'i128')):
            source='print(int("ff",'+str((1<<bits)+16)+'))\n'
            for optimized in (False,True):
                self.compare(self.compile(source,mode,optimized),mode=mode,wrapping=True)
