"""Concrete lazy choices retain pool capture and typed tuple semantics."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests

CASES={'callable_alias_identity': 'from itertools import combinations as choose\n'
                            'original=choose\n'
                            'choose=lambda values,r:[(99,)]\n'
                            'print(list(original([1,2,3],2)),choose([1],1))\n',
 'class_field_pool_capture': 'from itertools import combinations\n'
                             'class Box:\n'
                             ' def __init__(self):self.value=0\n'
                             'box=Box()\n'
                             'def visit(v):\n'
                             ' box.value+=v\n'
                             ' return v\n'
                             'for i in range(2):\n'
                             ' print(box.value)\n'
                             ' stream=combinations(map(visit,[1,2]),1)\n'
                             ' print(box.value,next(stream))\n',
 'classinfo_and_shared_cursor': 'from itertools import '
                                'combinations,permutations,combinations_with_replacement\n'
                                'a=combinations([1,2],1)\n'
                                'b=permutations([1,2],1)\n'
                                'c=combinations_with_replacement([1,2],1)\n'
                                'print(isinstance(a,combinations),isinstance(b,permutations),isinstance(c,combinations_with_replacement),iter(a) '
                                'is a,next(a),list(a))\n',
 'combinations_binding_duplicate': 'from itertools import combinations as choose\n'
                                   'choose([1],1,r=2)\n',
 'combinations_binding_missing': 'from itertools import combinations as choose\nchoose()\n',
 'combinations_binding_unknown': 'from itertools import combinations as choose\n'
                                 'choose([1],1,bad=2)\n',
 'combinations_empty_zero_oversized': 'from itertools import combinations\n'
                                      'print(list(combinations([],0)),list(combinations([],1)),list(combinations([1,2],0)),list(combinations([1,2],3)))\n',
 'combinations_float_ordering': 'from itertools import combinations as choose\n'
                                'def visit(v):\n'
                                ' print("pool",v)\n'
                                ' return v\n'
                                'print(choose(map(visit,[1,2]),1.5))\n',
 'combinations_huge_valid_rank': 'from itertools import combinations as choose\n'
                                 'def visit(v):\n'
                                 ' print("pool",v)\n'
                                 ' return v\n'
                                 'choose(map(visit,[1]),9223372036854775807)\n',
 'combinations_negative_ordering': 'from itertools import combinations as choose\n'
                                   'def visit(v):\n'
                                   ' print("pool",v)\n'
                                   ' return v\n'
                                   'print(choose(map(visit,[1,2]),-1))\n',
 'combinations_none_ordering': 'from itertools import combinations as choose\n'
                               'def visit(v):\n'
                               ' print("pool",v)\n'
                               ' return v\n'
                               'print(choose(map(visit,[1,2]),None))\n',
 'combinations_noniterable_vs_bad_rank': 'from itertools import combinations as choose\n'
                                         'choose(3,1.5)\n',
 'combinations_order': 'from itertools import combinations\n'
                       'print(list(combinations([4,1,3,1],2)))\n',
 'combinations_with_replacement_binding_duplicate': 'from itertools import '
                                                    'combinations_with_replacement as choose\n'
                                                    'choose([1],1,r=2)\n',
 'combinations_with_replacement_binding_missing': 'from itertools import '
                                                  'combinations_with_replacement as choose\n'
                                                  'choose()\n',
 'combinations_with_replacement_binding_unknown': 'from itertools import '
                                                  'combinations_with_replacement as choose\n'
                                                  'choose([1],1,bad=2)\n',
 'combinations_with_replacement_float_ordering': 'from itertools import '
                                                 'combinations_with_replacement as choose\n'
                                                 'def visit(v):\n'
                                                 ' print("pool",v)\n'
                                                 ' return v\n'
                                                 'print(choose(map(visit,[1,2]),1.5))\n',
 'combinations_with_replacement_huge_valid_rank': 'from itertools import '
                                                  'combinations_with_replacement as choose\n'
                                                  'def visit(v):\n'
                                                  ' print("pool",v)\n'
                                                  ' return v\n'
                                                  'choose(map(visit,[1]),9223372036854775807)\n',
 'combinations_with_replacement_negative_ordering': 'from itertools import '
                                                    'combinations_with_replacement as choose\n'
                                                    'def visit(v):\n'
                                                    ' print("pool",v)\n'
                                                    ' return v\n'
                                                    'print(choose(map(visit,[1,2]),-1))\n',
 'combinations_with_replacement_none_ordering': 'from itertools import '
                                                'combinations_with_replacement as choose\n'
                                                'def visit(v):\n'
                                                ' print("pool",v)\n'
                                                ' return v\n'
                                                'print(choose(map(visit,[1,2]),None))\n',
 'combinations_with_replacement_noniterable_vs_bad_rank': 'from itertools import '
                                                          'combinations_with_replacement as '
                                                          'choose\n'
                                                          'choose(3,1.5)\n',
 'constructor_argument_effects': 'from itertools import combinations\n'
                                 'def mark(label,value):\n'
                                 ' print(label)\n'
                                 ' return value\n'
                                 'print(list(combinations(mark("values",[1,2,3]),r=mark("rank",2))))\n',
 'constructor_binding_shape_precedence': 'from itertools import combinations\n'
                                         'def mark(label,value):\n'
                                         ' print(label)\n'
                                         ' return value\n'
                                         'combinations(mark("source",[1]),bad=mark("bad",2))\n',
 'consumer_composition': 'from itertools import '
                         'combinations,permutations,combinations_with_replacement\n'
                         'print(sum(a*b for a,b in combinations(range(5),2)))\n'
                         'print(list(zip(permutations([1,2,3],1),range(6))))\n'
                         'print([(i,a+b)for i,(a,b)in '
                         'enumerate(combinations_with_replacement([2,3],2))])\n',
 'dynamic_rank_and_unpack': 'from itertools import '
                            'combinations,permutations,combinations_with_replacement\n'
                            'def pairs(r):\n'
                            ' for a,b in combinations([1,2,3],r):print(a+b)\n'
                            ' for a,b in permutations([1,2,3],r):print(a-b)\n'
                            ' for a,b in combinations_with_replacement([1,2],r):print(a*b)\n'
                            'pairs(2)\n',
 'dynamic_rank_tuple_index': 'from itertools import permutations\n'
                             'def first_last(values,r):return [(v[0],v[-1],len(v))for v in '
                             'permutations(values,r)]\n'
                             'print(first_last([1,2,3],2),first_last([1,2],1))\n',
 'finite_source_alternatives': 'from itertools import combinations\n'
                               'def choose(values):return list(combinations(values,2))\n'
                               'print(choose([1,2,3]),choose((4,5,6)),choose(range(3)),choose(b"abc"),choose("xyz"))\n',
 'generator_pool_and_argument_order': 'from itertools import permutations,combinations\n'
                                      'rows=[1,2,3]\n'
                                      'def visit(value):\n'
                                      ' print("pool",value)\n'
                                      ' return value\n'
                                      'def rank():\n'
                                      ' print("rank")\n'
                                      ' rows.append(4)\n'
                                      ' return 2\n'
                                      'stream=permutations((visit(v)for v in rows),rank())\n'
                                      'print(next(stream),len(list(stream)))\n'
                                      'print(list(combinations((v*v for v in [1,2,3]),2)))\n',
 'heterogeneous_pool': 'from itertools import combinations,permutations\n'
                       'print(list(combinations((1,"x",None),2)))\n'
                       'print(list(permutations((True,2),2)))\n',
 'input_snapshot_and_mutable_items': 'from itertools import '
                                     'combinations,permutations,combinations_with_replacement\n'
                                     'child=[1]\n'
                                     'rows=[child,[2]]\n'
                                     'a=combinations(rows,1)\n'
                                     'b=permutations(rows,1)\n'
                                     'c=combinations_with_replacement(rows,1)\n'
                                     'rows.append([3])\n'
                                     'child.append(9)\n'
                                     'for stream in (a,b,c):\n'
                                     ' item=next(stream)\n'
                                     ' print(item,item[0] is child,list(stream))\n',
 'keyword_generator_pool': 'from itertools import '
                           'combinations,permutations,combinations_with_replacement\n'
                           'print(list(combinations(iterable=(i*i for i in range(4)),r=2)))\n'
                           'print(list(permutations(r=2,iterable=(i+1 for i in [1,2,3]))))\n'
                           'print(list(combinations_with_replacement(iterable=(i for i in '
                           '[2,3]),r=2)))\n',
 'partial_alias_consumption': 'from itertools import '
                              'combinations,permutations,combinations_with_replacement\n'
                              'a=combinations([1,2,3],2)\n'
                              'b=a\n'
                              'print(next(a),next(b),list(a),list(b))\n'
                              'a=permutations([1,2,3],2)\n'
                              'b=a\n'
                              'print(next(a),next(b),list(a),list(b))\n'
                              'a=combinations_with_replacement([1,2],2)\n'
                              'b=a\n'
                              'print(next(a),next(b),list(a),list(b))\n',
 'permutations_binding_duplicate': 'from itertools import permutations as choose\n'
                                   'choose([1],1,r=2)\n',
 'permutations_binding_missing': 'from itertools import permutations as choose\nchoose()\n',
 'permutations_binding_unknown': 'from itertools import permutations as choose\n'
                                 'choose([1],1,bad=2)\n',
 'permutations_default_and_none': 'from itertools import permutations\n'
                                  'print(list(permutations([3,1,2])))\n'
                                  'print(list(permutations([3,1],None)))\n',
 'permutations_empty_zero_oversized': 'from itertools import permutations\n'
                                      'print(list(permutations([])),list(permutations([],1)),list(permutations([1,2],0)),list(permutations([1,2],3)))\n',
 'permutations_float_ordering': 'from itertools import permutations as choose\n'
                                'def visit(v):\n'
                                ' print("pool",v)\n'
                                ' return v\n'
                                'print(choose(map(visit,[1,2]),1.5))\n',
 'permutations_huge_valid_rank': 'from itertools import permutations as choose\n'
                                 'def visit(v):\n'
                                 ' print("pool",v)\n'
                                 ' return v\n'
                                 'choose(map(visit,[1]),9223372036854775807)\n',
 'permutations_negative_ordering': 'from itertools import permutations as choose\n'
                                   'def visit(v):\n'
                                   ' print("pool",v)\n'
                                   ' return v\n'
                                   'print(choose(map(visit,[1,2]),-1))\n',
 'permutations_none_ordering': 'from itertools import permutations as choose\n'
                               'def visit(v):\n'
                               ' print("pool",v)\n'
                               ' return v\n'
                               'print(choose(map(visit,[1,2]),None))\n',
 'permutations_noniterable_vs_bad_rank': 'from itertools import permutations as choose\n'
                                         'choose(3,1.5)\n',
 'permutations_order': 'from itertools import permutations\n'
                       'print(list(permutations([4,1,3,1],2)))\n',
 'pool_stop_is_snapshot_boundary': 'from itertools import '
                                   'combinations,permutations,combinations_with_replacement\n'
                                   'def visit(value):\n'
                                   ' print("pool",value)\n'
                                   ' if value==2:return next(iter(()))\n'
                                   ' return value\n'
                                   'for make in '
                                   '(combinations,permutations,combinations_with_replacement):\n'
                                   ' source=map(visit,[1,2,3])\n'
                                   ' stream=make(source,1)\n'
                                   ' print(list(stream),list(source))\n',
 'qualified_canonical_identities': 'import itertools as tools\n'
                                   'print(list(tools.permutations([2,3],r=1)))\n'
                                   'print(list(tools.combinations(iterable=[1,2,3],r=2)))\n'
                                   'print(list(tools.combinations_with_replacement(r=2,iterable=[1,2])))\n',
 'rank_bool_and_nullable': 'from itertools import combinations,permutations\n'
                           'def collect(r):return list(permutations([1,2],r))\n'
                           'print(collect(None),collect(True),collect(False),list(combinations([1,2],True)))\n',
 'replacement_empty_zero_oversized': 'from itertools import combinations_with_replacement as '
                                     'choose\n'
                                     'print(list(choose([],0)),list(choose([],1)),list(choose([1,2],0)),list(choose([1,2],3)))\n',
 'replacement_order': 'from itertools import combinations_with_replacement\n'
                      'print(list(combinations_with_replacement([4,1,3],2)))\n',
 'runtime_unpack_error': 'from itertools import combinations\n'
                         'def run(r):\n'
                         ' for a,b in combinations([1,2,3],r):print(a,b)\n'
                         'run(1)\n',
 'unicode_pool': 'from itertools import permutations,combinations\n'
                 'print(list(permutations("猫🐈é",2)),list(combinations("猫🐈é",2)))\n',
 'zero_rank_still_consumes_pool': 'from itertools import '
                                  'combinations,permutations,combinations_with_replacement\n'
                                  'def visit(value):\n'
                                  ' print("pool",value)\n'
                                  ' return value\n'
                                  'print(list(combinations(map(visit,[1,2]),0)))\n'
                                  'print(list(permutations(map(visit,[3,4]),0)))\n'
                                  'print(list(combinations_with_replacement(map(visit,[5,6]),0)))\n'}

@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ChoiceTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_combinations_order(self):self.check('combinations_order')

    def test_permutations_order(self):self.check('permutations_order')

    def test_replacement_order(self):self.check('replacement_order')

    def test_permutations_default_and_none(self):self.check('permutations_default_and_none')

    def test_combinations_empty_zero_oversized(self):self.check('combinations_empty_zero_oversized')

    def test_permutations_empty_zero_oversized(self):self.check('permutations_empty_zero_oversized')

    def test_replacement_empty_zero_oversized(self):self.check('replacement_empty_zero_oversized')

    def test_dynamic_rank_and_unpack(self):self.check('dynamic_rank_and_unpack')

    def test_dynamic_rank_tuple_index(self):self.check('dynamic_rank_tuple_index')

    def test_rank_bool_and_nullable(self):self.check('rank_bool_and_nullable')

    def test_callable_alias_identity(self):self.check('callable_alias_identity')

    def test_qualified_canonical_identities(self):self.check('qualified_canonical_identities')

    def test_input_snapshot_and_mutable_items(self):self.check('input_snapshot_and_mutable_items')

    def test_partial_alias_consumption(self):self.check('partial_alias_consumption')

    def test_zero_rank_still_consumes_pool(self):self.check('zero_rank_still_consumes_pool')

    def test_generator_pool_and_argument_order(self):self.check('generator_pool_and_argument_order')

    def test_pool_stop_is_snapshot_boundary(self):self.check('pool_stop_is_snapshot_boundary')

    def test_consumer_composition(self):self.check('consumer_composition')

    def test_finite_source_alternatives(self):self.check('finite_source_alternatives')

    def test_unicode_pool(self):self.check('unicode_pool')

    def test_heterogeneous_pool(self):self.check('heterogeneous_pool')

    def test_class_field_pool_capture(self):self.check('class_field_pool_capture')

    def test_classinfo_and_shared_cursor(self):self.check('classinfo_and_shared_cursor')

    def test_runtime_unpack_error(self):self.check('runtime_unpack_error')

    def test_combinations_negative_ordering(self):self.check('combinations_negative_ordering')

    def test_combinations_float_ordering(self):self.check('combinations_float_ordering')

    def test_combinations_none_ordering(self):self.check('combinations_none_ordering')

    def test_combinations_binding_missing(self):self.check('combinations_binding_missing')

    def test_combinations_binding_duplicate(self):self.check('combinations_binding_duplicate')

    def test_combinations_binding_unknown(self):self.check('combinations_binding_unknown')

    def test_combinations_noniterable_vs_bad_rank(self):self.check('combinations_noniterable_vs_bad_rank')

    def test_combinations_huge_valid_rank(self):self.check('combinations_huge_valid_rank')

    def test_permutations_negative_ordering(self):self.check('permutations_negative_ordering')

    def test_permutations_float_ordering(self):self.check('permutations_float_ordering')

    def test_permutations_binding_missing(self):self.check('permutations_binding_missing')

    def test_permutations_binding_duplicate(self):self.check('permutations_binding_duplicate')

    def test_permutations_binding_unknown(self):self.check('permutations_binding_unknown')

    def test_permutations_noniterable_vs_bad_rank(self):self.check('permutations_noniterable_vs_bad_rank')

    def test_permutations_huge_valid_rank(self):self.check('permutations_huge_valid_rank')

    def test_combinations_with_replacement_negative_ordering(self):self.check('combinations_with_replacement_negative_ordering')

    def test_combinations_with_replacement_float_ordering(self):self.check('combinations_with_replacement_float_ordering')

    def test_combinations_with_replacement_none_ordering(self):self.check('combinations_with_replacement_none_ordering')

    def test_combinations_with_replacement_binding_missing(self):self.check('combinations_with_replacement_binding_missing')

    def test_combinations_with_replacement_binding_duplicate(self):self.check('combinations_with_replacement_binding_duplicate')

    def test_combinations_with_replacement_binding_unknown(self):self.check('combinations_with_replacement_binding_unknown')

    def test_combinations_with_replacement_noniterable_vs_bad_rank(self):self.check('combinations_with_replacement_noniterable_vs_bad_rank')

    def test_combinations_with_replacement_huge_valid_rank(self):self.check('combinations_with_replacement_huge_valid_rank')

    def test_keyword_generator_pool(self):self.check('keyword_generator_pool')

    def test_constructor_argument_effects(self):self.check('constructor_argument_effects')

    def test_constructor_binding_shape_precedence(self):self.check('constructor_binding_shape_precedence')

    def test_permutations_none_ordering(self):
        source=self.cases['permutations_none_ordering']
        cp=subprocess.run([sys.executable,'-I','-S','-c',source],capture_output=True,text=True,timeout=10)
        def normalized(text):return re.sub(r'0x[0-9a-f]+','0xADDRESS',text)
        with tempfile.TemporaryDirectory(prefix='pytors-choices-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
                    result=transpile(source,TranspileOptions(integer=mode,license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    self.assertEqual(actual.returncode,cp.returncode,actual.stderr)
                    self.assertEqual(normalized(actual.stdout),normalized(cp.stdout))
                    self.assertEqual(actual.stderr,'')


GENERIC_CASES={'choices_generator_pep479': 'from itertools import combinations\n'
                             'print(list(combinations((next(iter(()))for i in [1]),1)))\n',
 'choices_keyword_alias_pool': 'from itertools import combinations as choose\n'
                               'saved=choose\n'
                               'choose=lambda iterable,r:[]\n'
                               'print(list(saved(iterable=(v+1 for v in range(3)),r=2)))\n',
 'choices_pool_error_frame': 'from itertools import permutations\n'
                             'def visit(v):return 1//v\n'
                             'print(list(permutations(map(visit,[1,0]),1)))\n',
 'generic_callable_tuple_for': 'class Runner:\n'
                               ' def run(self):\n'
                               '  for operation in (sum,max,min):print(operation([1,2,3]))\n'
                               'Runner().run()\n',
 'generic_heterogeneous_tuple_for': 'class Runner:\n'
                                    ' def run(self):\n'
                                    '  for value in (1,"word",None,True):print(value)\n'
                                    'Runner().run()\n',
 'generic_iterator_family_next': 'def consume(stream):return next(stream),list(stream)\n'
                                 'for stream in '
                                 '(iter([1,2]),filter(None,[0,3,4]),map(int,["5","6"])):\n'
                                 ' print(consume(stream))\n',
 'generic_next_invalid_union': 'def consume(stream):return next(stream)\n'
                               'print(consume(iter([7])))\n'
                               'consume(3)\n',
 'generic_next_source_callback_effects': 'class Box:\n'
                                         ' def __init__(self):self.value=0\n'
                                         'box=Box()\n'
                                         'def visit(v):\n'
                                         ' box.value+=v\n'
                                         ' return v\n'
                                         'def consume(stream):return next(stream)\n'
                                         'for stream in (map(visit,[1]),filter(None,[4])):\n'
                                         ' print(box.value,consume(stream),box.value)\n'}

class ChoiceGenericTests(unittest.TestCase):
    cases=GENERIC_CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_generic_heterogeneous_tuple_for(self):self.check('generic_heterogeneous_tuple_for')

    def test_generic_callable_tuple_for(self):self.check('generic_callable_tuple_for')

    def test_generic_iterator_family_next(self):self.check('generic_iterator_family_next')

    def test_generic_next_invalid_union(self):self.check('generic_next_invalid_union')

    def test_generic_next_source_callback_effects(self):self.check('generic_next_source_callback_effects')

    def test_choices_keyword_alias_pool(self):self.check('choices_keyword_alias_pool')

    def test_choices_pool_error_frame(self):self.check('choices_pool_error_frame')

    def test_choices_generator_pep479(self):self.check('choices_generator_pep479')
