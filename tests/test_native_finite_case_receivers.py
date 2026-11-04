"""Finite builtin case methods retain lookup, receiver and error semantics."""
import ast
import re
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze,MethodValue
from py2fastrust.native_ascii_text_case import requires_frames
from py2fastrust.native_text_receiver_facts import builtin_text_receiver_kinds
import test_native_iterator_reductions as _execution

SOURCES={'bool_int_text': ['flag=int(input())\n'
                   'value=True if flag==0 else (7 if flag==1 else "ab")\n'
                   'print(value.upper())\n',
                   ['0\n', '1\n', '2\n']],
 'bytes_bool_lower': ['value=b"AB"if int(input())else False\nprint(value.lower())\n',
                      ['0\n', '1\n']],
 'bytes_none_float': ['key=input()\n'
                      'value=b"\\xffaZ" if key=="b" else (None if key=="n" else 1.5)\n'
                      'print(value.lower())\n',
                      ['b\n', 'n\n', 'f\n']],
 'bytes_nullable_float': ['flag=int(input())\n'
                          'value=b"MiX\\xff"if flag==0 else(None if flag==1 else 1.5)\n'
                          'print(value.lower())\n',
                          ['0\n', '1\n', '2\n']],
 'enumerated_records_main': ['def main():\n'
                             ' rows=[[2,"beta"],[1,"alpha"]]\n'
                             ' for i,(number,label)in '
                             'enumerate(rows):print(i,number+1,label.upper())\n'
                             '\n'
                             'if __name__=="__main__":main()\n',
                             ['']],
 'enumerated_records_module': ['rows=[[2,"beta"],[1,"alpha"]]\n'
                               'for i,(number,label)in '
                               'enumerate(rows):print(i,number+1,label.upper())\n',
                               ['']],
 'factory_parameter_int_text': ['def choose(flag):\n'
                                ' return "Ab" if flag else 17\n'
                                'def run(value):\n'
                                ' print("entered")\n'
                                ' print(value.lower())\n'
                                'run(choose(int(input())))\n',
                                ['0\n', '1\n']],
 'loop_mixed_builtin_receiver': ['values=["ab",3]\nfor value in values:print(value.upper())\n',
                                 ['']],
 'mixed_argument_effect_boundary': ['def effect():\n'
                                    ' print("argument")\n'
                                    ' return 1\n'
                                    'value="x" if int(input()) else 9\n'
                                    'value.upper(effect())\n',
                                    ['0\n', '1\n']],
 'mixed_argument_lookup_boundary': ['def mark():\n'
                                    ' print("argument")\n'
                                    ' return 3\n'
                                    'value="AB"if int(input())else 7\n'
                                    'print(value.lower(mark()))\n',
                                    ['0\n', '1\n']],
 'mixed_keyword_lookup_boundary': ['def mark():\n'
                                   ' print("keyword")\n'
                                   ' return 3\n'
                                   'value="AB"if int(input())else 7\n'
                                   'print(value.upper(key=mark()))\n',
                                   ['0\n', '1\n']],
 'mixed_star_lookup_boundary': ['def arguments():\n'
                                ' print("star")\n'
                                ' return ()\n'
                                'value="ab"if int(input())else 7\n'
                                'print(value.upper(*arguments()))\n',
                                ['0\n', '1\n']],
 'nested_record_unpack_main': ['def main():\n'
                               ' record=[1,[2,"nested"]]\n'
                               ' first,(second,label)=record\n'
                               ' print(first+second,label.upper())\n'
                               '\n'
                               'if __name__=="__main__":main()\n',
                               ['']],
 'nested_record_unpack_module': ['record=[1,[2,"nested"]]\n'
                                 'first,(second,label)=record\n'
                                 'print(first+second,label.upper())\n',
                                 ['']],
 'receiver_evaluated_once': ['calls=0\n'
                             'def receiver(flag):\n'
                             ' global calls\n'
                             ' calls+=1\n'
                             ' print("receiver",calls)\n'
                             ' return "aB" if flag else None\n'
                             'print(receiver(int(input())).upper())\n',
                             ['0\n', '1\n']],
 'record_factory_main': ['def main():\n'
                         ' def make(number):return [number,str(number)]\n'
                         ' number,label=make(5)\n'
                         ' print(number+1,label.upper())\n'
                         '\n'
                         'if __name__=="__main__":main()\n',
                         ['']],
 'record_factory_module': ['def make(number):return [number,str(number)]\n'
                           'number,label=make(5)\n'
                           'print(number+1,label.upper())\n',
                           ['']],
 'record_parameter_main': ['def main():\n'
                           ' def show(record):\n'
                           '  number,label=record\n'
                           '  print(number*2,label.upper())\n'
                           ' show([3,"parameter"])\n'
                           '\n'
                           'if __name__=="__main__":main()\n',
                           ['']],
 'record_parameter_module': ['def show(record):\n'
                             ' number,label=record\n'
                             ' print(number*2,label.upper())\n'
                             'show([3,"parameter"])\n',
                             ['']],
 'sorted_record_copy_main': ['def main():\n'
                             ' rows=[[2,"beta"],[1,"alpha"]]\n'
                             ' ordered=sorted(rows,key=lambda row:row[0])\n'
                             ' for number,label in ordered:print(number+1,label.upper())\n'
                             '\n'
                             'if __name__=="__main__":main()\n',
                             ['']],
 'sorted_record_copy_module': ['rows=[[2,"beta"],[1,"alpha"]]\n'
                               'ordered=sorted(rows,key=lambda row:row[0])\n'
                               'for number,label in ordered:print(number+1,label.upper())\n',
                               ['']],
 'source_class_same_name': ['class Reader:\n'
                            ' def upper(self):return "source upper"\n'
                            ' def lower(self):return "source lower"\n'
                            'value=Reader()\n'
                            'print(value.upper(),value.lower())\n',
                            ['']],
 'source_class_text_mix_excluded': ['class Reader:\n'
                                    ' def upper(self):return "source upper"\n'
                                    'value=Reader()if int(input())else "text"\n'
                                    'print(value.upper())\n',
                                    ['0\n', '1\n']],
 'str_float_upper': ['value="xy"if int(input())else 1.5\nprint(value.upper())\n', ['0\n', '1\n']],
 'str_int_upper': ['value="alpha"if int(input())else 7\nprint("before")\nprint(value.upper())\n',
                   ['0\n', '1\n']],
 'str_none_lower': ['value="MiXeD"if int(input())else None\nprint(value.lower())\n',
                    ['0\n', '1\n']],
 'str_nullable_unicode': ['value="Straße"if int(input())else None\nprint(value.upper())\n',
                          ['0\n', '1\n']],
 'text_only_invalid_signature': ['def mark():\n'
                                 ' print("argument")\n'
                                 ' return 3\n'
                                 'value="AB"if int(input())else b"CD"\n'
                                 'print(value.lower(mark()))\n',
                                 ['0\n', '1\n']]}


class FiniteCaseSelectionTests(unittest.TestCase):
    def test_closed_builtin_mixed_calls_select_before_emission_without_ast_changes(self):
        for name in ('str_int_upper','bytes_bool_lower','str_none_lower','str_float_upper'):
            source=SOURCES[name][0];unit=build_program(source,'mixed.py').main
            before=ast.dump(unit.tree,include_attributes=True)
            self.assertTrue(requires_frames(unit,analyze(unit)),name)
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
            unit.check_identity(source,'mixed.py')

    def test_other_text_adapters_do_not_gain_mixed_receiver_domains(self):
        source=SOURCES['str_int_upper'][0];unit=build_program(source,'mixed.py').main
        analysis=analyze(unit);nodes={unit.ordinal(n):n for n in ast.walk(unit.tree)}
        found=False
        for facts in analysis.scopes.values():
            for site,fact in facts.calls.items():
                for identity in fact.identity.alternatives:
                    if isinstance(identity,MethodValue)and identity.name=='upper':
                        found=True
                        self.assertFalse(builtin_text_receiver_kinds(unit,facts,nodes[site],identity))
        self.assertTrue(found)

    def test_explicit_mixed_calls_select_typed_validation_before_emission(self):
        for name in ('mixed_argument_lookup_boundary','mixed_keyword_lookup_boundary'):
            source=SOURCES[name][0];unit=build_program(source,'boundary.py').main
            self.assertTrue(requires_frames(unit,analyze(unit)),name)

    def test_custom_receiver_domains_do_not_select_mixed_adapter(self):
        source=SOURCES['source_class_text_mix_excluded'][0]
        unit=build_program(source,'boundary.py').main
        self.assertFalse(requires_frames(unit,analyze(unit)))

    def test_mixed_explicit_calls_and_custom_receivers_remain_positioned_diagnostics(self):
        for name in ('mixed_argument_lookup_boundary','mixed_keyword_lookup_boundary',
                     'mixed_star_lookup_boundary','source_class_text_mix_excluded'):
            result=transpile(SOURCES[name][0],TranspileOptions(filename='boundary.py'))
            self.assertFalse(result.success,name)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertEqual(result.diagnostics[0].filename,'boundary.py')
            self.assertGreater(result.diagnostics[0].line,0)

    def test_explicit_mixed_calls_name_the_missing_pre_argument_lookup(self):
        for name in ('mixed_argument_lookup_boundary','mixed_keyword_lookup_boundary'):
            result=transpile(SOURCES[name][0],TranspileOptions(filename='boundary.py'))
            self.assertFalse(result.success)
            self.assertIn('attribute lookup before argument effects',result.diagnostics[0].message)
            self.assertIn('zero-argument mixed builtin calls',result.diagnostics[0].message)

    def test_unicode_string_mixed_receiver_keeps_explicit_casing_gap(self):
        result=transpile(SOURCES['str_nullable_unicode'][0],TranspileOptions(string_mode='unicode'))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('str.upper()',result.diagnostics[0].message)
        self.assertIn('case-mapping',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FiniteCaseExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=_execution.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def check(self,name,*,string_mode='ascii',debug=False):
        source,inputs=SOURCES[name]
        for mode in ('i64','i128','bigint'):
            for release in ((False,True)if debug else(True,)):
                compiled=self.harness.compile(source,mode,release=release,string_mode=string_mode)
                for data in inputs:
                    with self.subTest(name=name,mode=mode,release=release,data=data):
                        actual=subprocess.run([str(compiled[1])],input=data,capture_output=True,text=True,timeout=10)
                        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=10)
                        self.assertEqual(actual.stdout,expected.stdout)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                        final=lambda s:s.rstrip().splitlines()[-1]if s.strip()else''
                        self.assertEqual(final(actual.stderr),final(expected.stderr))
                        frames=lambda s:re.findall(r'File "[^"\n]+", line (\d+), in ([^\n]+)',s)
                        self.assertEqual(frames(actual.stderr),frames(expected.stderr))

    def test_original_factory_module_and_main_records(self):
        self.check('record_factory_module');self.check('record_factory_main')

    def test_original_parameter_module_and_main_records(self):
        self.check('record_parameter_module');self.check('record_parameter_main')

    def test_original_nested_and_enumerated_records(self):
        self.check('nested_record_unpack_module');self.check('enumerated_records_module')

    def test_original_sorted_copy_records(self):
        self.check('sorted_record_copy_module')

    def test_str_int_receiver_branches(self):self.check('str_int_upper',debug=True)

    def test_runtime_int_bool_error_names(self):self.check('bool_int_text',debug=True)

    def test_bytes_none_float_receiver_branches(self):self.check('bytes_none_float',debug=True)

    def test_receiver_evaluated_once_before_lookup(self):self.check('receiver_evaluated_once',debug=True)

    def test_iteration_stops_at_first_invalid_builtin_receiver(self):self.check('loop_mixed_builtin_receiver')

    def test_text_only_invalid_signature_retains_argument_effects(self):self.check('text_only_invalid_signature')

    def test_same_named_source_class_methods_keep_dispatch(self):self.check('source_class_same_name')

    def test_bytes_mixed_domain_works_in_unicode_mode(self):self.check('bytes_nullable_float',string_mode='unicode',debug=True)


if __name__=='__main__':unittest.main()
