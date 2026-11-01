"""Captured character/radix builtins retain Python values, errors and effects."""
import ast
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import try_generate_classes
import test_native_class_iterators as execution
import test_native_union_ordering as scalar_execution

CASES = {'ascii_unicode_literal_ordinal': 'print(ord("猫"),ord("😀"))\n',
 'callee_before_effects': 'def replacement(value):return 99\n'
                          'def change():\n'
                          ' global ord\n'
                          ' ord=replacement\n'
                          ' print("changed")\n'
                          ' return "a"\n'
                          'print(ord(change()),ord("a"))\n',
 'empty_byte_capture_index': 'class Box:\n def run(self):return b""[0]\nprint(Box().run())\n',
 'empty_byte_capture_lengths': 'class Box:\n'
                               ' def run(self):\n'
                               '  a=b""\n'
                               '  print(len(a),len(b""),bool(b""))\n'
                               'Box().run()\n',
 'error_frames': 'def point(value):return ord(value)\nprint(point("abc"))\n',
 'ord_alias_and_arguments': 'def apply(operation,value):return operation(value)\n'
                            'from builtins import ord as point\n'
                            'print(apply(point,"x"),apply(ord,b"\\xff"))\n',
 'ord_class_field': 'class Convert:\n'
                    ' def __init__(self):self.operation=ord\n'
                    ' def call(self,value):return self.operation(value)\n'
                    'print(Convert().call("a"))\n',
 'ord_empty_bytes': 'print(ord(b""))\n',
 'ord_empty_text': 'print(ord(""))\n',
 'ord_excess': 'def mark(x):print(x);return x\nord(mark("a"),mark("b"))\n',
 'ord_keyword': 'def mark(x):print(x);return x\nord(value=mark("a"))\n',
 'ord_map_and_keys': 'print(list(map(ord,"cab")))\n'
                     'print(sorted(["b","a","c"],key=ord),max(["b","a"],key=ord))\n',
 'ord_missing': 'ord()\n',
 'ord_multiple_bytes': 'print(ord(b"abc"))\n',
 'ord_multiple_text': 'print(ord("ab"))\n',
 'ord_text_bytes': 'print(ord("a"),ord("Z"),ord("\\0"),ord(b"A"),ord(b"\\xff"))\n',
 'ord_union': 'def point(value):return ord(value)\nprint(point("a"),point(b"B"))\nprint(point(None))\n',
 'ord_wrong_integer': 'print(ord(65))\n',
 'ord_wrong_list': 'print(ord([65]))\n',
 'ord_wrong_none': 'print(ord(None))\n',
 'radices': 'for value in [0,1,-1,7,-8,16,-255,True,False]:\n print(bin(value),oct(value),hex(value))\n',
 'radix_alias_rebind': 'original=bin\nbin=7\nprint(original(13),bin)\n',
 'radix_captured_functions': 'def apply(operation,value):return operation(value)\n'
                             'print(apply(bin,19),apply(oct,-19),apply(hex,255))\n',
 'radix_class_field': 'class Convert:\n'
                      ' def __init__(self):self.operation=hex\n'
                      ' def call(self,value):return self.operation(value)\n'
                      'print(Convert().call(-255))\n',
 'radix_excess': 'def mark(x):print(x);return x\noct(mark(1),mark(2))\n',
 'radix_float': 'print(bin(1.5))\n',
 'radix_keyword': 'def mark(x):print(x);return x\nhex(number=mark(31))\n',
 'radix_map': 'print(list(map(bin,range(-3,4))))\n',
 'radix_missing': 'bin()\n',
 'radix_none': 'print(oct(None))\n',
 'radix_seeded_integrals': 'for value in [-2932561464197610469, -3509812195600721033, '
                           '-3811053989198964046, 455379010920926971, -2300738155700008242, '
                           '3623235584041853538, 4400396196818510566, -2097300145916197752, '
                           '1910424341147312202, 4459679175950702528, -2706286018556657929, '
                           '-4485802582140766052, -1172309395317665303, -53291276218445179, '
                           '1057850110783413391, -1725398855006551467, -203449595346111668, '
                           '878924733451422168, -22396685321335074, 2923190346357265828, '
                           '-3725636127063502020, -3479068754382583915, 3583033583359787182, '
                           '1553037377233436204, 4369737130317083572, -1210158898240663612, '
                           '-2621489753083979522, 4377354199596367974, -742523835422535533, '
                           '3960903058167401092, -3934481780823340697, 715900996781819076, '
                           '-3526440608396090363, -1237222654015706228, 984565346102852539, '
                           '-4345361756507116874, 916389222723375207, 4058077736323682174, '
                           '-1506946014752112049, -3969792938932964702, -985037076917052773, '
                           '-2299139078785987645, -2462502621443127515, -3960487069097933659, '
                           '-3120519859088152234, 4275503203909323515, 784119404325002508, '
                           '407463010192256299, -2356598770903355687, -4543395613318763558, '
                           '1193402994721564909, -3749854792021360557, 3874966318062070190, '
                           '4365401738597746598, 189930028128268302, 3874262851794725736, '
                           '4420484523829528294, -1752371363502365319, -3362551018076159564, '
                           '-3899214167455488967, -905925415621296470, -3933669076827728253, '
                           '-4016869261412662670, 4016831556470133194, -1897573687007143484, '
                           '1918309861758928178, -2346585759273844379, -2555977426856917837, '
                           '-421685793057157100, 1121474936168555521, -1263666557688492323, '
                           '-3934633076685602725, 4388922935638744748, 2069232755729636090, '
                           '-3909458160408911482, 551934433787893133, -4187398601365985788, '
                           '-3968993500987559338, 1044481523142329826, -3946127626654068718]:\n'
                           ' print(bin(value),oct(value),hex(value))\n',
 'radix_signed_min64': 'for value in [-9223372036854775808,9223372036854775807]:\n'
                       ' print(bin(value),oct(value),hex(value))\n',
 'radix_text': 'print(hex("ff"))\n',
 'radix_union': 'def display(value):return hex(value)\n'
                'print(display(31),display(True))\n'
                'print(display(None))\n',
 'unicode_ord': 'print(ord("猫"),ord("😀"),ord("é"))\n',
 'unicode_ord_filter_key': 'print(sorted("猫é😀",key=ord),max("猫é😀",key=ord))\n',
 'unicode_ord_mapped_cursor': 'print(list(map(ord,"猫🐈é")))\n',
 'unicode_ord_multiple_text': 'print(ord("猫😀é"))\n'}

class CharacterBuiltinCapabilityTests(unittest.TestCase):
    def test_source_ast_remains_original(self):
        source="point=ord\nprint(point('x'),hex(31))\n"
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(try_generate_classes(source,'main.py','i64',unit=unit))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_user_index_protocol_has_a_precise_diagnostic(self):
        source="class Number:\n def __index__(self):return 15\nprint(hex(Number()))\n"
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('__index__',result.diagnostics[0].message)

    def test_character_codes_and_radices_need_no_unicode_tables(self):
        for string_mode in ('ascii','unicode'):
            result=transpile("print(ord('猫'),hex(-255))\n",TranspileOptions(string_mode=string_mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('UNICODE LICENSE V3',result.rust_source)


class CharacterBuiltinExecutionTests(unittest.TestCase):
    cases=CASES
    check=execution.IteratorExecutionTests.check

    def test_ascii_unicode_literal_ordinal(self):
        self.check('ascii_unicode_literal_ordinal')

    def test_callee_before_effects(self):
        self.check('callee_before_effects')

    def test_empty_byte_capture_index(self):
        self.check('empty_byte_capture_index')

    def test_empty_byte_capture_lengths(self):
        self.check('empty_byte_capture_lengths')

    def test_error_frames(self):
        self.check('error_frames')

    def test_ord_alias_and_arguments(self):
        self.check('ord_alias_and_arguments')

    def test_ord_class_field(self):
        self.check('ord_class_field')

    def test_ord_empty_bytes(self):
        self.check('ord_empty_bytes')

    def test_ord_empty_text(self):
        self.check('ord_empty_text')

    def test_ord_excess(self):
        self.check('ord_excess')

    def test_ord_keyword(self):
        self.check('ord_keyword')

    def test_ord_map_and_keys(self):
        self.check('ord_map_and_keys')

    def test_ord_missing(self):
        self.check('ord_missing')

    def test_ord_multiple_bytes(self):
        self.check('ord_multiple_bytes')

    def test_ord_multiple_text(self):
        self.check('ord_multiple_text')

    def test_ord_text_bytes(self):
        self.check('ord_text_bytes')

    def test_ord_union(self):
        self.check('ord_union')

    def test_ord_wrong_integer(self):
        self.check('ord_wrong_integer')

    def test_ord_wrong_list(self):
        self.check('ord_wrong_list')

    def test_ord_wrong_none(self):
        self.check('ord_wrong_none')

    def test_radices(self):
        self.check('radices')

    def test_radix_alias_rebind(self):
        self.check('radix_alias_rebind')

    def test_radix_captured_functions(self):
        self.check('radix_captured_functions')

    def test_radix_class_field(self):
        self.check('radix_class_field')

    def test_radix_excess(self):
        self.check('radix_excess')

    def test_radix_float(self):
        self.check('radix_float')

    def test_radix_keyword(self):
        self.check('radix_keyword')

    def test_radix_map(self):
        self.check('radix_map')

    def test_radix_missing(self):
        self.check('radix_missing')

    def test_radix_none(self):
        self.check('radix_none')

    def test_radix_seeded_integrals(self):
        self.check('radix_seeded_integrals')

    def test_radix_signed_min64(self):
        self.check('radix_signed_min64')

    def test_radix_text(self):
        self.check('radix_text')

    def test_radix_union(self):
        self.check('radix_union')

    def test_unicode_ord(self):
        self.check('unicode_ord')

    def test_unicode_ord_filter_key(self):
        self.check('unicode_ord_filter_key')

    def test_unicode_ord_mapped_cursor(self):
        self.check('unicode_ord_mapped_cursor')

    def test_unicode_ord_multiple_text(self):
        self.check('unicode_ord_multiple_text')


class RadixWidthExecutionTests(unittest.TestCase):
    setUpClass=classmethod(scalar_execution.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(scalar_execution.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=scalar_execution.NativeUnionOrderingTests.compile
    exercise=scalar_execution.NativeUnionOrderingTests.exercise
    def test_signed_minimum_and_large_magnitudes(self):
        for mode,bits in (('i64',64),('i128',128),('bigint',300)):
            values=[-(1<<(bits-1)),(1<<(bits-1))-1]
            self.exercise('for value in '+repr(values)+':\n print(bin(value),oct(value),hex(value))\n',('',),modes=(mode,))
