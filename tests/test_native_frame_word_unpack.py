"""Frame input unpacking preserves eager split and lazy conversion order."""
import shutil
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_unpack_exact_lengths as execution


class FrameWordUnpackSelection(unittest.TestCase):
    def test_fixed_arity_words_use_stack_storage_on_class_frames(self):
        for mode in ('i64','i128','bigint'):
            source='class Marker:pass\na,b=map(int,input().split())\nprint(a,b)\n'
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('Option<(usize,usize)>;3',result.rust_source)
            self.assertNotIn('Vec::<(usize,usize)>::new()',result.rust_source)

    def test_custom_truth_protocol_still_has_an_explicit_diagnostic(self):
        source='class Bad:\n def __bool__(self):\n  raise ValueError("strict first")\na,b=map(int,input().split(),strict=Bad())\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertIn('__bool__',str(result.diagnostics[0]))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrameWordUnpackExecution(execution.ExactUnpackLengthTests):
    def test_eager_lengths_and_lazy_error_order(self):
        prefix='class Marker:pass\n'
        mark='def mark():\n print("strict",end="|")\n return False\n'
        strict=prefix+mark+'a,b=map(int,input().split(),strict=mark())\nprint(a,b)\n'
        bad=prefix+'def fail():\n print("strict",end="|")\n raise ValueError("strict first")\n'
        cases=(
            ('empty',prefix+'a,b=map(int,input().split())\n','\n'),
            ('short',prefix+'a,b=map(int,input().split())\n','1\n'),
            ('exact',prefix+'a,b=map(int,input().split())\nprint(a,b)\n','1 2\n'),
            ('invalid_extra',prefix+'a,b=map(int,input().split())\n','1 2 bad 4\n'),
            ('stop_before_fourth',prefix+'a,b=map(int,input().split())\n','1 2 3 bad\n'),
            ('reverse_first',prefix+'a,b=map(int,input().rsplit())\n','bad 2 3 4 5 6\n'),
            ('reverse_extra',prefix+'a,b=map(int,input().rsplit())\n','1 2 3 bad 5 6\n'),
            ('separator',prefix+'a,b=map(int,input().split(","))\n','1,,2\n'),
            ('strict_order',strict,'1 2 bad 4\n'),
            ('strict_success',strict,'1 2\n'),
            ('split_precedes_keyword',prefix+mark+'a,b=map(int,input().split(""),strict=mark())\n','1 2\n'),
            ('strict_value_precedes_parse',bad+'a,b=map(int,input().split(),strict=fail())\n','bad 2\n'),
            ('bytes_reverse',prefix+'import sys\na,b=map(int,sys.stdin.buffer.readline().rsplit())\n','1 2 3 bad\n'),
            ('bad_separator_type',prefix+'a,b=map(int,input().split(3))\n','1 2\n'),
            ('union_separator',prefix+'separator=None if int(input())else 3\na,b=map(int,input().split(separator))\n','0\n1 2\n'),
        )
        original=execution.CASES
        try:
            execution.CASES=cases
            super().test_eager_lengths_and_lazy_error_order()
        finally:
            execution.CASES=original


if __name__=='__main__':
    unittest.main()
