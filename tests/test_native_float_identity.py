"""Typed float payloads preserve Python NaN identity without a dynamic runtime."""
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_float_identity import RUNTIME
from tests import test_native_heapq as execution

CASES={'shared_nan_heap': ('import heapq\n'
                     "value=float('nan')\n"
                     "q=[(value,'b'),(value,'a')]\n"
                     'heapq.heapify(q)\n'
                     'print(value==value)\n'
                     'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                     ('',)),
 'distinct_nan_heap': ('import heapq\n'
                       "left=float('nan')\n"
                       "right=float('nan')\n"
                       "q=[(left,'a'),(right,'b')]\n"
                       'heapq.heapify(q)\n'
                       'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                       ('',)),
 'conversion_plus_alias': ('import heapq\n'
                           "value=float('nan')\n"
                           'alias=float(value)\n'
                           'positive=+alias\n'
                           'q=[(value,3),(alias,2),(positive,1)]\n'
                           'heapq.heapify(q)\n'
                           'print([heapq.heappop(q)[1] for _ in range(3)])\n',
                           ('',)),
 'negative_abs_fresh': ('import heapq\n'
                        "value=float('nan')\n"
                        'negative=-value\n'
                        'absolute=abs(value)\n'
                        "q=[(value,'original'),(negative,'negative'),(absolute,'absolute')]\n"
                        'heapq.heapify(q)\n'
                        'print([heapq.heappop(q)[1] for _ in range(3)])\n',
                        ('',)),
 'arithmetic_nan_fresh': ('import heapq\n'
                          "infinite=float('inf')\n"
                          'left=infinite-infinite\n'
                          'right=infinite-infinite\n'
                          "q=[(left,'a'),(right,'b')]\n"
                          'heapq.heapify(q)\n'
                          'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                          ('',)),
 'precision_and_tie': ('import heapq\n'
                       'class Key:\n'
                       '    def __init__(self,rank):self.rank=rank\n'
                       '    def __eq__(self,other):return self.rank==other.rank\n'
                       '    def __lt__(self,other):return self.rank<other.rank\n'
                       "q=[(9007199254740993,Key(3)),(9007199254740992.0,Key(2)),(float('inf'),Key(9)),(1.0,Key(1)),(1,Key(0))]\n"
                       'heapq.heapify(q)\n'
                       'print([heapq.heappop(q)[1].rank for _ in range(5)])\n',
                       ('',)),
 'signed_zero_infinities': ('import heapq\n'
                            "q=[(0.0,'b'),(-0.0,'a'),(float('inf'),'z'),(float('-inf'),'m')]\n"
                            'heapq.heapify(q)\n'
                            'print([heapq.heappop(q)[1] for _ in range(4)])\n',
                            ('',)),
 'input_conversion_alias': ('import heapq\n'
                            'def convert(text):return float(text)\n'
                            'value=convert(input())\n'
                            'q=[(value,2),(float(value),1)]\n'
                            'heapq.heapify(q)\n'
                            'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                            ('nan\n', '2.5\n')),
 'nested_lists_and_tuples': ('import heapq\n'
                             "value=float('nan')\n"
                             'first=[value]\n'
                             'second=[value]\n'
                             "third=[float('nan')]\n"
                             'print(first==second,first==third)\n'
                             'q=[((first,),2),((second,),1)]\n'
                             'heapq.heapify(q)\n'
                             'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                             ('',)),
 'default_object_alias': ('import heapq\n'
                          "def get(value=float('nan')):return value\n"
                          'q=[(get(),2),(get(),1)]\n'
                          'heapq.heapify(q)\n'
                          'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                          ('',)),
 'closure_object_alias': ('import heapq\n'
                          'def outer(value):\n'
                          '    def get():return value\n'
                          '    return get\n'
                          "get=outer(float('nan'))\n"
                          'q=[(get(),2),(get(),1)]\n'
                          'heapq.heapify(q)\n'
                          'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                          ('',)),
 'all_core_min_max': ('import heapq\n'
                      "value=float('nan')\n"
                      'def exercise(maximum):\n'
                      '    if maximum:\n'
                      '        prepare=heapq.heapify_max\n'
                      '        push=heapq.heappush_max\n'
                      '        pop=heapq.heappop_max\n'
                      '        pushpop=heapq.heappushpop_max\n'
                      '        replace=heapq.heapreplace_max\n'
                      '    else:\n'
                      '        prepare=heapq.heapify\n'
                      '        push=heapq.heappush\n'
                      '        pop=heapq.heappop\n'
                      '        pushpop=heapq.heappushpop\n'
                      '        replace=heapq.heapreplace\n'
                      '    queue=[(value,3),(value,1),(value,2)]\n'
                      '    prepare(queue)\n'
                      '    push(queue,(value,0))\n'
                      '    print(pushpop(queue,(value,4))[1],replace(queue,(value,5))[1])\n'
                      '    print([pop(queue)[1]for _ in range(len(queue))])\n'
                      'exercise(False)\n'
                      'exercise(True)\n',
                      ('',)),
 'division_floor_mod_fresh': ('import heapq\n'
                              "infinite=float('inf')\n"
                              'first=infinite/infinite\n'
                              'second=infinite//2.0\n'
                              'third=infinite%2.0\n'
                              "queue=[(first,'a'),(first,'b'),(second,'c'),(third,'d')]\n"
                              'heapq.heapify(queue)\n'
                              'print([heapq.heappop(queue)[1]for _ in range(4)])\n',
                              ('',)),
 'min_max_return_alias': ('import heapq\n'
                          "value=float('nan')\n"
                          "first=min([value,float('nan')])\n"
                          "second=max([value,float('nan')])\n"
                          'third=min([],default=value)\n'
                          'queue=[(value,4),(first,3),(second,2),(third,1)]\n'
                          'heapq.heapify(queue)\n'
                          'print([heapq.heappop(queue)[1]for _ in range(4)])\n',
                          ('',)),
 'bytes_bytearray_text': ('import heapq\n'
                          "first=float(b'nan')\n"
                          "second=float(bytearray(b'nan'))\n"
                          'queue=[(first,2),(float(first),1),(second,3)]\n'
                          'heapq.heapify(queue)\n'
                          'print(str(first),repr(second),ascii(first))\n'
                          'print([heapq.heappop(queue)[1]for _ in range(3)])\n',
                          ('',)),
 'iterator_tuple_alias': ('import heapq\n'
                          "value=float('nan')\n"
                          'source=iter([value])\n'
                          'first=next(source)\n'
                          'values=tuple([first])\n'
                          'queue=[(value,2),(values[0],1)]\n'
                          'heapq.heapify(queue)\n'
                          'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                          ('',)),
 'augmented_field_fresh': ('import heapq\n'
                           'class Box:\n'
                           '    def __init__(self,value):self.value=value\n'
                           "box=Box(float('nan'))\n"
                           'old=box.value\n'
                           'box.value+=0.0\n'
                           "queue=[(old,'old'),(box.value,'new')]\n"
                           'heapq.heapify(queue)\n'
                           'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                           ('',)),
 'bare_mixed_bisect': ('import heapq\n'
                       "value=float('nan')\n"
                       'queue=[(value,2),(value,1)]\n'
                       'heapq.heapify(queue)\n'
                       'from bisect import bisect_left,bisect_right\n'
                       'values=[9007199254740992.0,9007199254740993]\n'
                       'print(bisect_left(values,9007199254740993),bisect_right(values,9007199254740992.0))\n',
                       ('',)),
 'dictionary_copy_alias': ('import heapq\n'
                           'class Box:\n'
                           '    def __init__(self,value):self.data={0:value}\n'
                           "box=Box(float('nan'))\n"
                           'copy=box.data.copy()\n'
                           'queue=[(box.data[0],2),(copy[0],1)]\n'
                           'heapq.heapify(queue)\n'
                           'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                           ('',)),
 'conversion_error_order': ('import heapq\n'
                            "value=float('nan')\n"
                            'queue=[(value,2),(value,1)]\n'
                            'heapq.heapify(queue)\n'
                            "print('before')\n"
                            'print(int(value))\n',
                            ('',)),
 'float_relations': ('import heapq\n'
                     "value=float('nan')\n"
                     "other=float('nan')\n"
                     'a=(value,1)\n'
                     'b=(value,2)\n'
                     'c=(other,2)\n'
                     'print(a==a,a!=a,a<a,a<=a,a>a,a>=a)\n'
                     'print(a==b,a!=b,a<b,a<=b,a>b,a>=b)\n'
                     'print(a==c,a!=c,a<c,a<=c,a>c,a>=c)\n'
                     'first=[value,1]\n'
                     'second=[value,2]\n'
                     'print(first<second,first<=second,first>second,first>=second)\n',
                     ('',)),
 'mapped_text_fresh': ('import heapq\n'
                       'convert=float\n'
                       "values=list(map(convert,['nan','nan']))\n"
                       'queue=[(values[0],2),(values[0],1),(values[1],3)]\n'
                       'heapq.heapify(queue)\n'
                       'print([heapq.heappop(queue)[1]for _ in range(3)])\n',
                       ('',)),
 'mapped_existing_alias': ('import heapq\n'
                           "shared=float('nan')\n"
                           'values=list(map(float,[shared,shared]))\n'
                           'queue=[(values[0],2),(values[1],1)]\n'
                           'heapq.heapify(queue)\n'
                           'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                           ('',)),
 'mapped_byte_input_fresh': ('import sys,heapq\n'
                             'values=list(map(float,sys.stdin.buffer.readline().split()))\n'
                             'queue=[(values[0],2),(values[0],1),(values[1],3)]\n'
                             'heapq.heapify(queue)\n'
                             'print([heapq.heappop(queue)[1]for _ in range(3)])\n',
                             ('nan nan\n',)),
 'scalar_nan_membership': ('import heapq\n'
                           "shared=float('nan')\n"
                           'queue=[(shared,2),(shared,1)]\n'
                           'heapq.heapify(queue)\n'
                           "print(shared==shared,shared in [shared],float('nan') in "
                           '[shared],shared in (shared,))\n',
                           ('',)),
 'ordinary_float_container': ('values=[(2.0,1),(1.0,2)]\n'
                              'print(values==values,values[0]<values[1])\n',
                              ('',)),
 'float_field_rebind': ('import heapq\n'
                        'class Box:\n'
                        ' def __init__(self,value):self.value=value\n'
                        ' def change(self,value):self.value=value\n'
                        "box=Box(float('nan'))\n"
                        'first=box.value\n'
                        "box.change(float('nan'))\n"
                        'queue=[(first,1),(box.value,2),(float(box.value),3)]\n'
                        'heapq.heapify(queue)\n'
                        'print([heapq.heappop(queue)[1]for _ in range(3)])\n',
                        ('',)),
 'float_key_selection': ('import heapq\n'
                         "shared=float('nan')\n"
                         'values=[(2,shared),(1,shared)]\n'
                         'first=min(values,key=lambda item:item[0])\n'
                         'second=max(values,key=lambda item:item[0])\n'
                         'queue=[(first[1],2),(second[1],1)]\n'
                         'heapq.heapify(queue)\n'
                         'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                         ('',)),
 'canonical_alias': ('import heapq as module\n'
                     'prepare=module.heapify\n'
                     'pop=module.heappop\n'
                     "value=float('nan')\n"
                     'queue=[(value,2),(value,1)]\n'
                     'prepare(queue)\n'
                     'print(pop(queue)[1],pop(queue)[1])\n',
                     ('',)),
 'iterator_repeat_alias': ('import heapq\n'
                           'from itertools import repeat\n'
                           "value=float('nan')\n"
                           'values=list(repeat(value,2))\n'
                           'queue=list(zip(values,[2,1]))\n'
                           'heapq.heapify(queue)\n'
                           'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                           ('',)),
 'iterator_accumulate_fresh': ('import heapq\n'
                               'from itertools import accumulate\n'
                               "value=float('nan')\n"
                               'values=list(accumulate([value,0.0]))\n'
                               'queue=list(zip(values,[2,1]))\n'
                               'heapq.heapify(queue)\n'
                               'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                               ('',)),
 'membership_alias': ('import heapq\n'
                      "value=float('nan')\n"
                      'values=[value]\n'
                      "print(value in values,float('nan') in values,value in (value,),float('nan') "
                      'not in (value,))\n'
                      'queue=[(value,2),(value,1)]\n'
                      'heapq.heapify(queue)\n'
                      'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                      ('',)),
 'float_conversion_error': ('import heapq\n'
                            "value=float('nan')\n"
                            "print('before')\n"
                            'print(int(value))\n'
                            'queue=[(value,2),(value,1)]\n'
                            'heapq.heapify(queue)\n',
                            ('',)),
 'lambda_return_alias': ('import heapq\n'
                         "value=float('nan')\n"
                         'get=lambda:value\n'
                         'queue=[(get(),2),(get(),1)]\n'
                         'heapq.heapify(queue)\n'
                         'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                         ('',))}

CASES.update({'format_observer': ('import heapq\n'
                     "value=float('nan')\n"
                     'queue=[(value,2),(value,1)]\n'
                     'heapq.heapify(queue)\n'
                     'def specification():\n'
                     " print('specification')\n"
                     " return '.2f'\n"
                     "print(f'{value:.3f}|{1.25:>8.2f}|{value!r}|{value!s}')\n"
                     'print(f\'{float("inf"):{specification()}}\')\n'
                     'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                     ('',)),
 'format_observer_error': ('import heapq\n'
                           "value=float('nan')\n"
                           'queue=[(value,2),(value,1)]\n'
                           'heapq.heapify(queue)\n'
                           'def specification():\n'
                           " print('specification')\n"
                           " return 'bad-format'\n"
                           "print('before')\n"
                           "print(f'{value:{specification()}}')\n",
                           ('',))})

BOUNDARIES={'constant_nan_origin': ('import heapq\n'
                         'def get():return 1e400-1e400\n'
                         'q=[(get(),2),(get(),1)]\n'
                         'heapq.heapify(q)\n'
                         'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                         'constant'),
 'math_nan_origin': ('import heapq\n'
                     'import math\n'
                     'q=[(math.nan,2),(math.nan,1)]\n'
                     'heapq.heapify(q)\n'
                     'print([heapq.heappop(q)[1] for _ in range(2)])\n',
                     'math'),
 'float_sum_boundary': ('import heapq\n'
                        "value=float('nan')\n"
                        'queue=[(value,2),(value,1)]\n'
                        'heapq.heapify(queue)\n'
                        'print(sum([value]))\n',
                        'sum'),
 'float_sum_start_boundary': ('import heapq\n'
                              "value=float('nan')\n"
                              'queue=[(value,2),(value,1)]\n'
                              'heapq.heapify(queue)\n'
                              'print(sum([],value))\n',
                              'sum'),
 'integral_power_boundary': ('import heapq\n'
                             "value=float('nan')\n"
                             'queue=[(value,2),(value,1)]\n'
                             'heapq.heapify(queue)\n'
                             'print(2**-1)\n',
                             'power'),
 'float_power_boundary': ('import heapq\n'
                          "value=float('nan')\n"
                          'queue=[(value,2),(value,1)]\n'
                          'heapq.heapify(queue)\n'
                          'print(2.0**2)\n',
                          'power'),
 'round_boundary': ('import heapq\n'
                    "value=float('nan')\n"
                    'queue=[(value,2),(value,1)]\n'
                    'heapq.heapify(queue)\n'
                    'print(round(1.25,1))\n',
                    'round'),
 'format_boundary': ('import heapq\n'
                     "value=float('nan')\n"
                     'queue=[(value,2),(value,1)]\n'
                     'heapq.heapify(queue)\n'
                     'print(format(value))\n',
                     'format'),
 'float_divmod_boundary': ('import heapq\n'
                           "value=float('nan')\n"
                           'queue=[(value,2),(value,1)]\n'
                           'heapq.heapify(queue)\n'
                           'print(divmod(value,2.0))\n',
                           'divmod'),
 'list_float_sort_boundary': ('import heapq\n'
                              "shared=float('nan')\n"
                              'queue=[(shared,2),(shared,1)]\n'
                              'heapq.heapify(queue)\n'
                              'print(sorted([shared,shared]))\n',
                              'NaN'),
 'unproved_math_producer': ('import heapq\n'
                            'import math\n'
                            "value=math.sqrt(float('nan'))\n"
                            'queue=[(value,2),(value,1)]\n'
                            'heapq.heapify(queue)\n'
                            'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                            'math'),
 'unproved_array_producer': ('import heapq\n'
                             'from array import array\n'
                             "values=array('d',[float('nan')])\n"
                             'queue=[(values[0],2),(values[0],1)]\n'
                             'heapq.heapify(queue)\n'
                             'print([heapq.heappop(queue)[1]for _ in range(2)])\n',
                             'array'),
 'explicit_float_identity_boundary': ('import heapq\n'
                                      "value=float('nan')\n"
                                      'print(value is value)\n'
                                      'queue=[(value,2),(value,1)]\n'
                                      'heapq.heapify(queue)\n',
                                      'identity')}

CONTROLS={'shadowed_heap_name': 'from heapq import heapify\n'
                       'def heapify(values):return len(values)\n'
                       "print(heapify([(float('nan'),1)]))\n",
 'unused_heap_function': 'import heapq\n'
                         'def unused():\n'
                         "    heapq.heapify([(float('nan'),1)])\n"
                         'print(1.5+2.5)\n',
 'empty_heap': 'import heapq\n'
               'values=[]\n'
               'heapq.heapify(values)\n'
               "print(len(values),float('inf')>1.0)\n",
 'rebound_heap_alias': 'from heapq import heapify as operation\n'
                       'def local(values):return len(values)\n'
                       'operation=local\n'
                       "print(operation([(float('nan'),1)]))\n",
 'plain_float_class': 'class Box:\n'
                      '    def __init__(self,value):self.value=value\n'
                      "box=Box(float('nan'))\n"
                      'print(box.value==box.value,abs(-1.25),float(3))\n',
 'unreached_comparison': 'def unused():\n'
                         "    value=float('nan')\n"
                         '    return (value,1)==(value,1)\n'
                         'print(1.5+2.5)\n'}

class FloatIdentityProofTests(unittest.TestCase):
    def test_unproved_producers_have_positioned_capability_diagnostics(self):
        for name,(source,reason)in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none'))
                    self.assertFalse(result.success,result.diagnostics)
                    self.assertTrue(any(d.code=='E006'and d.line>0 and reason.lower()in d.message.lower()for d in result.diagnostics),result.diagnostics)

    def test_other_float_programs_do_not_acquire_identity_storage(self):
        for name,source in CONTROLS.items():
            with self.subTest(name=name):
                result=transpile(source,TranspileOptions(license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertNotIn('NativeIdentityFloat',result.rust_source)
                self.assertNotIn('NATIVE_FLOAT_IDENTITY',result.rust_source)

    def test_bare_bigint_float_heap_retains_its_exact_comparison_boundary(self):
        source=CASES['bare_mixed_bisect'][0].split('from bisect')[0]+"values=[9007199254740993,9007199254740992.0]\nheapq.heapify(values)\n"
        result=transpile(source,TranspileOptions(integer='bigint'))
        self.assertFalse(result.success)
        self.assertTrue(any(d.code=='E006'and 'BigInt/float' in d.message for d in result.diagnostics),result.diagnostics)

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FloatIdentityExecutionTests(unittest.TestCase):
    def check(self,name):
        source,inputs=CASES[name]
        execution.HeapExecutionTests.compare(self,source,inputs)

    def test_checked_nan_ids_leave_ordinary_values_unallocated(self):
        source='trait ClassDisplay{fn class_str(&self)->String;}\nfn native_float_text(value:f64)->String{value.to_string()}\n'+RUNTIME+r"""
fn main(){
    let ordinary=native_identity_float(1.5).unwrap();
    assert_eq!(ordinary.nan_identity,0);
    NATIVE_FLOAT_IDENTITY.with(|counter|assert_eq!(counter.get(),0));
    let first=native_identity_float(f64::NAN).unwrap();
    let alias=first;
    let second=native_identity_float(f64::NAN).unwrap();
    assert_eq!(first.nan_identity,alias.nan_identity);
    assert_ne!(first.nan_identity,second.nan_identity);
    assert!(!(first==alias));
    NATIVE_FLOAT_IDENTITY.with(|counter|counter.set(usize::MAX));
    assert_eq!(native_identity_float(0.0).unwrap().nan_identity,0);
    assert_eq!(native_identity_float(f64::NAN).err().unwrap(),"MemoryError: float identity capacity");
}
"""
        with tempfile.TemporaryDirectory(prefix='pytors-float-identity-')as directory:
            path=Path(directory)/'main.rs';path.write_text(source)
            for release in (False,True):
                binary=Path(directory)/str(release)
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                ran=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10)
                self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(0,'',''))

    def test_shared_nan_heap(self):
        self.check('shared_nan_heap')

    def test_distinct_nan_heap(self):
        self.check('distinct_nan_heap')

    def test_conversion_plus_alias(self):
        self.check('conversion_plus_alias')

    def test_negative_abs_fresh(self):
        self.check('negative_abs_fresh')

    def test_arithmetic_nan_fresh(self):
        self.check('arithmetic_nan_fresh')

    def test_precision_and_tie(self):
        self.check('precision_and_tie')

    def test_signed_zero_infinities(self):
        self.check('signed_zero_infinities')

    def test_input_conversion_alias(self):
        self.check('input_conversion_alias')

    def test_nested_lists_and_tuples(self):
        self.check('nested_lists_and_tuples')

    def test_default_object_alias(self):
        self.check('default_object_alias')

    def test_closure_object_alias(self):
        self.check('closure_object_alias')

    def test_all_core_min_max(self):
        self.check('all_core_min_max')

    def test_division_floor_mod_fresh(self):
        self.check('division_floor_mod_fresh')

    def test_min_max_return_alias(self):
        self.check('min_max_return_alias')

    def test_bytes_bytearray_text(self):
        self.check('bytes_bytearray_text')

    def test_iterator_tuple_alias(self):
        self.check('iterator_tuple_alias')

    def test_augmented_field_fresh(self):
        self.check('augmented_field_fresh')

    def test_bare_mixed_bisect(self):
        self.check('bare_mixed_bisect')

    def test_dictionary_copy_alias(self):
        self.check('dictionary_copy_alias')

    def test_conversion_error_order(self):
        self.check('conversion_error_order')

    def test_float_relations(self):
        self.check('float_relations')

    def test_mapped_text_fresh(self):
        self.check('mapped_text_fresh')

    def test_mapped_existing_alias(self):
        self.check('mapped_existing_alias')

    def test_mapped_byte_input_fresh(self):
        self.check('mapped_byte_input_fresh')

    def test_scalar_nan_membership(self):
        self.check('scalar_nan_membership')

    def test_ordinary_float_container(self):
        self.check('ordinary_float_container')

    def test_float_field_rebind(self):
        self.check('float_field_rebind')

    def test_float_key_selection(self):
        self.check('float_key_selection')

    def test_canonical_alias(self):
        self.check('canonical_alias')

    def test_iterator_repeat_alias(self):
        self.check('iterator_repeat_alias')

    def test_iterator_accumulate_fresh(self):
        self.check('iterator_accumulate_fresh')

    def test_membership_alias(self):
        self.check('membership_alias')

    def test_float_conversion_error(self):
        self.check('float_conversion_error')

    def test_lambda_return_alias(self):
        self.check('lambda_return_alias')

    def test_format_observer(self):
        self.check('format_observer')

    def test_format_observer_error(self):
        self.check('format_observer_error')

if __name__=='__main__':unittest.main()
