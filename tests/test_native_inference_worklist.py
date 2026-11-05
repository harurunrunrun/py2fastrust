"""Long dependency propagation and compact, source-faithful native calls."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_inference_worklist


def chain(count):
    return ('OFFSET=int(input())\n' +
            ''.join(f'def stage{i}(value):return stage{i+1}(value)+1\n' for i in range(count - 1)) +
            f'def stage{count-1}(value):return 10//value+OFFSET\n' +
            'print(stage0(int(input())))\n')


def field_chain(count):
    return ('class Holder:\n    def __init__(self, value):\n        self.value = value\n' +
            ''.join(f'def read_{i}(item):\n    return read_{i+1}(item) + 1\n' for i in range(count - 1)) +
            f'def read_{count-1}(item):\n    return item.value\n' +
            'print(read_0(Holder(int(input()))))\n')


EMPTY = '''OFFSET = 0
def count(values):
    return len(values) + OFFSET
print(count([]))
'''
HEAP = '''values = [0]
alias = values
def walk(n):
    if n == 0:
        values[0] = True
        return 1
    previous = walk(n - 1)
    return previous + alias[0]
print(walk(int(input())), values, alias)
'''
FACTORY_CONTEXT = '''def make():
    return Context()
def calculate():
    with make():
        return []
class Context:
    def __enter__(self):
        return None
    def __exit__(self, kind, value, trace):
        print('closed')
        return None
print(calculate())
'''
SUPPRESSING_CONTEXT = '''def calculate(n):
    with Context():
        return [1 // n]
class Context:
    def __enter__(self):
        return None
    def __exit__(self, kind, value, trace):
        print('closed')
        return True
print(calculate(int(input())))
'''


def frames(text):
    result = []
    for line in text.splitlines():
        match = re.search(r'File "([^"]+)", line (\d+), in (.+)', line)
        if match:
            result.append(match.groups())
        repeated = re.fullmatch(r'\s*\[Previous line repeated (\d+) more times\]\s*', line)
        if repeated:
            if not result:
                raise AssertionError('traceback repetition without a frame')
            result.extend([result[-1]] * int(repeated.group(1)))
    return result


class InferenceWorklistProofs(unittest.TestCase):
    def test_pending_implicit_exit_result_does_not_invent_a_none_return(self):
        source = ('from atcoder.convolution import convolution\n'
                  'print(convolution(998244353, [1, 2], [3, 4]))\n')
        import py2fastrust
        folder = Path(py2fastrust.__file__).resolve().parent.parent
        command = [sys.executable, '-B', '-c',
                   'import sys; from py2fastrust import transpile,TranspileOptions; '
                   'r=transpile(sys.argv[1],TranspileOptions(license="none")); '
                   'print(r.success,len(r.rust_source or ""),r.diagnostics); '
                   'raise SystemExit(0 if r.success else 1)', source]
        actual = subprocess.run(command, cwd=folder, text=True, capture_output=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)

    def test_linked_publication_scopes_stabilize_after_defaulting(self):
        source = ('import sys\nfrom atcoder.math import floor_sum\n'
                  'def main():\n    t = int(sys.stdin.readline())\n'
                  '    for _ in range(t):\n'
                  '        n, m, a, b = map(int, sys.stdin.readline().split())\n'
                  '        print(floor_sum(n, m, a, b))\n'
                  'if __name__ == "__main__":\n    main()\n')
        # Keep a scheduler regression from hanging the rest of the suite.
        # The child changes neither the host recursion limit nor input code.
        import py2fastrust
        folder = Path(py2fastrust.__file__).resolve().parent.parent
        command = [sys.executable, '-B', '-c',
                   'import sys; from py2fastrust import transpile,TranspileOptions; '
                   'r=transpile(sys.argv[1],TranspileOptions(license="none")); '
                   'print(r.success,len(r.rust_source or ""),r.diagnostics); '
                   'raise SystemExit(0 if r.success else 1)', source]
        actual = subprocess.run(command, cwd=folder, text=True, capture_output=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)

    def test_long_dependencies_reach_the_existing_verification_checkpoint(self):
        models = []
        original = native_inference_worklist.solve
        def observe(model):
            value = original(model)
            models.append(model)
            return value
        with patch.object(native_inference_worklist, 'solve', observe):
            result = transpile(chain(96), TranspileOptions(license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(models)
        self.assertTrue(all(run['verification_sweeps'] for model in models for run in model.inference_runs))
        self.assertNotIn('Box::pin', result.rust_source)
        self.assertLess(len(result.rust_source.encode()), 512 * 1024)

    def test_existing_long_call_cones_remain_below_submission_size(self):
        for integer in ('i64', 'i128', 'bigint'):
            with self.subTest(integer=integer):
                result = transpile(chain(80), TranspileOptions(integer=integer, license='none'))
                self.assertTrue(result.success, result.diagnostics)
                self.assertLess(len(result.rust_source.encode()), 512 * 1024)
                for marker in ('enum Value', 'enum Op', 'struct Runtime', 'Box::pin'):
                    self.assertNotIn(marker, result.rust_source)

    def test_recursive_storage_has_its_original_positioned_diagnostic(self):
        source = ('def descend(n, value):\n    if n == 0:\n        return 0\n'
                  '    return descend(n - 1, (value,))\nprint(descend(5, 1))\n')
        result = transpile(source, TranspileOptions(license='none'))
        self.assertFalse(result.success)
        self.assertTrue(any(d.code == 'E006' and d.line == 4 and 'recursive' in d.message
                            for d in result.diagnostics), result.diagnostics)


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class InferenceWorklistExecution(unittest.TestCase):
    def exercise(self, source, inputs):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / 'main.py'
            path.write_text(source)
            expected = [subprocess.run([sys.executable, '-I', '-S', str(path)], input=data,
                        text=True, capture_output=True, timeout=30) for data in inputs]
            for integer in ('i64', 'i128', 'bigint'):
                result = transpile(source, TranspileOptions(integer=integer, filename=str(path), license='none'))
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.backend, 'native')
                self.assertLess(len(result.rust_source.encode()), 512 * 1024)
                rust = folder / (integer + '.rs')
                rust.write_text(result.rust_source)
                for optimized in (False, True):
                    binary = folder / (integer + ('_O' if optimized else '_debug'))
                    command = ['rustc', '--edition=2021', '--crate-name', 'inference_worklist',
                               *(['-O'] if optimized else []), str(rust), '-o', str(binary)]
                    built = subprocess.run(command, text=True, capture_output=True, timeout=180)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    for data, cp in zip(inputs, expected):
                        actual = subprocess.run([str(binary)], input=data, text=True, capture_output=True, timeout=30)
                        self.assertEqual((actual.returncode, actual.stdout), (cp.returncode, cp.stdout))
                        self.assertEqual(frames(actual.stderr), frames(cp.stderr))
                        last = lambda text: text.rstrip().splitlines()[-1] if text.strip() else ''
                        self.assertEqual(last(actual.stderr), last(cp.stderr))

    def test_original_96_helpers_and_exception_frames(self):
        self.exercise(chain(96), ['2\n2\n', '2\n0\n'])

    def test_long_class_field_flow(self):
        self.exercise(field_chain(120), ['5\n', '-150\n'])

    def test_defaulting_uninhabited_storage_restarts_analysis(self):
        self.exercise(EMPTY, [''])

    def test_shared_heap_effects_remain_visible_across_recursive_calls(self):
        self.exercise(HEAP, ['0\n', '7\n'])

    def test_pending_context_factory_and_exit_do_not_invent_fallthrough(self):
        self.exercise(FACTORY_CONTEXT, [''])

    def test_resolved_exit_keeps_real_exception_suppression(self):
        self.exercise(SUPPRESSING_CONTEXT, ['1\n', '0\n'])


if __name__ == '__main__':
    unittest.main()
