"""Loop targets keep entry values on zero iterations and distinct exits."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


CASES = (
    ('exact_prior_boolean_empty_enumerate',
     '''i=77
value=False
for i,value in enumerate([]):
 value=99
 break
else:
 print(i,value)
print(i,value)
''',
     ('',)),
    ('prior_bool_dynamic_break',
     '''value=False
for value in range(int(input())):
 if value==1:break
else:print("else",value)
print("after",value)
''',
     ('0\n', '1\n', '2\n')),
    ('no_else_map_zero_or_nonempty',
     '''value=False
for value in map(int,input().split()):value+=1
print(value)
''',
     ('\n', '2\n')),
    ('prior_string_empty_enumerate',
     '''i="index"
value="value"
for i,value in enumerate([]):
 value=99
 break
else:print(i,value)
print(i,value)
''',
     ('',)),
    ('prior_none_empty_zip',
     '''value=None
for value in zip([],[]):
 value=(1,2)
 break
else:print(value)
print(value)
''',
     ('',)),
    ('partly_defined_tuple_target',
     '''left=5
for left,right in zip([],[]):pass
else:print(left)
print(right)
''',
     ('',)),
    ('prior_mutable_alias',
     '''value=[9]
original=value
for value in enumerate([]):
 value=[3]
 break
else:print(value is original,value)
print(value is original,original)
''',
     ('',)),
    ('else_replaces_binding',
     '''value=False
for value in enumerate([]):break
else:value="done"
print(value)
''',
     ('',)),
    ('return_body_zero_trip',
     '''def solve(data):
 value=False
 for value in data:return value
 else:print("empty",value)
 return value
print(solve([]))
print(solve([7]))
''',
     ('',)),
    ('continue_feedback',
     '''value=False
for value in range(int(input())):
 if value%2==0:continue
 value="odd"
else:print(value)
''',
     ('0\n', '1\n', '2\n')),
    ('target_deleted_on_break',
     '''value=10
for value in range(int(input())):
 del value
 break
else:print(value)
print(value)
''',
     ('0\n', '1\n')),
    ('nested_empty_loop',
     '''value=False
for outer in range(2):
 for value in enumerate([]):
  value=3
  break
 else:print(outer,value)
print(value)
''',
     ('',)),
    ('argument_target_presence',
     '''def run(value,data):
 for value in data:break
 else:print("else",value)
 return value
print(run(False,[]))
print(run(True,[5]))
''',
     ('',)),

)

UNSUPPORTED_UNPACK = 'for (x,) in [1]:pass\n'

def error_line(stderr):
    line = stderr.rstrip().splitlines()[-1] if stderr.strip() else ""
    # CP may append spelling suggestions while rendering a NameError; compare
    # its class and complete base message, without that optional hint.
    if line.startswith(("NameError:", "AttributeError:")):
        line = line.split(". Did you mean:", 1)[0]
    return line


def frames(stderr):
    return re.findall(r'File "([^"\n]+)", line (\d+), in ([^\n]+)', stderr)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ZeroTripLoopFlowTests(unittest.TestCase):
    def test_prior_bindings_targets_and_exhaustion_paths(self):
        for name, source, inputs in CASES:
            with self.subTest(source=name):
                self.exercise(source, inputs)

    def exercise(self, source, inputs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "main.py"
            main.write_text(source)
            references = [subprocess.run(
                [sys.executable, "-S", str(main)], input=data, text=True,
                capture_output=True, timeout=15,
            ) for data in inputs]
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(integer=integer):
                    result = transpile(source, TranspileOptions(
                        filename=str(main), integer=integer, license="none",
                    ))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    rust = root / (integer + ".rs")
                    rust.write_text(result.rust_source)
                    for optimized in (False, True):
                        with self.subTest(optimized=optimized):
                            binary = root / (integer + ("_release" if optimized else "_debug"))
                            built = subprocess.run(
                                ["rustc", "--edition=2021", "--crate-name", "zero_trip_flow",
                                 *(["-O"] if optimized else []), str(rust), "-o", str(binary)],
                                text=True, capture_output=True, timeout=180,
                            )
                            self.assertEqual(built.returncode, 0, built.stderr)
                            for data, expected in zip(inputs, references):
                                with self.subTest(stdin=data):
                                    actual = subprocess.run(
                                        [str(binary)], input=data, text=True,
                                        capture_output=True, timeout=15,
                                    )
                                    self.assertEqual(actual.stdout, expected.stdout)
                                    self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                                    self.assertEqual(frames(actual.stderr), frames(expected.stderr))
                                    self.assertEqual(error_line(actual.stderr), error_line(expected.stderr))

    def test_existing_noniterable_unpack_boundary_is_preserved(self):
        for integer in ("i64", "i128", "bigint"):
            with self.subTest(integer=integer):
                result = transpile(UNSUPPORTED_UNPACK, TranspileOptions(integer=integer))
                self.assertFalse(result.success)
                self.assertTrue(any(d.code == "E006" for d in result.diagnostics))


if __name__ == "__main__":
    unittest.main()
