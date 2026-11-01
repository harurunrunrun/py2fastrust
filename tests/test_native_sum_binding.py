"""Canonical sum signatures retain captured argument order and keyword starts."""
import shutil,unittest
from tests import test_native_finite_tuple_unpacking as helpers

CASES={'keyword_start': 'class Scope:pass\nprint(sum([1,2,3],start=7))\n',
 'captured_alias': 'fold=sum\nprint(fold([1,2],start=4))\n',
 'higher_order': 'def run(fn):return fn([2,3],start=6)\nprint(run(sum))\n',
 'empty_bool_start': 'class Scope:pass\nvalue=sum([],start=True)\nprint(value,value is True)\n',
 'bool_items': 'class Scope:pass\nprint(sum([True,False,True],start=True))\n',
 'generator_order': 'class Scope:pass\n'
                    "def mark(value):print('argument',value);return value\n"
                    'print(sum((mark(x)for x in[mark(1),mark(2)]),start=mark(20)))\n',
 'default_and_keyword_order': 'class Scope:pass\n'
                              "def mark(value):print('argument',value);return value\n"
                              'print(sum((mark(x)for x in range(mark(3))),start=mark(10)))\n',
 'body_raises_after_start': 'class Scope:pass\n'
                            "def mark(value):print('argument',value);return value\n"
                            'print(sum((10//x for x in[1,0]),start=mark(4)))\n',
 'shadowed_function': 'def sum(values,start=0):return start-5\nprint(sum([],start=7))\n',
 'from_builtins': 'from builtins import sum as fold\nprint(fold([3,4],start=2))\n',
 'empty_no_start': 'class Scope:pass\nprint(sum([]))\n',
 'positional_start': 'class Scope:pass\nprint(sum([1,2],5))\n',
 'missing': 'class Scope:pass\nsum()\n',
 'start_without_iterable': 'class Scope:pass\n'
                           "def mark(value):print('argument',value);return value\n"
                           'sum(start=mark(4))\n',
 'iterable_keyword': 'class Scope:pass\n'
                     "def mark(value):print('argument',value);return value\n"
                     'sum(iterable=mark([1]),start=mark(4))\n',
 'unknown_keyword': 'class Scope:pass\n'
                    "def mark(value):print('argument',value);return value\n"
                    'sum(mark([1]),extra=mark(4))\n',
 'duplicate_start': 'class Scope:pass\n'
                    "def mark(value):print('argument',value);return value\n"
                    'sum(mark([1]),mark(2),start=mark(3))\n',
 'too_many': 'class Scope:pass\n'
             "def mark(value):print('argument',value);return value\n"
             'sum(mark([1]),mark(2),mark(3))\n',
 'too_many_with_unknown': 'class Scope:pass\n'
                          "def mark(value):print('argument',value);return value\n"
                          'sum(mark([1]),mark(2),mark(3),extra=mark(4))\n',
 'unknown_and_duplicate': 'class Scope:pass\n'
                          "def mark(value):print('argument',value);return value\n"
                          'sum(mark([1]),mark(2),extra=mark(3),start=mark(4))\n',
 'only_unknown': 'class Scope:pass\n'
                 "def mark(value):print('argument',value);return value\n"
                 'sum(extra=mark(3))\n',
 'two_unknown': 'class Scope:pass\n'
                "def mark(value):print('argument',value);return value\n"
                'sum(mark([1]),first=mark(2),second=mark(3))\n',
 'empty_generator_argument_error': 'class Scope:pass\n'
                                   "def mark(value):print('argument',value);return value\n"
                                   'sum((mark(x)for x in[mark(1)]),extra=mark(2))\n',
 'alias_binding_error': 'fold=sum\n'
                        "def mark(value):print('argument',value);return value\n"
                        'fold(mark([1]),mark(2),start=mark(3))\n'}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeSumBindingTests(unittest.TestCase):
    exercise=helpers.FiniteTupleUnpackExecutionTests.exercise


def _case(source):
    def test(self):self.exercise(source,"")
    return test


for _name,_source in CASES.items():setattr(NativeSumBindingTests,"test_"+_name,_case(_source))
