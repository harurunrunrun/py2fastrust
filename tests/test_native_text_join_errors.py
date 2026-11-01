"""Native builtin errors preserve join materialization priority and PEP479."""
import unittest,shutil
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests
CASES={'join_later_parse_error': 'def word(value):\n'
                           ' print(value,end="|")\n'
                           ' if value==3:return int("invalid")\n'
                           ' return value\n'
                           'print(":".join(map(word,[1,2,3])))\n',
 'join_later_division_error': 'def word(value):\n'
                              ' print(value,end="|")\n'
                              ' if value==3:return 1//(value-3)\n'
                              ' return value\n'
                              'print(":".join(map(word,[1,2,3])))\n',
 'join_builtin_callback_stop_resumes': 'def word(value):\n'
                                       ' print(value,end="|")\n'
                                       ' if value==2:return next(iter(()))\n'
                                       ' return str(value)\n'
                                       'it=map(word,[1,2,3])\n'
                                       'print(":".join(it))\n'
                                       'print(next(it))\n',
 'join_generator_builtin_stop_pep479': 'def word(value):\n'
                                       ' print(value,end="|")\n'
                                       ' if value==2:return next(iter(()))\n'
                                       ' return str(value)\n'
                                       'print(":".join(word(value)for value in '
                                       'range(4)))\n',
 'join_generator_later_parse_error': 'def word(value):\n'
                                     ' print(value,end="|")\n'
                                     ' if value==3:return int("invalid")\n'
                                     ' return value\n'
                                     'print(":".join(word(value)for value in '
                                     'range(4)))\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class JoinBuiltinErrors(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_join_later_parse_error(self):self.check('join_later_parse_error')
    def test_join_later_division_error(self):self.check('join_later_division_error')
    def test_join_builtin_callback_stop_resumes(self):self.check('join_builtin_callback_stop_resumes')
    def test_join_generator_later_parse_error(self):self.check('join_generator_later_parse_error')

class JoinGeneratorCause(unittest.TestCase):
    def test_original_pep479_source_has_complete_chain(self):
        import test_native_explicit_raise as raise_tests
        raise_tests.NativeRaiseExecutionTests.exercise(self,CASES['join_generator_builtin_stop_pep479'],'')
