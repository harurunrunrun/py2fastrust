"""Native try/except/else/finally regions for builtin exception classes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from test_native_atexit import normalized_stderr


CASES = {
    'loop_control_and_cleanup': ('''def total(tokens):
    value=0
    for token in tokens:
        try:
            value+=int(token)
        except ValueError:
            continue
        finally:
            print("seen",token)
        if value>50:
            break
    return value
print(total(["4","z","90","1"]))
def quotient(a,b):
    try:
        return a//b
    except ZeroDivisionError:
        return None
    finally:
        print("divided",a,b)
print(quotient(9,4),quotient(2,0))
''', ''),
    'hierarchy_else_and_nesting': ('''counts={}
for key in [3,3,8]:
    try:
        counts[key]+=1
    except KeyError:
        counts[key]=1
    except Exception:
        print("unreachable")
    else:
        print("again",key)
print(counts)
try:
    item=[0][2]
except (KeyError,IndexError):
    print("lookup")
try:
    try:
        int("x1")
    except LookupError:
        print("inner")
except ArithmeticError:
    print("arithmetic")
except Exception:
    print("outer")
try:
    print(len([1,2]))
except BaseException:
    print("never")
''', ''),
    'input_until_eof': ('''lines=0
width=0
while True:
    try:
        text=input()
    except EOFError:
        break
    lines+=1
    width=max(width,len(text))
print(lines,width)
''', 'red\ngreen\n\nblue\n'),
    'recursion_and_methods': ('''import sys
sys.setrecursionlimit(5000)
def descend(n):
    try:
        if n==0:
            raise ValueError("floor")
        return descend(n-1)+1
    except ValueError:
        return 0
print(descend(1500))
def forever(n):
    return forever(n+1)
try:
    forever(0)
except RecursionError:
    print("recursion")
class Pile:
    def __init__(self):
        self.items=[]
    def take(self):
        try:
            return self.items.pop()
        except IndexError:
            return -1
pile=Pile()
pile.items.append(6)
print(pile.take(),pile.take())
''', ''),
    'handler_error_context': ('''def pick(index):
    try:
        return [5,6][index]
    except IndexError:
        return int("bad")
print(pick(1))
print(pick(4))
''', ''),
    'finally_with_propagation': ('''def failing():
    try:
        raise ValueError("first")
    finally:
        print("cleanup")
try:
    failing()
except ValueError:
    print("caught")
try:
    print(1//0)
except ValueError:
    print("other")
''', ''),
    'generator_finished_by_error': ('''stream=(10//x for x in [0,5])
try:
    next(stream)
except ZeroDivisionError:
    print(next(stream,77))
''', ''),
    'exit_is_not_an_exception': ('''import sys
try:
    sys.exit(4)
except Exception:
    print("swallowed")
''', ''),
}


def compare(test, source, stdin):
    with tempfile.TemporaryDirectory(prefix='pytors-exception-handlers-') as directory:
        script = Path(directory) / 'program.py'
        script.write_text(source)
        expected = subprocess.run([sys.executable, '-I', '-S', str(script)], input=stdin,
                                  capture_output=True, text=True, timeout=20)
        for integer in ('i64', 'i128', 'bigint'):
            with patch('py2fastrust.codegen.generate', side_effect=AssertionError('VM fallback')):
                result = transpile(source, TranspileOptions(integer=integer, filename=str(script), license='none'))
            test.assertTrue(result.success, result.diagnostics)
            test.assertEqual(result.backend, 'native')
            test.assertLess(len(result.rust_source.encode()), 512 * 1024)
            for marker in ('enum Value', 'enum Op', 'struct Runtime', 'struct PegParser'):
                test.assertNotIn(marker, result.rust_source)
            rust = Path(directory) / (integer + '.rs')
            rust.write_text(result.rust_source)
            for optimized in (False, True):
                binary = rust.with_suffix('.opt' if optimized else '.debug')
                built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                                       capture_output=True, text=True, timeout=180)
                test.assertEqual(built.returncode, 0, built.stderr)
                test.assertNotIn('warning', built.stderr)
                actual = subprocess.run([str(binary)], input=stdin, capture_output=True, text=True, timeout=20,
                                        env={**os.environ, 'PATH': '/no-python-runtime'})
                with test.subTest(integer=integer, optimized=optimized):
                    test.assertEqual((actual.returncode, actual.stdout), (expected.returncode, expected.stdout), actual.stderr)
                    test.assertEqual(normalized_stderr(actual.stderr), normalized_stderr(expected.stderr))


class NativeExceptionHandlerTests(unittest.TestCase):
    def test_loop_control_and_cleanup(self):
        compare(self, *CASES['loop_control_and_cleanup'])

    def test_hierarchy_else_and_nesting(self):
        compare(self, *CASES['hierarchy_else_and_nesting'])

    def test_input_until_eof(self):
        compare(self, *CASES['input_until_eof'])

    def test_recursion_and_methods(self):
        compare(self, *CASES['recursion_and_methods'])

    def test_handler_error_context(self):
        compare(self, *CASES['handler_error_context'])

    def test_finally_with_propagation(self):
        compare(self, *CASES['finally_with_propagation'])

    def test_generator_finished_by_error(self):
        compare(self, *CASES['generator_finished_by_error'])

    def test_failed_import_runs_again(self):
        with tempfile.TemporaryDirectory(prefix='pytors-import-retry-') as directory:
            folder = Path(directory)
            (folder / 'ledger.py').write_text('entries=[]\ndef record(value):entries.append(value)\n')
            (folder / 'loader.py').write_text('from ledger import record\nrecord(1)\nraise ValueError("again")\n')
            source = ('from ledger import entries\nfor attempt in range(2):\n    try:\n        import loader\n'
                      '    except ValueError:\n        print("failed",attempt)\nprint(len(entries))\n')
            main = folder / 'main.py'
            main.write_text(source)
            expected = subprocess.run([sys.executable, '-S', str(main)], capture_output=True, text=True, timeout=20, cwd=folder)
            self.assertEqual(expected.stdout, 'failed 0\nfailed 1\n2\n')
            result = transpile(source, TranspileOptions(filename=str(main), module_paths=(folder,), license='none'))
            self.assertTrue(result.success, result.diagnostics)
            rust = folder / 'main.rs'
            rust.write_text(result.rust_source)
            built = subprocess.run(['rustc', '--edition=2021', str(rust), '-o', str(folder / 'main')], capture_output=True, text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stderr)
            actual = subprocess.run([str(folder / 'main')], capture_output=True, text=True, timeout=20)
            self.assertEqual((actual.returncode, actual.stdout), (0, expected.stdout), actual.stderr)

    def test_exit_is_not_an_exception(self):
        compare(self, *CASES['exit_is_not_an_exception'])

    def test_unproved_handlers_are_positioned(self):
        boundaries = {
            'try:\n    pass\nexcept len:\n    pass\n': ('canonical builtin exception class', ':3:8:'),
            'ValueError=3\ntry:\n    pass\nexcept ValueError:\n    pass\n': ('canonical builtin exception class', ':4:8:'),
            'try:\n    int("a")\nexcept ValueError as error:\n    print(error)\n': ('caught exception object', ':3:1:'),
            'import sys\ntry:\n    sys.exit(1)\nexcept:\n    pass\n': ('SystemExit', ':4:1:'),
            'try:\n    pass\nexcept SystemExit:\n    pass\n': ('termination', ':3:8:'),
            'for i in range(2):\n    try:\n        pass\n    finally:\n        break\n': ('finally', ':5:9:'),
        }
        for source, (reason, position) in boundaries.items():
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='boundary.py'))
                self.assertFalse(result.success)
                text = '\n'.join(map(str, result.diagnostics))
                self.assertIn(reason, text)
                self.assertIn('boundary.py' + position, text)
