"""Exact boolean singleton identity on typed native comparison paths."""
import ast
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile

CASES={'boolean_pairs': ('for first in (False,True):\n'
                   ' for second in (False,True):\n'
                   '  print(first is second,first is not second,first==second)\n',
                   ('',),
                   ('i64', 'i128', 'bigint')),
 'literal_sides': ('flag=int(input())>0\n'
                   'print(flag is True,True is flag,flag is False,False is flag)\n'
                   'print(flag is not True,True is not flag,flag is not False,False is not flag)\n',
                   ('0\n', '1\n', '-7\n'),
                   ('i64', 'i128', 'bigint')),
 'integer_distinction': ('number=int(input())\n'
                         'print(number is True,True is number,number is False,False is number)\n'
                         'print(number is not True,number==True,number is not False,number==False)\n',
                         ('0\n', '1\n', '9\n'),
                         ('i64', 'i128', 'bigint')),
 'integer_boolean_flow': ('for toggle in (False,True):\n'
                          ' value=True if toggle else 1\n'
                          ' print(value is True,True is value,value is not True,value==True)\n'
                          ' value=False if toggle else 0\n'
                          ' print(value is False,False is value,value is not False,value==False)\n',
                          ('',),
                          ('i64', 'i128', 'bigint')),
 'aliases_and_rebinding': ('original=True\n'
                           'alias=original\n'
                           'print(alias is original,alias is not False)\n'
                           'original=1\n'
                           'print(alias is original,original is True,alias is True)\n'
                           'original=False\n'
                           'print(alias is original,False is original)\n',
                           ('',),
                           ('i64', 'i128', 'bigint')),
 'nullable_boolean': ('value=True if input()=="yes" else None\n'
                      'print(value is True,True is value,value is False,value is None)\n',
                      ('yes\n', 'no\n'),
                      ('i64', 'i128', 'bigint')),
 'chain_middle_once': ('def seen(label,value):\n'
                       ' print(label,end="|")\n'
                       ' return value\n'
                       'print(seen("left",True) is seen("middle",True) is seen("right",True))\n'
                       'print(seen("first",False) is seen("second",True) is seen("skipped",True))\n',
                       ('',),
                       ('i64', 'i128', 'bigint')),
 'mixed_chain_operators': ('def seen(label,value):\n'
                           ' print(label,end="|")\n'
                           ' return value\n'
                           'print(seen("a",True)==seen("b",True) is seen("c",True))\n'
                           'print(seen("d",True) is seen("e",True)==seen("f",1))\n'
                           'print(seen("g",False) is seen("h",True)<seen("skipped",True))\n',
                           ('',),
                           ('i64', 'i128', 'bigint')),
 'chain_skips_error': ('flag=int(input())>0\nprint(False is flag is (1//0))\n',
                       ('0\n', '1\n'),
                       ('i64', 'i128', 'bigint')),
 'disjoint_still_evaluates': ('denominator=int(input())\nprint(True is (1//denominator))\n',
                              ('0\n', '1\n'),
                              ('i64', 'i128', 'bigint')),
 'framed_boolean_and_int': ('class Compare:\n'
                            ' def run(self,value):return value is True,True is value,value is False,False is '
                            'value\n'
                            'for value in (0,False,1,True,2):print(Compare().run(value))\n',
                            ('',),
                            ('i64', 'i128', 'bigint')),
 'source_boolean_results': ('def enabled(number):return bool(number)\n'
                            'for number in (-1,0,1):\n'
                            ' print(enabled(number) is True,False is enabled(number))\n',
                            ('',),
                            ('i64', 'i128', 'bigint')),
 'list_boolean_elements': ('flags=[True,False]\n'
                           'print(flags[0] is True,False is flags[1],flags[0] is not flags[1])\n',
                           ('',),
                           ('i64', 'i128', 'bigint')),
 'chained_input_boolean': ('def flag(label):\n'
                           ' print(label,end="|")\n'
                           ' return int(input())>0\n'
                           'print(flag("one") is True is flag("two"))\n',
                           ('0\n', '1\n1\n', '1\n0\n'),
                           ('i64', 'i128', 'bigint')),
 'counter_short_circuit': ('count=0\n'
                           'def select(value):\n'
                           ' global count\n'
                           ' count+=1\n'
                           ' return value\n'
                           'print(select(True) is select(True) is select(False),count)\n'
                           'count=0\n'
                           'print(select(False) is select(True) is select(True),count)\n',
                           ('',),
                           ('i64', 'i128', 'bigint'))}

BOUNDARIES={'general_integer_identity': ('first=int(input())\nsecond=int(input())\nprint(first is second)\n',
                              'identity'),
 'general_int_bool_identity': ('first=True if input()=="bool" else int(input())\n'
                               'second=True if input()=="bool" else int(input())\n'
                               'print(first is second)\n',
                               'identity'),
 'walrus_boolean_capture': ('flag=True\n'
                            'print(flag is (flag:=False),flag)\n'
                            'print((flag:=True) is flag,flag)\n',
                            ':='),
 'walrus_tagged_capture': ('for turn in (False,True):\n'
                           ' value=True if turn else 1\n'
                           ' print(value is (value:=True),value)\n',
                           ':=')}

class BooleanIdentityProofTests(unittest.TestCase):
    def test_general_integer_identity_remains_positioned(self):
        for name,(source,reason)in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,filename='original.py',license='none'))
                self.assertFalse(result.success,(name,result.diagnostics))
                diagnostic=result.diagnostics[0]
                self.assertEqual((diagnostic.code,diagnostic.filename),('E006','original.py'))
                self.assertGreater(diagnostic.line,0)
                self.assertIn(reason,diagnostic.message)

    def test_exact_bool_loop_stays_on_ordinary_native_path(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_frame_selection import select_frames
        source='total=0\nfor i in range(int(input())):\n flag=i%2==0\n if flag is True:total+=1\nprint(total)\n'
        unit=build_program(source,'original.py').main
        for integer in ('i64','i128','bigint'):
            self.assertFalse(select_frames(unit,integer=integer).required)
            result=transpile(source,TranspileOptions(integer=integer,filename='original.py',license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            self.assertNotIn('ClassScope',result.rust_source)
            self.assertNotIn('enum Value',result.rust_source)

    def test_original_ast_and_scope_nodes_are_retained(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_linked_frames import generate_linked
        program=build_program(CASES['framed_boolean_and_int'][0],'main.py')
        tree=program.main.tree
        before=ast.dump(tree,include_attributes=True)
        nodes=tuple(ast.walk(tree))
        self.assertIsNotNone(generate_linked(program,'i64'))
        self.assertEqual(ast.dump(tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(tree)),nodes)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class BooleanIdentityExecutionTests(unittest.TestCase):
    def check(self,name):
        source,inputs,modes=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-bool-identity-')as directory:
            root=Path(directory)
            program=root/'main.py';program.write_text(source)
            expected=[subprocess.run([sys.executable,'-I','-S','-B',str(program)],input=data,text=True,capture_output=True,timeout=20)for data in inputs]
            for integer in modes:
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('Forbidden VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=str(program),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                self.assertNotIn('enum Value',result.rust_source)
                rust=root/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in(False,True):
                    binary=root/(integer+str(optimized))
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(name=name,integer=integer,optimized=optimized,stdin=data):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=20)
                            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                            if reference.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1:],reference.stderr.splitlines()[-1:])
                                frames=lambda text:re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',text)
                                self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                            else:self.assertEqual(actual.stderr,'')

    def test_boolean_pairs(self):
        self.check('boolean_pairs')

    def test_literal_sides(self):
        self.check('literal_sides')

    def test_integer_distinction(self):
        self.check('integer_distinction')

    def test_integer_boolean_flow(self):
        self.check('integer_boolean_flow')

    def test_aliases_and_rebinding(self):
        self.check('aliases_and_rebinding')

    def test_nullable_boolean(self):
        self.check('nullable_boolean')

    def test_chain_middle_once(self):
        self.check('chain_middle_once')

    def test_mixed_chain_operators(self):
        self.check('mixed_chain_operators')

    def test_chain_skips_error(self):
        self.check('chain_skips_error')

    def test_disjoint_still_evaluates(self):
        self.check('disjoint_still_evaluates')

    def test_framed_boolean_and_int(self):
        self.check('framed_boolean_and_int')

    def test_source_boolean_results(self):
        self.check('source_boolean_results')

    def test_list_boolean_elements(self):
        self.check('list_boolean_elements')

    def test_chained_input_boolean(self):
        self.check('chained_input_boolean')

    def test_counter_short_circuit(self):
        self.check('counter_short_circuit')



if __name__=='__main__':unittest.main()
