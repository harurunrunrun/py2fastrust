"""CPython differential coverage for stream, exception and generator protocols."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ProtocolTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_system_exit_status_and_stderr(self):
        wrapper = "import sys\nexec(sys.stdin.read())\n"
        with tempfile.TemporaryDirectory(prefix="py2fastrust-exit-") as directory:
            root = Path(directory)
            result = transpile(wrapper, TranspileOptions(filename="case.py", optimize=False))
            self.assertTrue(result.success, result.diagnostics)
            rust = root / "main.rs"
            rust.write_text(result.rust_source)
            compiled = subprocess.run(["rustc", "--edition=2021", str(rust), "-o", str(root / "main")],
                                      capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            for expression in ("", "None", "0", "7", "False", "True", "'message'", "(1, 2)"):
                with self.subTest(expression=expression):
                    source = f"import sys\nprint('before', flush=True)\nsys.exit({expression})\n"
                    actual = subprocess.run([str(root / "main")], input=source,
                                            capture_output=True, text=True, timeout=15)
                    expected = subprocess.run([sys.executable, "-I", "-c", wrapper], input=source,
                                              capture_output=True, text=True, timeout=15)
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (expected.returncode, expected.stdout, expected.stderr))

    def test_standard_input_text_and_binary_iteration(self):
        self.run_source('''
            import sys
            iterator = iter(sys.stdin)
            print(iterator is sys.stdin)
            print(repr(next(iterator)))
            for line in sys.stdin:
                print(repr(line))
            print(next(iterator, "done"))
        ''', stdin="first\r\nsecond\rlast")
        self.run_source('''
            import sys
            iterator = iter(sys.stdin.buffer)
            print(iterator is sys.stdin.buffer)
            print(repr(next(iterator)))
            for line in sys.stdin.buffer:
                print(repr(line))
            print(next(iterator, "done"))
        ''', stdin=b"first\nraw\xff\nlast")

    def test_standard_input_character_counts_and_line_hints(self):
        self.run_source('''
            import sys
            print(repr(sys.stdin.read(0)), repr(sys.stdin.read(2)))
            print(sys.stdin.readlines(1))
            print(repr(input()))
        ''', stdin="éxnext\nfinal\n")
        self.run_source('''
            import sys
            print(sys.stdin.buffer.readlines(1))
            print(sys.stdin.buffer.read())
        ''', stdin=b"longline\nrest\n")

    def test_original_exception_arguments_identity_and_mutation(self):
        self.run_source('''
            import gc
            payload = [1]
            error = ValueError(payload, 7)
            print(error.args[0] is payload, error.args, str(error), repr(error))
            payload.append(2)
            print(str(error), repr(error))
            try:
                raise error
            except ValueError as caught:
                print(caught is error, caught.args[0] is payload)
            error.args = ("changed",)
            print(error.args, str(error), repr(error))
            stop = StopIteration(payload)
            print(stop.value is payload, stop.args[0] is payload)
            exit_error = SystemExit(payload)
            print(exit_error.code is payload, exit_error.args[0] is payload)
            for i in range(11000):
                discarded = [i]
            gc.collect()
            print(stop.value is payload, exit_error.code is payload)
            stop.value = 3
            stop.args = (4,)
            exit_error.code = 5
            exit_error.args = (6,)
            print(stop.value, stop.args, exit_error.code, exit_error.args)
            first = ValueError([])
            first.args[0].append(first)
            linked = TypeError([first])
            linked.__cause__ = first
            linked.__context__ = first
            del first
            gc.collect()
            cause = linked.__cause__
            print(cause is linked.__context__, cause is linked.args[0][0],
                  cause.args[0][0] is cause, cause.args is cause.args)
            del linked, cause
            gc.collect()
        ''')

    def test_explicit_and_implicit_exception_chaining(self):
        self.run_source('''
            first = ValueError("first")
            second = TypeError("second")
            try:
                raise first
            except ValueError:
                try:
                    raise second from first
                except TypeError as caught:
                    print(caught is second, caught.__cause__ is first,
                          caught.__context__ is first, caught.__suppress_context__)
                try:
                    raise KeyError("third") from None
                except KeyError as caught:
                    print(caught.__cause__, caught.__context__ is first,
                          caught.__suppress_context__)
                try:
                    raise RuntimeError("implicit")
                except RuntimeError as caught:
                    print(caught.__cause__, caught.__context__ is first,
                          caught.__suppress_context__)
            try:
                raise second
            except TypeError as caught:
                caught.__cause__ = None
                caught.__suppress_context__ = False
                try:
                    raise
                except TypeError as again:
                    print(again is second, again.__cause__, again.__suppress_context__)
        ''')

    def test_generator_return_and_delegate_send_throw(self):
        self.run_source('''
            events = []
            def inner():
                try:
                    value = yield "ready"
                    try:
                        yield value
                    except ValueError as error:
                        yield "caught " + str(error)
                    return [7, 8]
                finally:
                    events.append("inner")
            def outer():
                try:
                    result = yield from inner()
                    yield result
                    return 9
                finally:
                    events.append("outer")
            generator = outer()
            print(next(generator), generator.send(5), generator.throw(ValueError("boom")))
            print(next(generator))
            try:
                next(generator)
            except StopIteration as error:
                print(error.value, error.args)
            try:
                next(generator)
            except StopIteration as error:
                print(error.value, error.args)
            print(events)
            class Finished:
                def __iter__(self): return self
                def __next__(self): raise StopIteration((3, 4))
            def custom():
                result = yield from Finished()
                return result
            try:
                next(custom())
            except StopIteration as error:
                print(error.value, error.args)
            def drained():
                yield 1
                return 7
            generator = drained()
            print(list(generator))
            try:
                next(generator)
            except StopIteration as error:
                print(error.value, error.args)
        ''')

    def test_generator_delegate_close_and_missing_throw(self):
        self.run_source('''
            events = []
            def inner():
                try:
                    yield 1
                finally:
                    events.append("inner")
            def outer():
                try:
                    yield from inner()
                finally:
                    events.append("outer")
            generator = outer()
            print(next(generator), generator.close(), generator.close(), events)
            def catches_exit():
                try:
                    yield 2
                except GeneratorExit:
                    return 6
            generator = catches_exit()
            print(next(generator), generator.close())
            def missing_throw():
                try:
                    yield from [3, 4]
                except KeyError:
                    yield 5
            generator = missing_throw()
            print(next(generator), generator.throw(KeyError("key")), next(generator, "done"))
            def invalid_stop():
                yield 1
                raise StopIteration(2)
            generator = invalid_stop()
            next(generator)
            try:
                next(generator)
            except RuntimeError as error:
                print(type(error.__cause__).__name__, error.__cause__.value,
                      error.__cause__ is error.__context__)
        ''')

    def test_custom_yield_from_delegate_protocols(self):
        self.run_source('''
            events = []
            class Delegate:
                def __iter__(self): return self
                def __next__(self):
                    events.append("next")
                    return 1
                def send(self, value):
                    events.append(("send", value))
                    return value * 2
                def throw(self, error):
                    events.append(("throw", error.args))
                    stop = StopIteration(3)
                    stop.value = 12
                    raise stop
                def close(self): events.append("close")
            def outer():
                try:
                    result = yield from Delegate()
                    yield result
                finally:
                    events.append("outer")
            generator = outer()
            print(next(generator), generator.send(4), generator.throw(ValueError("x")))
            print(next(generator, "done"), events)
            events.clear()
            generator = outer()
            print(next(generator), generator.close(), events)
        ''')

    def test_gc_automatic_collection_controls(self):
        self.run_source('''
            import gc
            events = []
            class Cycle:
                def __init__(self): self.cycle = self
                def __del__(self): events.append("finalized")
            gc.disable()
            print(gc.isenabled())
            value = Cycle()
            del value
            for i in range(11000):
                discarded = [i]
            print(events)
            gc.collect()
            print(events, gc.isenabled())
            gc.enable()
            print(gc.isenabled())
        ''')


if __name__ == "__main__":
    unittest.main()
