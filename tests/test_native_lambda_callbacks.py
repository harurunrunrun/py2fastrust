"""Typed non-escaping lambda calls preserve defaults, scopes and evaluation."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeLambdaCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-lambda-")
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def exercise(self, source, inputs=("",)):
        references = [subprocess.run([sys.executable, "-I", "-c", source],
                      input=data, text=True, capture_output=True, timeout=10) for data in inputs]
        for mode in ("i64", "i128", "bigint"):
            result = transpile(source, TranspileOptions(integer=mode, filename="callback.py"))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native")
            for optimize in (False, True):
                key = (source, mode, optimize)
                if key not in self.cache:
                    name = hashlib.sha256(repr(key).encode()).hexdigest()
                    path = Path(self.directory.name) / (name + ".rs")
                    path.write_text(result.rust_source)
                    binary = path.with_suffix("")
                    built = subprocess.run(["rustc", "--edition=2021", "--crate-name", "callback",
                            *(["-O"] if optimize else []), str(path), "-o", str(binary)],
                            text=True, capture_output=True, timeout=120)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    self.cache[key] = binary
                for data, expected in zip(inputs, references):
                    with self.subTest(mode=mode, optimize=optimize, input=data):
                        actual = subprocess.run([str(self.cache[key])], input=data, text=True,
                                 capture_output=True, timeout=10,
                                 env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.stdout, expected.stdout)
                        self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                             expected.stderr.splitlines()[-1].split(":")[0])
                            pattern = r'File ".*?", line (\d+), in ([^\n]+)'
                            self.assertEqual(re.findall(pattern, actual.stderr),
                                             re.findall(pattern, expected.stderr))

    def test_sort_and_sorted_stable_tuple_keys(self):
        self.exercise('''values=[(2,0),(1,3),(2,4),(1,5)]
print(sorted(values,key=lambda pair:-pair[0]))
values.sort(key=lambda pair:(pair[0],-pair[1]),reverse=True)
print(values)
''')

    def test_live_immutable_capture_and_definition_time_defaults(self):
        self.exercise('''offset=int(input())
values=[-3,1,4,0]
values.sort(key=lambda value,origin=offset:abs(value-origin))
print(values,offset)
''', ("0\n", "3\n", "-4\n"))

    def test_defaults_execute_once_before_later_sort_arguments(self):
        self.exercise('''values=[3,1,2]
values.sort(key=lambda value,scale=int(input()):value*scale,reverse=bool(int(input())))
print(values)
''', ("2\n1\n", "-2\n0\n", "bad\n0\n"))

    def test_empty_sort_still_evaluates_lambda_defaults(self):
        self.exercise('''values=[]
values.sort(key=lambda value,scale=int(input()):value*scale)
print(values)
''', ("3\n", "bad\n", ""))

    def test_each_key_body_runs_once_in_original_order(self):
        self.exercise('''def mark(value):
 print(value)
 return -value
values=[3,1,2]
values.sort(key=lambda value:mark(value))
print(values)
''')

    def test_lambda_parameter_does_not_change_callee_globals(self):
        self.exercise('''def convert(value):return int(value)
values=[3,1,2]
values.sort(key=lambda int:convert(int))
print(values)
''')

    def test_callback_index_errors_have_lambda_frames(self):
        self.exercise('''index=int(input())
values=[(1,4),(3,2)]
values.sort(key=lambda value:value[index])
print(values)
''', ("0\n", "-1\n", "2\n"))

    def test_nested_immediate_lambda_and_keyword_binding(self):
        self.exercise('''value=int(input())
print((lambda first,/,second=5,*,factor=2:(first+second)*factor)(value,factor=3))
print((lambda outer:(lambda inner:outer+inner)(2))(value))
''', ("1\n", "-7\n"))

    def test_immediate_call_evaluates_defaults_then_arguments_in_source_order(self):
        self.exercise('''def mark(label,value):
 print(label)
 return value
answer=(lambda first,/,second=mark("D",2),*,third=mark("K",3):first+second+third)(mark("A",4),third=mark("C",5))
print(answer)
''')

    def test_borrowed_immutable_results_keep_outer_bindings(self):
        self.exercise('''text=b"abc"
print((lambda:text)(),text)
pair=(1,2)
print((lambda:pair)(),pair)
''')

    def test_out_of_place_sort_can_observe_its_original_input(self):
        self.exercise('''values=[3,1,2]
print(sorted(values,key=lambda item:len(values)))
''')

    def test_sorting_list_visibility_has_a_specific_boundary(self):
        result=transpile('values=[3,1,2]\nvalues.sort(key=lambda item:len(values))\n')
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,"E006")
        self.assertIn("temporary-empty",result.diagnostics[0].message)

    def test_binary_input_variable_tuples_and_lambda_sort_in_main(self):
        self.exercise('''import sys
def main():
 read=sys.stdin.buffer.readline
 count=int(read())
 rows=[tuple(map(int,read().split())) for _ in range(count)]
 rows.sort(key=lambda row:(-row[0],row[1]))
 for first,second in rows:
  print(first,second)
if __name__=="__main__":main()
''', ("0\n", "3\n2 9\n1 3\n2 4\n", "1\n5\n", "1\n2 3 4\n", "1\n2 invalid\n"))

    def test_print_captures_mutable_and_starred_arguments_in_order(self):
        self.exercise('''values=[1,2,3]
print(values,values.pop())
print(*values,values.pop())
print(values)
''')


if __name__ == "__main__":
    unittest.main()
