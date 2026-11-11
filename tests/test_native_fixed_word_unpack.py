"""Fixed-width input unpacking uses stack storage and preserves lazy errors."""
import shutil
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_unpack_exact_lengths as execution


class FixedWordUnpackSelection(unittest.TestCase):
    def test_known_integer_word_arity_uses_stack_storage(self):
        for mode in ("i64", "i128", "bigint"):
            with self.subTest(integer=mode):
                result = transpile("a,b=map(int,input().split())\nprint(a+b)\n",
                    TranspileOptions(integer=mode, license="none"))
                self.assertTrue(result.success, result.diagnostics)
                self.assertIn("native_unpack_integer_words::<2,_,_,_>(", result.rust_source)
                self.assertNotIn("native_collect_integer_words(", result.rust_source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class FixedWordUnpackExecution(execution.ExactUnpackLengthTests):
    def test_eager_lengths_and_lazy_error_order(self):
        # The existing differential harness also compares source traceback frames.
        original = execution.CASES
        try:
            execution.CASES = (
                ("invalid_overflow_word", "a,b=map(int,input().split())\n", "1 2 invalid 4\n"),
                ("stop_before_fourth_word", "a,b=map(int,input().split())\n", "1 2 3 invalid\n"),
                ("empty", "a,b=map(int,input().split())\n", "\n"),
                ("short", "a,b=map(int,input().split())\n", "1\n"),
                ("function_frame", "def run():\n a,b=map(int,input().split())\n print(a,b)\nrun()\n", "1 invalid\n"),
            )
            super().test_eager_lengths_and_lazy_error_order()
        finally:
            execution.CASES = original


if __name__ == "__main__":
    unittest.main()
