"""Exception sites and with receive the public traceback chain."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class TracebackTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_caught_traceback_chain_and_identity(self):
        self.run_source('''
            def inner():
                raise ValueError("message")
            def outer():
                inner()
            try:
                outer()
            except ValueError as error:
                tb = error.__traceback__
                print(type(tb).__name__, tb is error.__traceback__)
                while tb is not None:
                    print(tb.tb_frame.f_code.co_name, tb.tb_lineno)
                    tb = tb.tb_next
            print(ValueError("not raised").__traceback__ is None)
        ''')

    def test_with_receives_original_exception_traceback(self):
        self.run_source('''
            class Guard:
                def __enter__(self):
                    return None
                def __exit__(self, kind, error, tb):
                    if error is None:
                        print(kind is None, tb is None)
                    else:
                        print(kind.__name__, error.args, tb is error.__traceback__)
                        print(tb.tb_frame.f_code.co_name, tb.tb_lineno)
                    return True
            def f():
                with Guard():
                    raise ValueError("hidden")
                with Guard():
                    pass
            f()
        ''')

    def test_dynamic_source_positions_and_bare_raise(self):
        self.run_source('''
            source = "def inner():\\n    raise TypeError('message')\\ndef outer():\\n    try:\\n        inner()\\n    except TypeError:\\n        raise\\nouter()\\n"
            try:
                exec(compile(source, "dynamic_trace.py", "exec"))
            except TypeError as error:
                tb = error.__traceback__
                while tb is not None:
                    if tb.tb_frame.f_code.co_filename == "dynamic_trace.py":
                        print(tb.tb_frame.f_code.co_name, tb.tb_lineno)
                    tb = tb.tb_next
        ''')


if __name__ == "__main__":
    unittest.main()
