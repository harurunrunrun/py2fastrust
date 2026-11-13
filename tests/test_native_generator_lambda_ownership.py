"""Generator callable payloads retain actual parents and expose real cycles."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
CASES={'method_parent_retention': 'class Box:\n'
                            ' def __init__(self):self.scale=3\n'
                            ' def make(self):return '
                            'list(lambda:self.scale+value for value in '
                            'range(3))\n'
                            'box=Box()\n'
                            'functions=box.make()\n'
                            'box.scale=9\n'
                            'print([function()for function in functions])\n',
 'real_environment_cycle': 'def make():\n'
                           ' values=[]\n'
                           ' values.extend(lambda:values for unused in '
                           'range(2))\n'
                           ' return values\n'
                           'print(len(make()))\n'}
class GeneratorLambdaOwnership(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_method_parent_retention(self):self.check('method_parent_retention')
    def test_extend_keeps_separate_generator_consumer_boundary(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['real_environment_cycle'],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line==3
                                and 'list.extend'in d.message
                                and 'ordered iterable consumption and element conversion'in d.message
                                for d in result.diagnostics),result.diagnostics)
    def test_direct_collector_cycle_remains_named(self):
        source='def make():\n values=list(lambda:values for unused in range(2))\n return values\nprint(len(make()))\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006'and d.line>0 and 'cycle-safe lexical environment ownership'in d.message for d in result.diagnostics),result.diagnostics)
