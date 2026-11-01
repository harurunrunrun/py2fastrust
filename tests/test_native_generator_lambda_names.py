"""Generator lexical qualification is retained in actual Python binding errors."""
import unittest
import test_native_explicit_raise as raise_tests
CASES={'module_missing_lambda_argument': 'functions=list(lambda value:value for '
                                   'unused in range(1))\n'
                                   'functions[0]()\n',
 'module_extra_lambda_argument': 'functions=list(lambda:7 for unused in '
                                 'range(1))\n'
                                 'functions[0](1)\n',
 'function_nested_lambda_argument': 'def make():\n'
                                    ' return list(lambda value:value for '
                                    'unused in range(1))\n'
                                    'functions=make()\n'
                                    'functions[0](bad=1)\n',
 'nested_generator_lambda_argument': 'groups=list(list(lambda value:value for '
                                     'unused in range(1))for outer in '
                                     'range(1))\n'
                                     'groups[0][0]()\n'}
class GeneratorLambdaNames(unittest.TestCase):
    def test_module_missing_lambda_argument(self):raise_tests.NativeRaiseExecutionTests.exercise(self,CASES['module_missing_lambda_argument'],'')
    def test_module_extra_lambda_argument(self):raise_tests.NativeRaiseExecutionTests.exercise(self,CASES['module_extra_lambda_argument'],'')
    def test_function_nested_lambda_argument(self):raise_tests.NativeRaiseExecutionTests.exercise(self,CASES['function_nested_lambda_argument'],'')
    def test_nested_generator_lambda_argument(self):raise_tests.NativeRaiseExecutionTests.exercise(self,CASES['nested_generator_lambda_argument'],'')
