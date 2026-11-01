"""Captured constructor capabilities name their remaining runtime protocols."""
import unittest
from py2fastrust import transpile,TranspileOptions
CASES={'non_none_initializer_result': 'class Item:\n'
                                ' def __init__(self,value):\n'
                                '  self.value=value\n'
                                '  return value\n'
                                'print(list(map(Item,[2])))\n',
 'named_tuple_callback': 'from typing import NamedTuple\n'
                         'class Point(NamedTuple):\n'
                         ' x:int\n'
                         'print([p.x for p in map(Point,[2,4])])\n'}
class ConstructorBoundaries(unittest.TestCase):
    def test_initializer_return_value_validation_is_named(self):
        self.check('non_none_initializer_result', 'initializer return-value validation')
    def test_nominal_tuple_callback_abi_is_named(self):
        self.check('named_tuple_callback', 'captured nominal tuple construction')
    def check(self,name,cause):
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006' and d.line>0 and cause in d.message for d in result.diagnostics),result.diagnostics)
