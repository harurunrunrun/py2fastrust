"""Builtin predicate signatures, pinned Unicode properties and direct execution."""
import ast
from dataclasses import dataclass,replace
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.call_semantics import CallBindingError
from py2fastrust.frontend import build_program
from py2fastrust.native import _Expression
from py2fastrust.native_constraints import analyze
from py2fastrust.native_range_facts import derive_regions
from py2fastrust.native_stream_plans import Normalizer
from py2fastrust.native_text_predicates import STR_PREDICATES,BYTES_PREDICATES,render_helpers,supports
import test_native_iterator_reductions as _execution

NAMES=tuple(sorted(STR_PREDICATES))
BYTE_NAMES=tuple(sorted(BYTES_PREDICATES))


class PredicatePlanTests(unittest.TestCase):
    def test_api_families_match_the_actual_builtin_types(self):
        for name in NAMES:
            self.assertTrue(hasattr(str,name))
            self.assertEqual(name in BYTES_PREDICATES,hasattr(bytes,name))
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag='opaque_string_override'
        self.assertFalse(supports(Opaque(),'isupper'))

    def test_shared_method_plan_reads_receiver_once_before_binding_arguments(self):
        class Generator:
            function=None
            source_unit=None
            global_environment={}
            global_names=frozenset()
            entry_scope=None
            def __init__(self):self.reads=[]
            def read_expression(self,node,environment):
                self.reads.append(node)
                return _Expression('receiver_once()','str',owned=False,char_code='65_u32')
            def expression(self,*_):raise AssertionError('predicate used materializing receiver entry')
        g=Generator();node=ast.parse('receiver().isupper()',mode='eval').body
        normalizer=Normalizer(g,{})
        plan=normalizer.method(node,names=STR_PREDICATES)
        self.assertEqual(len(g.reads),1)
        self.assertIs(normalizer.method(node,names=STR_PREDICATES),plan)
        self.assertEqual(plan.identity.owner,'str')
        self.assertEqual(plan.identity.name,'isupper')
        self.assertEqual(plan.invocation.explicit_order,())
        self.assertEqual(plan.receiver.captured.char_code,'65_u32')
        for expression in ('receiver().isupper(1)','receiver().isupper(value=1)'):
            with self.assertRaises(CallBindingError):Normalizer(g,{}).method(ast.parse(expression,mode='eval').body,names=STR_PREDICATES)

    def test_scalar_and_unicode_helpers_select_only_needed_data(self):
        ascii=render_helpers({('str','isupper',False)},'ascii')
        self.assertNotIn('NATIVE_PRED_TABLE_',ascii)
        upper=render_helpers({('str','isupper',True)},'unicode')
        self.assertIn('NATIVE_PRED_TABLE_UPPER',upper)
        self.assertNotIn('NATIVE_PRED_TABLE_CASED',upper)
        self.assertNotIn('NATIVE_PRED_TABLE_LOWER',upper)
        full=render_helpers({('str','isupper',False)},'unicode')
        self.assertIn('NATIVE_PRED_TABLE_CASED',full)
        self.assertNotIn('NATIVE_PRED_TABLE_ALPHA',full)
        decimal=render_helpers({('str','isdecimal',False)},'unicode')
        self.assertIn('NATIVE_PRED_TABLE_DECIMAL',decimal)
        self.assertNotIn('NATIVE_PRED_TABLE_DIGIT',decimal)
        title=render_helpers({('str','istitle',False)},'unicode')
        self.assertIn('NATIVE_PRED_TABLE_TITLE',title)
        self.assertNotIn('NATIVE_PRED_TABLE_NUMERIC',title)

    def test_boolean_result_and_effect_summary_require_exact_builtin_receiver(self):
        source='s=input()\nvalues=[]\nfor i in range(len(s)):\n values.append(s[i].isupper())\nprint(values)\n'
        unit=build_program(source,'predicate.py').main;analysis=analyze(unit)
        self.assertTrue(any(kind=='bool' for kind in analysis.scope().expressions.values()))
        source='s=input()\nanswer=sum(s[i].isupper() for i in range(len(s)))\n'
        unit=build_program(source,'predicate.py').main;analysis=analyze(unit)
        facts=derive_regions(analysis,analysis.scope(),64)
        self.assertEqual(len(facts),1)
        self.assertTrue(next(iter(facts.values())).vectorizable_when_guarded)
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag='opaque_predicate_override'
        scope=analysis.scope();kinds=dict(scope.expressions)
        for site,term in analysis.graph.expressions.items():
            if term.operation=='index':kinds[site]=Opaque()
        self.assertEqual(dict(derive_regions(analysis,replace(scope,expressions=kinds),64)),{})

    def test_invalid_signatures_and_missing_bytes_methods_are_positioned(self):
        for source in ('print(0)\nprint("A".isupper(1))\n','print(0)\nprint("A".isupper(x=1))\n',
                       'print(0)\nprint(b"A".isdecimal())\n','print(0)\nprint(b"A".isnumeric())\n','print(0)\nprint(b"A".isidentifier())\n'):
            result=transpile(source,TranspileOptions(filename='bad_predicate.py'))
            self.assertFalse(result.success)
            self.assertIsNone(result.rust_source)
            self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].line,result.diagnostics[0].filename),('E006',2,'bad_predicate.py'))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeTextPredicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=_execution.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def compare(self,source,data=('',),*,string_mode='ascii',debug=False,trace=False,modes=('i64','i128','bigint'),inspect=None):
        for mode in modes:
            for release in ((False,True) if debug else (True,)):
                compiled=self.harness.compile(source,mode,release=release,string_mode=string_mode)
                if inspect:inspect(compiled[2])
                for sample in data:
                    with self.subTest(mode=mode,release=release,data=sample):self.harness.compare(compiled,sample,mode=mode,trace=trace)

    def test_all_string_predicates_ascii_empty_controls_and_words(self):
        calls=','.join('s.'+name+'()'for name in NAMES)
        source='def inspect(s):\n return ('+calls+',)\ns=input()\nprint(inspect(s))\n'
        samples=('','A','a','aA','ABC 123','abc 123','Title Words','A\x00B','_', 'a_2','2x','\t\v\f\x1c')
        self.compare(source,tuple(sample+'\n'for sample in samples),debug=True)

    def test_unicode_properties_titlecase_identifier_and_new16_characters(self):
        calls=','.join('s.'+name+'()'for name in NAMES)
        source='s=input()\nprint(('+calls+',))\n'
        samples=('', 'ǅ','ǅuro','ǅURO','Ǆuro','ǆuro','A\u0301b','A\u0301B','ᾈ','ᾈλφα',
                 '²','½','Ⅻ','四','\u0085','\u2003','\u200b','\x1c','\u2118','\u212e','a\u200c','a\u0301',
                 '\u1c89','\u1c8a','\U00010d50','\U0001e5d0','猫🙂','Straße','Δelta','İ','ı','K')
        self.compare(source,tuple(sample+'\n'for sample in samples),string_mode='unicode',debug=True)

    def test_all_bytes_predicates_ignore_unicode_data(self):
        calls=','.join('value.'+name+'()'for name in BYTE_NAMES)
        source='import sys\nvalue=sys.stdin.buffer.read()\nprint(('+calls+',))\n'
        def no_tables(rust):self.assertNotIn('NATIVE_PRED_TABLE_',rust)
        for mode in ('i64','i128','bigint'):
            compiled=self.harness.compile(source,mode,string_mode='unicode')
            no_tables(compiled[2])
            for sample in (b'',b'ABC',b'abc',b'Abc Def',b'A\xc0B',b'A\xc0b',bytes(range(256)),b'\x1c',b'\t\n\v\f\r ',b'123',b'\xb2'):
                actual=subprocess.run([str(compiled[1])],input=sample,capture_output=True,timeout=5)
                expected=subprocess.run([sys.executable,'-I','-c',source],input=sample,capture_output=True,timeout=5)
                self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)

    def test_generator_functions_and_typed_string_containers(self):
        source='''def count_upper(text):
 return sum(char.isupper() for char in text)
words=["A","lower","Title","ABC123",""]
answer=[]
for word in words:
 answer.append(word.isupper())
print(answer,count_upper(input()))
'''
        self.compare(source,('AaZ 09\n','\n','ABC\n'),debug=True)
        self.compare(source,('ǅΑβ猫\n','\n','𐵐A\n'),string_mode='unicode')

    def test_codepoint_predicates_and_bounds_keep_receiver_effects_once(self):
        source='''def text():
 print("text")
 return input()
def index():
 print("index")
 return int(input())
print(text()[index()].isupper())
'''
        self.compare(source,('Ab\n0\n','Ab\n-1\n','Ab\n2\n','Ab\n','Ab\nbad\n'),debug=True,trace=True)
        self.compare(source,('ǅΑ\n0\n','ǅΑ\n1\n','ǅΑ\n2\n'),string_mode='unicode',trace=True)

    def test_rebinding_and_boolean_aliases_preserve_types(self):
        source='''value=input()
print(value.isupper())
value=7
print(value)
if int(input()):value="ABC"
else:value=b"abc"
print(value.isupper(),value.isascii())
'''
        self.compare(source,('ABC\n0\n','abc\n1\n'),debug=True)

    def test_user_class_override_remains_an_ordinary_integer_method(self):
        source='class C:\n def isupper(self):return 7\nprint(C().isupper())\n'
        self.compare(source,('',))

    def test_isascii_selects_the_physical_metadata_hook_once(self):
        from py2fastrust.native import _Generator
        selected=[]
        def hook(value):
            selected.append(value)
            return f"({value.code}).is_ascii()"
        source='def text():\n print("text")\n return input()\nprint(text().isascii())\n'
        for mode in ('i64','i128','bigint'):
            selected.clear()
            with patch.object(_Generator,'text_is_ascii',staticmethod(hook)):
                compiled=self.harness.compile(source,mode,string_mode='unicode')
            self.assertTrue(selected)
            self.assertTrue(all(value.code.startswith('native_temp_') for value in selected))
            self.assertNotIn('native_str_isascii(',compiled[2])
            for data in ('abc\n','猫\n','\n'):self.harness.compare(compiled,data,mode=mode)

    def test_notices_follow_actual_retained_unicode_tables(self):
        for mode in ('i64','i128','bigint'):
            ascii=transpile('print("A".isupper())\n',TranspileOptions(integer=mode))
            self.assertTrue(ascii.success,ascii.diagnostics)
            self.assertNotIn('NATIVE_PRED_TABLE_',ascii.rust_source)
            unicode=transpile('print("ǅ".istitle())\n',TranspileOptions(integer=mode,string_mode='unicode'))
            self.assertTrue(unicode.success,unicode.diagnostics)
            self.assertIn('NATIVE_PRED_TABLE_TITLE',unicode.rust_source)
            self.assertIn('UNICODE LICENSE V3',unicode.rust_source)
            for pruned in (False,True):
                result=transpile('s=input()\nprint(s.isdecimal())\n',TranspileOptions(integer=mode,string_mode='unicode',optimize=pruned))
                self.assertTrue(result.success,result.diagnostics)
                self.assertIn('NATIVE_PRED_TABLE_DECIMAL',result.rust_source)
                self.assertNotIn('NATIVE_PRED_TABLE_NUMERIC',result.rust_source)
                self.assertNotIn('NATIVE_PRED_TABLE_TITLE',result.rust_source)

    def test_independent_seeded_unicode_strings_match_cpython(self):
        rng=random.Random(274683)
        alphabet=['A','a','0','_',' ','\x1c','ǅ','ǆ','İ','ß','²','½','猫','\u0301','\u2003','\u2118','\u1c89','\U00010d50']
        rows=[''.join(rng.choice(alphabet)for _ in range(rng.randrange(0,18)))for _ in range(90)]
        calls=','.join('s.'+name+'()'for name in NAMES)
        source='n=int(input())\nfor i in range(n):\n s=input()\n print(('+calls+',))\n'
        data=str(len(rows))+'\n'+'\n'.join(rows)+'\n'
        self.compare(source,(data,),string_mode='unicode')


if __name__=='__main__':unittest.main()
