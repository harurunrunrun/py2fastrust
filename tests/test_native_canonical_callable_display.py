"""Canonical callable display and float-only comparisons retain Python values."""
import unittest
import test_native_class_iterators as execution


CASES = {'builtin_containers': 'values=[abs,int,dict]\nprint(values,(min,max),[values])\n',
 'builtin_functions': 'print(abs,min,max,len,sum,print,input,sorted)\n',
 'builtin_types': 'print(int,bool,float,str,list,tuple,dict,set,range,map,zip,filter,enumerate)\n',
 'captured_display_after_rebinding': 'saved=abs\nabs=3\nprint(saved,abs)\n',
 'float_infinity_and_zero': 'class Marker:pass\n'
                            'a=1e400\n'
                            'b=-1e400\n'
                            'print(a>b,a>=a,a==a,a!=a,b<a,b<=a)\n'
                            'print(0.0==-0.0,0.0<-0.0,-0.0>0.0)\n',
 'float_relations': 'class Marker:pass\n'
                    'for a in [1.5,-3.0,2.5]:\n'
                    ' for b in [1.5,-3.0,2.5]:\n'
                    '  print(a<b,a<=b,a>b,a>=b,a==b,a!=b)\n',
 'native_members': 'import math\n'
                   'import sys\n'
                   'from collections import Counter\n'
                   'from itertools import accumulate,repeat\n'
                   'print(math.gcd,sys.getrecursionlimit,Counter,accumulate,repeat)\n'}


class CanonicalCallableDisplayTests(unittest.TestCase):
    cases=CASES
    check=execution.IteratorExecutionTests.check

    def test_canonical_callables_and_containers(self):
        for name in ('builtin_functions','builtin_types','builtin_containers','native_members','captured_display_after_rebinding'):
            with self.subTest(name=name):self.check(name)

    def test_float_only_ordering_all_integer_profiles(self):
        for name in ('float_relations','float_infinity_and_zero'):
            with self.subTest(name=name):self.check(name)


if __name__=='__main__':unittest.main()
