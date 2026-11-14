"""Canonical math predicates preserve numeric conversions and argument effects."""
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

CASES={'ordinary_numbers': ('import math\n'
                      "for value in (False,True,0,-17,3.25,-0.0,float('inf'),-float('inf'),float('nan')):\n"
                      ' print(math.isnan(value),math.isinf(value),math.isfinite(value))\n',
                      ('',),
                      ('i64', 'i128', 'bigint')),
 'framed_numbers': ('import math\n'
                    'class Box:\n'
                    ' def run(self,value):return math.isnan(value),math.isinf(value),math.isfinite(value)\n'
                    'for value in '
                    "(0,1.25,-0.0,float('inf'),-float('inf'),float('nan')):print(Box().run(value))\n",
                    ('',),
                    ('i64', 'i128', 'bigint')),
 'input_scalar': ('from math import isnan,isinf,isfinite\n'
                  'value=float(input())\n'
                  'print(isnan(value),isinf(value),isfinite(value))\n',
                  ('nan\n', 'inf\n', '-inf\n', '-0.0\n', '5e-324\n', '1e308\n'),
                  ('i64', 'i128', 'bigint')),
 'identity_observer': ('import math\n'
                       "shared=float('nan')\n"
                       'values=(shared,shared)\n'
                       'print(values==(shared,shared))\n'
                       "for value in (shared,float('inf'),-0.0,9):\n"
                       ' '
                       'print(math.isnan(value),math.isinf(value),math.isfinite(value),(value,)==(value,))\n',
                       ('',),
                       ('i64', 'i128', 'bigint')),
 'captured_alias': ('import math as numeric\n'
                    'saved=numeric.isnan\n'
                    'numeric.isnan=lambda value:False\n'
                    "print(saved(float('nan')),numeric.isnan(float('nan')))\n",
                    ('',),
                    ('i64', 'i128', 'bigint')),
 'capture_before_argument_mutation': ('import math\n'
                                      'def mutate():\n'
                                      ' math.isnan=lambda value:False\n'
                                      " print('mutate')\n"
                                      " return float('nan')\n"
                                      'print(math.isnan(mutate()))\n'
                                      "print(math.isnan(float('nan')))\n",
                                      ('',),
                                      ('i64', 'i128', 'bigint')),
 'canonical_callbacks': ('from math import isnan,isinf,isfinite\n'
                         'class Apply:\n'
                         ' def run(self,function,value):return function(value)\n'
                         'for function in (isnan,isinf,isfinite):\n'
                         " print(Apply().run(function,float('nan')),Apply().run(function,-0.0))\n",
                         ('',),
                         ('i64', 'i128', 'bigint')),
 'local_import_alias': ('class Box:\n'
                        ' def run(self,value):\n'
                        '  from math import isfinite as finite\n'
                        '  return finite(value)\n'
                        "print(Box().run(17),Box().run(float('inf')))\n",
                        ('',),
                        ('i64', 'i128', 'bigint')),
 'source_method_names': ('class Number:\n'
                         ' def isnan(self,value):return value+7\n'
                         ' def isinf(self,value):return value+8\n'
                         ' def isfinite(self,value):return value+9\n'
                         'number=Number()\n'
                         'print(number.isnan(1),number.isinf(2),number.isfinite(3))\n',
                         ('',),
                         ('i64', 'i128', 'bigint')),
 'closed_valid_union': ('import math\n'
                        'for flag in (False,True):\n'
                        ' value=1.5 if flag else 7\n'
                        ' print(math.isnan(value),math.isinf(value),math.isfinite(value))\n',
                        ('',),
                        ('i64', 'i128', 'bigint')),
 'isnan_empty': ('import math\nmath.isnan()\n', ('',), ('i64', 'i128', 'bigint')),
 'isnan_too_many': ('import math\n'
                    'def value(label):\n'
                    ' print(label)\n'
                    ' return 1\n'
                    "math.isnan(value('first'),value('second'))\n",
                    ('',),
                    ('i64', 'i128', 'bigint')),
 'isnan_keyword': ('import math\n'
                   'def value(label):\n'
                   ' print(label)\n'
                   ' return 1\n'
                   "math.isnan(value('first'),ignored=value('keyword'))\n",
                   ('',),
                   ('i64', 'i128', 'bigint')),
 'isnan_string_error': ("import math\nprint(math.isnan('1.25'))\n", ('',), ('i64', 'i128', 'bigint')),
 'isnan_none_error': ('import math\nprint(math.isnan(None))\n', ('',), ('i64', 'i128', 'bigint')),
 'isnan_huge_checked': ('import math\nprint(math.isnan(int(input())))\n',
                        ('114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n',
                         '-114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n'),
                        ('bigint',)),
 'isinf_empty': ('import math\nmath.isinf()\n', ('',), ('i64', 'i128', 'bigint')),
 'isinf_too_many': ('import math\n'
                    'def value(label):\n'
                    ' print(label)\n'
                    ' return 1\n'
                    "math.isinf(value('first'),value('second'))\n",
                    ('',),
                    ('i64', 'i128', 'bigint')),
 'isinf_keyword': ('import math\n'
                   'def value(label):\n'
                   ' print(label)\n'
                   ' return 1\n'
                   "math.isinf(value('first'),ignored=value('keyword'))\n",
                   ('',),
                   ('i64', 'i128', 'bigint')),
 'isinf_string_error': ("import math\nprint(math.isinf('1.25'))\n", ('',), ('i64', 'i128', 'bigint')),
 'isinf_none_error': ('import math\nprint(math.isinf(None))\n', ('',), ('i64', 'i128', 'bigint')),
 'isinf_huge_checked': ('import math\nprint(math.isinf(int(input())))\n',
                        ('114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n',
                         '-114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n'),
                        ('bigint',)),
 'isfinite_empty': ('import math\nmath.isfinite()\n', ('',), ('i64', 'i128', 'bigint')),
 'isfinite_too_many': ('import math\n'
                       'def value(label):\n'
                       ' print(label)\n'
                       ' return 1\n'
                       "math.isfinite(value('first'),value('second'))\n",
                       ('',),
                       ('i64', 'i128', 'bigint')),
 'isfinite_keyword': ('import math\n'
                      'def value(label):\n'
                      ' print(label)\n'
                      ' return 1\n'
                      "math.isfinite(value('first'),ignored=value('keyword'))\n",
                      ('',),
                      ('i64', 'i128', 'bigint')),
 'isfinite_string_error': ("import math\nprint(math.isfinite('1.25'))\n", ('',), ('i64', 'i128', 'bigint')),
 'isfinite_none_error': ('import math\nprint(math.isfinite(None))\n', ('',), ('i64', 'i128', 'bigint')),
 'isfinite_huge_checked': ('import math\nprint(math.isfinite(int(input())))\n',
                           ('114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n',
                            '-114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n'),
                           ('bigint',)),
 'closed_nullable': ('import math\n'
                     'for flag in (False,True):\n'
                     ' value=3.0 if flag else None\n'
                     ' print(math.isnan(value),math.isinf(value),math.isfinite(value))\n',
                     ('',),
                     ('i64', 'i128', 'bigint')),
 'closed_text': ('import math\n'
                 'for flag in (True,False):\n'
                 ' value=3.0 if flag else "bad"\n'
                 ' print(math.isnan(value),math.isinf(value),math.isfinite(value))\n',
                 ('',),
                 ('i64', 'i128', 'bigint')),
 'list_retained': ('import math\nvalues=[1]\nmath.isfinite(values)\nprint(values)\n', ('',), ('bigint',)),
 'after_error_atexit': ('import atexit\n'
                        'import math\n'
                        'value=3.0 if input()=="float" else "bad"\n'
                        'def after():\n'
                        ' print("after",value)\n'
                        'atexit.register(after)\n'
                        'print(math.isnan(value),math.isinf(value),math.isfinite(value))\n',
                        ('float\n', 'bad\n'),
                        ('i64', 'i128', 'bigint')),
 'shared_wrong_type_atexit': ('import atexit\n'
                              'import math\n'
                              'shared=[1]\n'
                              'value=3.0 if input()=="float" else shared\n'
                              'def after():\n'
                              ' shared.append(2)\n'
                              ' print("after",shared,value)\n'
                              'atexit.register(after)\n'
                              'print(math.isfinite(value))\n',
                              ('float\n', 'bad\n'),
                              ('i64', 'i128', 'bigint'))}

BOUNDARIES={'isnan__float___boundary': ('import math\n'
                             'class Number:\n'
                             ' def __float__(self):\n'
                             '  print("conversion")\n'
                             '  return 2.0\n'
                             'print(math.isnan(Number()))\n',
                             '__float__'),
 'isnan__index___boundary': ('import math\n'
                             'class Number:\n'
                             ' def __index__(self):\n'
                             '  print("conversion")\n'
                             '  return 2\n'
                             'print(math.isnan(Number()))\n',
                             '__index__'),
 'isinf__float___boundary': ('import math\n'
                             'class Number:\n'
                             ' def __float__(self):\n'
                             '  print("conversion")\n'
                             '  return 2.0\n'
                             'print(math.isinf(Number()))\n',
                             '__float__'),
 'isinf__index___boundary': ('import math\n'
                             'class Number:\n'
                             ' def __index__(self):\n'
                             '  print("conversion")\n'
                             '  return 2\n'
                             'print(math.isinf(Number()))\n',
                             '__index__'),
 'isfinite__float___boundary': ('import math\n'
                                'class Number:\n'
                                ' def __float__(self):\n'
                                '  print("conversion")\n'
                                '  return 2.0\n'
                                'print(math.isfinite(Number()))\n',
                                '__float__'),
 'isfinite__index___boundary': ('import math\n'
                                'class Number:\n'
                                ' def __index__(self):\n'
                                '  print("conversion")\n'
                                '  return 2\n'
                                'print(math.isfinite(Number()))\n',
                                '__index__'),
 'isnan_invalid_arity_custom': ('import math\n'
                                'class Number:\n'
                                ' def __float__(self):\n'
                                "  print('conversion')\n"
                                '  return 1.0\n'
                                'math.isnan(Number(),Number())\n',
                                '__float__'),
 'isinf_invalid_arity_custom': ('import math\n'
                                'class Number:\n'
                                ' def __float__(self):\n'
                                "  print('conversion')\n"
                                '  return 1.0\n'
                                'math.isinf(Number(),Number())\n',
                                '__float__'),
 'isfinite_invalid_arity_custom': ('import math\n'
                                   'class Number:\n'
                                   ' def __float__(self):\n'
                                   "  print('conversion')\n"
                                   '  return 1.0\n'
                                   'math.isfinite(Number(),Number())\n',
                                   '__float__')}

class MathPredicateProofTests(unittest.TestCase):
    def test_custom_numeric_protocols_remain_positioned(self):
        for name,(source,protocol)in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode,filename='original.py',license='none'))
                self.assertFalse(result.success,(name,result.diagnostics))
                diagnostic=result.diagnostics[0]
                self.assertEqual((diagnostic.code,diagnostic.filename),('E006','original.py'))
                self.assertGreater(diagnostic.line,0)
                self.assertIn(protocol,diagnostic.message)

    def test_scalar_and_bigint_use_existing_math_selection(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_frame_selection import select_frames
        for name in ('isnan','isinf','isfinite'):
            source='import math\nprint(math.'+name+'(7))\n'
            unit=build_program(source,'main.py').main
            for mode in ('i64','i128'):
                self.assertFalse(select_frames(unit,integer=mode).required)
            self.assertTrue(select_frames(unit,integer='bigint').required)

    def test_original_ast_nodes_are_retained(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_linked_frames import generate_linked
        program=build_program(CASES['framed_numbers'][0],'main.py')
        unit=program.main
        before=ast.dump(unit.tree,include_attributes=True)
        nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(generate_linked(program,'i64'))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)


    def test_raw_list_scalar_conversion_gap_names_the_actual_predicate(self):
        source=CASES['list_retained'][0]
        for mode in ('i64','i128'):
            result=transpile(source,TranspileOptions(integer=mode,filename='original.py',license='none'))
            self.assertFalse(result.success,result.diagnostics)
            diagnostic=result.diagnostics[0]
            self.assertEqual((diagnostic.code,diagnostic.filename),('E006','original.py'))
            self.assertGreater(diagnostic.line,0)
            self.assertIn('math.isfinite',diagnostic.message)
            self.assertNotIn('math.sqrt',diagnostic.message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MathPredicateExecutionTests(unittest.TestCase):
    def check(self,name):
        source,inputs,modes=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-math-predicate-')as directory:
            root=Path(directory)
            program=root/'main.py'
            program.write_text(source)
            expected=[subprocess.run([sys.executable,'-I','-S','-B',str(program)],input=data,text=True,capture_output=True,timeout=20)for data in inputs]
            for mode in modes:
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename=str(program),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                rust=root/(mode+'.rs')
                rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+str(optimized))
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(name=name,integer=mode,optimized=optimized,stdin=data):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=20)
                            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                            if reference.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1:],reference.stderr.splitlines()[-1:])
                                frames=lambda text:re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',text)
                                self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                            else:
                                self.assertEqual(actual.stderr,'')

    def test_ordinary_numbers(self):
        self.check('ordinary_numbers')

    def test_framed_numbers(self):
        self.check('framed_numbers')

    def test_input_scalar(self):
        self.check('input_scalar')

    def test_identity_observer(self):
        self.check('identity_observer')

    def test_captured_alias(self):
        self.check('captured_alias')

    def test_capture_before_argument_mutation(self):
        self.check('capture_before_argument_mutation')

    def test_canonical_callbacks(self):
        self.check('canonical_callbacks')

    def test_local_import_alias(self):
        self.check('local_import_alias')

    def test_source_method_names(self):
        self.check('source_method_names')

    def test_closed_valid_union(self):
        self.check('closed_valid_union')

    def test_isnan_empty(self):
        self.check('isnan_empty')

    def test_isnan_too_many(self):
        self.check('isnan_too_many')

    def test_isnan_keyword(self):
        self.check('isnan_keyword')

    def test_isnan_string_error(self):
        self.check('isnan_string_error')

    def test_isnan_none_error(self):
        self.check('isnan_none_error')

    def test_isnan_huge_checked(self):
        self.check('isnan_huge_checked')


    def test_isinf_empty(self):
        self.check('isinf_empty')

    def test_isinf_too_many(self):
        self.check('isinf_too_many')

    def test_isinf_keyword(self):
        self.check('isinf_keyword')

    def test_isinf_string_error(self):
        self.check('isinf_string_error')

    def test_isinf_none_error(self):
        self.check('isinf_none_error')

    def test_isinf_huge_checked(self):
        self.check('isinf_huge_checked')


    def test_isfinite_empty(self):
        self.check('isfinite_empty')

    def test_isfinite_too_many(self):
        self.check('isfinite_too_many')

    def test_isfinite_keyword(self):
        self.check('isfinite_keyword')

    def test_isfinite_string_error(self):
        self.check('isfinite_string_error')

    def test_isfinite_none_error(self):
        self.check('isfinite_none_error')

    def test_isfinite_huge_checked(self):
        self.check('isfinite_huge_checked')


    def test_closed_nullable(self):
        self.check('closed_nullable')

    def test_closed_text(self):
        self.check('closed_text')

    def test_list_retained(self):
        self.check('list_retained')

    def test_after_error_atexit(self):
        self.check('after_error_atexit')

    def test_shared_wrong_type_atexit(self):
        self.check('shared_wrong_type_atexit')

if __name__=='__main__':unittest.main()
