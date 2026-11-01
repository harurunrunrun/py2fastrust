"""Original generator lexical cells retain ordinary lambda identities/defaults."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
CASES={'immediate_lambda_in_generator': 'print(sum((lambda value:value*3)(value)for '
                                  'value in range(4)))\n',
 'map_lambda_inside_generator': 'rows=[[1,2],[3,4]]\n'
                                'print(sum(sum(map(lambda '
                                'value:value*2,row))for row in rows))\n',
 'escaped_generator_target_cells': 'functions=list(lambda:value for value in '
                                   'range(3))\n'
                                   'print([function()for function in '
                                   'functions])\n',
 'per_definition_default_snapshot': 'functions=list(lambda value=value:value '
                                    'for value in range(3))\n'
                                    'print([function()for function in '
                                    'functions])\n',
 'fresh_lambda_identity': 'functions=list(lambda:7 for unused in range(2))\n'
                          'print(functions[0]is '
                          'functions[1],functions[0]==functions[1])\n',
 'returned_closures_keep_parent_cells': 'def make(offset):\n'
                                        ' functions=list(lambda:offset+value '
                                        'for value in range(3))\n'
                                        ' offset+=1\n'
                                        ' return functions\n'
                                        'functions=make(5)\n'
                                        'print([function()for function in '
                                        'functions])\n',
 'multiple_clause_late_binding': 'functions=list(lambda:a+b for a in '
                                 'range(2)for b in range(3))\n'
                                 'print([function()for function in '
                                 'functions])\n',
 'nested_generator_environments': 'groups=list(list(lambda:value for value in '
                                  'range(base))for base in [2,3])\n'
                                  'print([[function()for function in group]for '
                                  'group in groups])\n',
 'creation_after_later_argument': 'offset=2\n'
                                  'def later():\n'
                                  ' global offset\n'
                                  ' offset=5\n'
                                  ' return 0\n'
                                  'print(sum(((lambda '
                                  'value:value+offset)(value)for value in '
                                  'range(2)),later()))\n',
 'inline_comprehension_inside_generator': 'print(sum(sum(function()for '
                                          'function in [lambda:value for value '
                                          'in range(3)])for unused in '
                                          'range(2)))\n',
 'default_side_effects_at_each_creation': 'def mark(value):\n'
                                          ' print("default",value)\n'
                                          ' return value\n'
                                          'functions=list(lambda '
                                          'value=mark(value):value for value '
                                          'in range(3))\n'
                                          'print([function()for function in '
                                          'functions])\n',
 'empty_source_no_creation_effects': 'def mark(value):\n'
                                     ' print("unreachable")\n'
                                     ' return value\n'
                                     'print(list(lambda value=mark(1):value '
                                     'for unused in range(0)))\n',
 'same_line_distinct_lambda_calls': 'print(sum((lambda '
                                    'value:value)(value)+(lambda '
                                    'value:value*2)(value)for value in '
                                    'range(3)))\n',
 'function_default_outer_capture': 'def make(offset):\n'
                                   ' return list(lambda '
                                   'extra=offset:extra+value for value in '
                                   'range(2))\n'
                                   'print([function()for function in '
                                   'make(8)])\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class GeneratorLambdaScopes(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_immediate_lambda_in_generator(self):self.check('immediate_lambda_in_generator')
    def test_map_lambda_inside_generator(self):self.check('map_lambda_inside_generator')
    def test_escaped_generator_target_cells(self):self.check('escaped_generator_target_cells')
    def test_per_definition_default_snapshot(self):self.check('per_definition_default_snapshot')
    def test_fresh_lambda_identity(self):self.check('fresh_lambda_identity')
    def test_returned_closures_keep_parent_cells(self):self.check('returned_closures_keep_parent_cells')
    def test_multiple_clause_late_binding(self):self.check('multiple_clause_late_binding')
    def test_nested_generator_environments(self):self.check('nested_generator_environments')
    def test_creation_after_later_argument(self):self.check('creation_after_later_argument')
    def test_inline_comprehension_inside_generator(self):self.check('inline_comprehension_inside_generator')
    def test_default_side_effects_at_each_creation(self):self.check('default_side_effects_at_each_creation')
    def test_empty_source_retains_function_display_boundary(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['empty_source_no_creation_effects'],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006' and d.line>0 and 'function-object display protocol'in d.message for d in result.diagnostics),result.diagnostics)
    def test_same_line_distinct_lambda_calls(self):self.check('same_line_distinct_lambda_calls')
    def test_function_default_outer_capture(self):self.check('function_default_outer_capture')
