"""Typed integer-exponent powers preserve original results, errors and NaN identity."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile

CASES={'integral_dynamic': ("shared=float('nan')\n"
                      'print((shared,)==(shared,))\n'
                      'base,exponent=map(int,input().split())\n'
                      'result=base**exponent\n'
                      'print(result)\n'
                      'print((result,)==(result,))\n',
                      ('2 -3\n',
                       '-2 -3\n',
                       '2 5\n',
                       '0 0\n',
                       '0 -1\n',
                       '2 -1075\n',
                       '-2 -1075\n',
                       '-1 -9007199254740993\n'),
                      ('i64', 'i128', 'bigint')),
 'integral_negative_literal': ("shared=float('nan')\n"
                               'print((shared,)==(shared,))\n'
                               'print(2**-3,(-2)**-3)\n',
                               ('',),
                               ('i64', 'i128', 'bigint')),
 'integral_nonnegative_literal': ("shared=float('nan')\n"
                                  'print((shared,)==(shared,))\n'
                                  'print(3**7,True**0,False**1)\n',
                                  ('',),
                                  ('i64', 'i128', 'bigint')),
 'float_base_integral': ("shared=float('nan')\n"
                         'print((shared,)==(shared,))\n'
                         'base=float(input())\n'
                         'exponent=int(input())\n'
                         'result=base**exponent\n'
                         'print(result,base==result,(base,)==(result,),(result,)==(result,))\n',
                         ('nan\n2\n',
                          'nan\n0\n',
                          'inf\n-1\n',
                          '-inf\n-3\n',
                          '-0.0\n3\n',
                          '-0.0\n-1\n',
                          '0\n-1\n',
                          '1e308\n2\n',
                          '-1e-300\n3\n',
                          '-1.0\n-9007199254740993\n'),
                         ('i64', 'i128', 'bigint')),
 'fresh_nan_power_results': ("shared=float('nan')\n"
                             'print((shared,)==(shared,))\n'
                             'first=shared**2\n'
                             'second=pow(shared,2)\n'
                             'print(shared==first,(shared,)==(first,),(first,)==(second,),(first,)==(first,))\n',
                             ('',),
                             ('i64', 'i128', 'bigint')),
 'pow_alias_keywords': ("shared=float('nan')\n"
                        'print((shared,)==(shared,))\n'
                        'saved=pow\n'
                        'n=int(input())\n'
                        'def value(label,number):\n'
                        " print(label,end='|')\n"
                        ' return number\n'
                        "result=saved(exp=value('exp',n),base=value('base',-2),mod=value('mod',None))\n"
                        'print(result)\n',
                        ('-3\n', '0\n', '4\n'),
                        ('i64', 'i128', 'bigint')),
 'indexed_augmented': ("shared=float('nan')\n"
                       'print((shared,)==(shared,))\n'
                       'values=[2]\n'
                       'def index():\n'
                       " print('index',end='|')\n"
                       ' return 0\n'
                       'values[index()]**=int(input())\n'
                       'print(values)\n',
                       ('-3\n', '0\n', '5\n'),
                       ('i64', 'i128', 'bigint')),
 'function_result_alternatives': ("shared=float('nan')\n"
                                  'print((shared,)==(shared,))\n'
                                  'def power(base,exponent):return base**exponent\n'
                                  'for exponent in (-3,0,5):\n'
                                  ' result=power(-2,exponent)\n'
                                  ' print(result,(result,)==(result,))\n',
                                  ('',),
                                  ('i64', 'i128', 'bigint')),
 'float_nan_zero_branch': ("shared=float('nan')\n"
                           'print((shared,)==(shared,))\n'
                           'base=float(input())\n'
                           'print(base**0,pow(base,1),pow(base,-1))\n',
                           ('nan\n', 'inf\n', '-0.0\n', '2.0\n'),
                           ('i64', 'i128', 'bigint')),
 'unboxed_control': ('base,exponent=map(int,input().split())\nprint(base**exponent)\n',
                     ('2 -3\n', '-2 -3\n', '2 5\n'),
                     ('i64', 'i128', 'bigint')),
 'checked_huge_conversion': ("shared=float('nan')\n"
                             'print((shared,)==(shared,))\n'
                             'base=int(input())\n'
                             'exponent=int(input())\n'
                             'print(base**exponent)\n',
                             ('114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n'
                              '-1\n',
                              '0\n'
                              '-114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n',
                              '-114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n'
                              '-1\n',
                              '1\n'
                              '-114813069527425452423283320117768198402231770208869520047764273682576626139237031385665948631650626991844596463898746277344711896086305533142593135616665318539129989145312280000688779148240044871428926990063486244781615463646388363947317026040466353970904996558162398808944629605623311649536164221970332681344168908984458505602379484807914058900934776500429002716706625830522008132236281291761267883317206598995396418127021779858404042159853183251540889433902091920554957783589672039160081957216630582755380425583726015528348786419432054508915275783882625175435528800822842770817965453762184851149029376\n'),
                             ('bigint',)),
 'fresh_nan_dictionary_keys': ("base=float('nan')\n"
                               'first=base**1\n'
                               'second=pow(base,1)\n'
                               "values={base:'base',first:'first',second:'second'}\n"
                               'print(len(values),values[base],values[first],values[second])\n'
                               "values[pow(first,1)]='fresh'\n"
                               'print(len(values),list(values.values()))\n',
                               ('',),
                               ('i64', 'i128', 'bigint')),
 'int_bool_power_alternatives': ("shared=float('nan')\n"
                                 'print((shared,)==(shared,))\n'
                                 'for flag in (False,True):\n'
                                 ' exponent=True if flag else -1\n'
                                 ' base=True if flag else 2\n'
                                 ' print(base**exponent)\n'
                                 ' value=shared**exponent\n'
                                 ' print(value,(value,)==(shared,),(value,)==(value,))\n',
                                 ('',),
                                 ('i64', 'i128', 'bigint')),
 'plain_float_power_control': ('base=float(input())\n'
                               'exponent=int(input())\n'
                               'print(base**exponent)\n',
                               ('nan\n2\n', '-0.0\n3\n', '2.0\n-3\n'),
                               ('i64', 'i128', 'bigint')),
 'frame_integer_control': ('class Marker:pass\n'
                           'base,exponent=map(int,input().split())\n'
                           'print(base**exponent)\n',
                           ('2 -3\n', '-2 3\n'),
                           ('i64', 'i128', 'bigint')),
 'frame_float_control': ('class Marker:pass\n'
                         'base=float(input())\n'
                         'exponent=int(input())\n'
                         'print(base**exponent)\n',
                         ('nan\n2\n', '-0.0\n3\n'),
                         ('i64', 'i128', 'bigint')),
 'frame_pow_alias_control': ('class Marker:pass\nsaved=pow\nprint(saved(exp=-3,base=2,mod=None))\n',
                             ('',),
                             ('i64', 'i128', 'bigint')),
 'shadowed_pow_control': ("shared=float('nan')\n"
                          'print((shared,)==(shared,))\n'
                          'def pow(base,exponent):return base+exponent\n'
                          'print(pow(2,-1))\n',
                          ('',),
                          ('i64', 'i128', 'bigint'))}

BOUNDARIES={'float_exponent_boundary': ("shared=float('nan')\n"
                             'print((shared,)==(shared,))\n'
                             'base=int(input())\n'
                             'exponent=float(input())\n'
                             'print(base**exponent)\n',
                             'power'),
 'finite_modulus_union_boundary': ("shared=float('nan')\n"
                                   'print((shared,)==(shared,))\n'
                                   'exponent=-1\n'
                                   'for flag in (False,True):\n'
                                   ' modulus=None if flag else 5\n'
                                   ' print(pow(2,exponent,modulus))\n',
                                   'pow'),
 'floating_exponent_call_boundary': ("shared=float('nan')\n"
                                     'print((shared,)==(shared,))\n'
                                     'print(pow(2,0.5))\n',
                                     'pow'),
 'unproved_set_power_history': ('exponent=int(input())\n'
                                'items={2**exponent}\n'
                                'print(sorted(items))\n',
                                'NaN')}

class DemandedPowerProofTests(unittest.TestCase):
    def test_unproved_power_and_set_history_boundaries_are_positioned(self):
        for name,(source,reason)in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode,filename='original.py',license='none'))
                self.assertFalse(result.success,(name,result.diagnostics))
                diagnostic=result.diagnostics[0]
                self.assertEqual((diagnostic.code,diagnostic.filename),('E006','original.py'))
                self.assertGreater(diagnostic.line,0)
                self.assertIn(reason,diagnostic.message)

    def test_nonnegative_integer_literals_keep_the_existing_integer_path(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['integral_nonnegative_literal'][0],TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('NativeIdentityFloat',result.rust_source)
            self.assertNotIn('.powf(',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DemandedPowerExecutionTests(unittest.TestCase):
    def check(self,name):
        source,inputs,modes=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-demand-power-')as directory:
            root=Path(directory);program=root/'case.py';program.write_text(source)
            expected=[subprocess.run([sys.executable,'-I','-B',str(program)],input=data,text=True,capture_output=True,timeout=20)for data in inputs]
            for mode in modes:
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename=str(program),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):self.assertNotIn(marker,result.rust_source)
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+str(optimized));built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180);self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(name=name,integer=mode,optimized=optimized,stdin=data):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=20)
                            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                            if reference.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1:],reference.stderr.splitlines()[-1:])
                                frames=lambda value:re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',value)
                                self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                            else:self.assertEqual(actual.stderr,'')

    def test_integral_dynamic(self):
        self.check('integral_dynamic')

    def test_integral_negative_literal(self):
        self.check('integral_negative_literal')

    def test_integral_nonnegative_literal(self):
        self.check('integral_nonnegative_literal')

    def test_float_base_integral(self):
        self.check('float_base_integral')

    def test_fresh_nan_power_results(self):
        self.check('fresh_nan_power_results')

    def test_pow_alias_keywords(self):
        self.check('pow_alias_keywords')

    def test_indexed_augmented(self):
        self.check('indexed_augmented')

    def test_function_result_alternatives(self):
        self.check('function_result_alternatives')

    def test_float_nan_zero_branch(self):
        self.check('float_nan_zero_branch')

    def test_unboxed_control(self):
        self.check('unboxed_control')

    def test_checked_huge_conversion(self):
        self.check('checked_huge_conversion')

    def test_fresh_nan_dictionary_keys(self):
        self.check('fresh_nan_dictionary_keys')

    def test_int_bool_power_alternatives(self):
        self.check('int_bool_power_alternatives')

    def test_plain_float_power_control(self):
        self.check('plain_float_power_control')

    def test_frame_integer_control(self):
        self.check('frame_integer_control')

    def test_frame_float_control(self):
        self.check('frame_float_control')

    def test_frame_pow_alias_control(self):
        self.check('frame_pow_alias_control')

    def test_shadowed_pow_control(self):
        self.check('shadowed_pow_control')

if __name__=='__main__':unittest.main()
