"""Boolean bitwise results agree across AOT, dynamic code and integer modes."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


FIXTURE = '''
def describe(value):
    return type(value).__name__, value, value is True, value is False

for left in [False, True]:
    for right in [False, True]:
        print(describe(left & right), describe(left | right), describe(left ^ right))
        print(describe((not left) & right), describe((left | right) ^ left))
        for number in [0, 1, 2, -1]:
            print(describe(left & number), describe(number & left),
                  describe(left | number), describe(number | left),
                  describe(left ^ number), describe(number ^ left))
        value = left
        value &= right
        print(describe(value))
        value |= left
        print(describe(value))
        value ^= right
        print(describe(value))
        for owner in [bool, int]:
            for name in ['__and__', '__rand__', '__or__', '__ror__', '__xor__', '__rxor__']:
                method = getattr(owner, name)
                print(owner.__name__, name, describe(method(left, right)),
                      describe(method(left, 2)), method(left, None) is NotImplemented)

print(bool.__and__ is int.__and__, describe((True).__and__(False)))
try:
    bool.__and__(1, True)
except TypeError:
    print('bool receiver checked')

class Integer(int):
    pass

print(describe(True & Integer(1)), describe(Integer(1) & True),
      describe(Integer.__and__(True, False)))
'''


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class BooleanValueTests(unittest.TestCase):
    def test_aot_and_dynamic_results_in_every_integer_and_build_mode(self):
        source = FIXTURE + '\nexec(' + repr(FIXTURE) + ', {})\n'
        expected = subprocess.run([sys.executable, '-I', '-c', source],
                                  capture_output=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        with tempfile.TemporaryDirectory(prefix='pytors-boolean-values-') as directory:
            root = Path(directory)
            for integer in ['i64', 'i128', 'bigint']:
                result = transpile(source, TranspileOptions(integer=integer, optimize=False))
                self.assertTrue(result.success, result.diagnostics)
                target = root / (integer + '.rs')
                target.write_text(result.rust_source, encoding='utf-8')
                for release in [False, True]:
                    with self.subTest(integer=integer, release=release):
                        binary = root / (integer + ('-release' if release else '-debug'))
                        built = subprocess.run(
                            ['rustc', '--edition=2021', *(['-O'] if release else []),
                             str(target), '-o', str(binary)],
                            capture_output=True, timeout=240,
                        )
                        self.assertEqual(built.returncode, 0, built.stderr.decode(errors='replace'))
                        actual = subprocess.run([str(binary)], capture_output=True, timeout=20,
                                                env={**os.environ, 'PATH': str(root / 'no-executables')})
                        self.assertEqual(actual.returncode, 0, actual.stderr.decode(errors='replace'))
                        self.assertEqual(actual.stdout, expected.stdout,
                                         actual.stderr.decode(errors='replace'))
