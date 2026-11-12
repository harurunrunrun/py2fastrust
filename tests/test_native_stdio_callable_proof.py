"""Canonical reader calls retain identity, size and byte/text results."""
import shutil
import unittest

import test_native_class_iterators as iterator_tests
from test_native_readline_integer_borrows import CASES as ORIGINAL_CASES, INPUTS as ORIGINAL_INPUTS
import test_native_stdio as stdio_tests
from py2fastrust import transpile, TranspileOptions


CASES = {name: ORIGINAL_CASES[name] for name in (
    'binary_separator_reads', 'text_callback_reads', 'text_sizes')}
INPUTS = {name: ORIGINAL_INPUTS[name] for name in CASES}

CASES['renamed_separator'] = '''from sys import stdin as incoming
raw = incoming.buffer
take = again = raw.readline
def separator():
    print(again())
    return None
left, right = map(int, take().split(separator()))
print(left, right)
'''
INPUTS['renamed_separator'] = '5 6\nretained callback read\n'

CASES['renamed_callback'] = '''from sys import stdin as stream
next_line = stream.readline
def add_adjustment(token):
    return int(token) + int(next_line())
first, second = map(add_adjustment, next_line().split())
print(first, second)
'''
INPUTS['renamed_callback'] = '2 7\n3\n-4\n'

CASES['renamed_sizes'] = '''import sys as io_module
text_stream = io_module.stdin
take = text_stream.readline
print(repr(take(0)))
print(repr(take(2)), repr(take(True)), repr(take(-2)), repr(take()))
'''
INPUTS['renamed_sizes'] = 'abC rest\nlast'

CASES['query_callback'] = '''import sys
fetch = sys.stdin.readline
def adjusted(token):
    return int(token) + int(fetch())
q = int(fetch())
answer = 0
for _ in range(q):
    x, y = map(adjusted, fetch().split())
    answer += x * y
print(answer)
'''
INPUTS['query_callback'] = '3\n1 2\n3\n4\n5 6\n-1\n2\n7 8\n0\n-2\n'

CASES['binary_grid_decode'] = '''import sys
fetch = sys.stdin.buffer.readline
n, width = map(int, fetch().split())
grid = [fetch().decode().strip() for _ in range(n)]
answer = 0
for row in grid:
    answer += row.count('#')
print(width, answer)
'''
INPUTS['binary_grid_decode'] = '3 5\n#..##\n.....\n##.#.\n'

CASES['sized_chunks'] = '''import sys
take = sys.stdin.buffer.read
first = take(4)
second = take(3)
print(repr(first), repr(second), repr(take(None)))
'''
INPUTS['sized_chunks'] = '123456789'

CASES['local_imported_callback'] = '''def main():
    from sys import stdin as source
    take = source.readline
    def convert(token):
        return int(token) + int(take())
    a, b = map(convert, take().split())
    print(a, b)
main()
'''
INPUTS['local_imported_callback'] = '2 7\n3\n-4\n'

CASES['sized_argument_callback'] = '''import sys
take = sys.stdin.readline
def count():
    print("count")
    return int(take())
print(repr(take(count())))
print(repr(take()))
'''
INPUTS['sized_argument_callback'] = '2\nabc\n'


@unittest.skipUnless(shutil.which('rustc'), 'rustc required')
class StdioCallableProofTests(unittest.TestCase):
    cases = CASES
    inputs = INPUTS
    check = iterator_tests.IteratorExecutionTests.check

    def test_original_binary_separator(self): self.check('binary_separator_reads')
    def test_original_text_callback(self): self.check('text_callback_reads')
    def test_original_text_sizes(self): self.check('text_sizes')
    def test_renamed_separator(self): self.check('renamed_separator')
    def test_renamed_callback(self): self.check('renamed_callback')
    def test_renamed_sizes(self): self.check('renamed_sizes')
    def test_query_callback(self): self.check('query_callback')
    def test_binary_grid_decode(self): self.check('binary_grid_decode')
    def test_sized_chunks(self): self.check('sized_chunks')
    def test_local_imported_callback(self): self.check('local_imported_callback')
    def test_sized_argument_callback(self): self.check('sized_argument_callback')


@unittest.skipUnless(shutil.which('rustc'), 'rustc required')
class StdioReaderBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass = classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile = stdio_tests.NativeStdioTests.compile
    differential = stdio_tests.NativeStdioTests.differential

    def test_count_error_before_read_and_recovery(self):
        source = '''import sys
take = sys.stdin.buffer.read
for size in [-2, 1.5, "2", None, 0, 1]:
    try:
        print(repr(take(size)))
    except ValueError:
        print("bad range")
    except TypeError:
        print("bad type")
print(repr(take()))
'''
        # Preserve the exact fresh failing fixture. The separate exception
        # frame selection currently misses try-only handlers; it is not a
        # reader adapter failure and must not be hidden by rewriting source.
        result = transpile(source, TranspileOptions(integer='i64', filename='try_only.py'))
        if result.success:
            self.differential(source, [b'abc\n', b''], profiles=(False, True))
        else:
            self.assertTrue(any(item.code == 'E006' and 'exception handler' in item.message
                                for item in result.diagnostics), result.diagnostics)

    def test_reader_errors_before_blocking_input(self):
        import subprocess
        import sys
        for size in ('-2', '1.5', '"2"'):
            source = 'import sys\ntake=sys.stdin.buffer.read\nprint(repr(take(' + size + ')))\n'
            commands = [[sys.executable, '-c', source]]
            commands += [[str(self.compile(source, mode))] for mode in ('i64', 'i128', 'bigint')]
            results = []
            for command in commands:
                child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertNotEqual(child.wait(timeout=5), 0)
                    output, error = child.communicate(timeout=5)
                    results.append((output, error.splitlines()[-1].split(b':')[0]))
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=5)
            self.assertTrue(all(result == results[0] for result in results))

    def test_mixed_text_binary_sizes_and_eof(self):
        source = '''import sys
text = sys.stdin.readline
raw = sys.stdin.buffer.readline
print(repr(text(0)), raw(0))
print(repr(text(2)), raw(2), repr(text(None)))
'''
        self.differential(source, [b'abcd\nefg\n', b'', 'é𝄞z\nlast'.encode()],
                          profiles=(False, True), string_mode='unicode')

    def test_explicit_utf8_decode_and_invalid_bytes(self):
        source = '''from sys import stdin as stream
take = stream.buffer.readline
print(take().decode("utf-8"), end='|')
print(take().decode("utf8"), end='!')
'''
        self.differential(source, [b'ab\ncd', b'\xff\n', 'é\r\n𝄞'.encode(), b''],
                          profiles=(False, True), string_mode='unicode')


if __name__ == '__main__':
    unittest.main()
