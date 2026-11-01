"""Independent CP comparisons for termination tuple and mapping payloads."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


CASES = (
    ('sys_dynamic_tuple',
     '''import sys
sys.exit(tuple(map(int,input().split())))
''',
     ('\n', '7\n', '7 8\n')),
    ('empty_element_tuple',
     '''import sys
sys.exit(tuple([]))
''',
     ('',)),
    ('none_element_tuple',
     '''import sys
sys.exit(tuple([None]))
''',
     ('',)),
    ('bool_element_tuple',
     '''import sys
sys.exit(tuple([True]))
''',
     ('',)),
    ('nested_empty_tuple',
     '''import sys
sys.exit(tuple([()]))
''',
     ('',)),
    ('nested_single_tuple',
     '''import sys
sys.exit(tuple([(7,)]))
''',
     ('',)),
    ('shared_list_element',
     '''import sys
values=[1]
class Change:
 def __enter__(self):return self
 def __exit__(self,a,b,c):values.append(2);return False
with Change():sys.exit(tuple([values]))
''',
     ('',)),
    ('site_empty_dict',
     '''exit({})
''',
     ('',)),
    ('sys_empty_dict',
     '''import sys
sys.exit({})
''',
     ('',)),
    ('sys_nonempty_dict',
     '''import sys
sys.exit({"a":[1]})
''',
     ('',)),
    ('sys_mapping_cleanup_mutation',
     '''import sys
payload={}
class Change:
 def __enter__(self):return self
 def __exit__(self,a,b,c):payload["a"]=[1,2];return False
with Change():sys.exit(payload)
''',
     ('',)),

)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExitPayloadExecutionTests(unittest.TestCase):
    def test_runtime_tuple_and_mapping_payloads(self):
        for name, source, inputs in CASES:
            with self.subTest(source=name):
                self.exercise(source, inputs)

    def exercise(self, source, inputs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "main.py"
            main.write_text(source)
            # Site must be enabled: exit and quit are actual Quitter objects.
            references = [subprocess.run(
                [sys.executable, str(main)], input=data, text=True,
                capture_output=True, timeout=15,
            ) for data in inputs]
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(integer=integer):
                    result = transpile(source, TranspileOptions(
                        filename=str(main), integer=integer, license="none",
                    ))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    self.assertLess(len(result.rust_source.encode()), 512 * 1024)
                    for marker in ("enum Value", "enum Op", "struct Runtime", "struct PegParser"):
                        self.assertNotIn(marker, result.rust_source)
                    rust = root / (integer + ".rs")
                    rust.write_text(result.rust_source)
                    for optimized in (False, True):
                        with self.subTest(optimized=optimized):
                            binary = root / (integer + ("_release" if optimized else "_debug"))
                            build = subprocess.run(
                                ["rustc", "--edition=2021", "--crate-name", "exit_payloads",
                                 *(["-O"] if optimized else []), str(rust), "-o", str(binary)],
                                text=True, capture_output=True, timeout=180,
                            )
                            self.assertEqual(build.returncode, 0, build.stderr)
                            for data, expected in zip(inputs, references):
                                with self.subTest(stdin=data):
                                    actual = subprocess.run(
                                        [str(binary)], input=data, text=True,
                                        capture_output=True, timeout=15,
                                        env={**os.environ, "PATH": "/no-python", "PYTHONPATH": "/no-python"},
                                    )
                                    self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                                    self.assertEqual(actual.stdout, expected.stdout)
                                    self.assertEqual(actual.stderr, expected.stderr)


if __name__ == "__main__":
    unittest.main()
