"""Runtime except* compilation and ExceptionGroup propagation."""

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class DynamicExceptionGroupTests(unittest.TestCase):
    maxDiff = None
    helpers = """def aot_raise():
    raise ExceptionGroup("aot", [ValueError("v"), TypeError("t")])
def aot_handle(function):
    events = []
    try:
        function()
    except* ValueError as error:
        events.append(("value", error.message))
    except* TypeError as error:
        events.append(("type", error.message))
    return events
"""
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-dynamic-groups-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile(cls.helpers + "import sys\nexec(sys.stdin.read())\n",
                           TranspileOptions(filename="dynamic_groups.py", optimize=False))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        (root / "main.rs").write_text(result.rust_source, encoding="utf-8")
        compiled = subprocess.run(["rustc", "--edition=2021", str(root / "main.rs"),
                                   "-o", str(root / "main")], capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        cls.executable = root / "main"

    def check_source(self, source):
        source = textwrap.dedent(source)
        actual = subprocess.run([str(self.executable)], input=source,
                                capture_output=True, text=True, timeout=15)
        expected = subprocess.run([sys.executable, "-I", "-c", self.helpers + source],
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                             expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_recursive_partition_all_handlers_remainder_and_else(self):
        self.check_source('''
            def describe(error):
                if isinstance(error, BaseExceptionGroup):
                    return type(error).__name__, error.message, [describe(child) for child in error.exceptions]
                return type(error).__name__, str(error)
            group = ExceptionGroup("outer", [ValueError("a"), ExceptionGroup("nested", [TypeError("b"), ValueError("c")]), KeyError("d")])
            try:
                try:
                    raise group
                except* ValueError as caught:
                    print("values", describe(caught))
                except* TypeError as caught:
                    print("types", describe(caught))
                else:
                    print("wrong else")
                finally:
                    print("finally")
            except ExceptionGroup as remainder:
                print("remainder", describe(remainder))
            for name in ["caught", "remainder"]:
                print(name in globals())
            try:
                pass
            except* Exception:
                print("wrong handler")
            else:
                print("normal else")
            finally:
                print("normal finally")
            try:
                raise ExceptionGroup("handled", [ValueError("v"), TypeError("t")])
            except* ValueError, TypeError:
                print("multiple types")
        ''')

    def test_new_errors_bare_raise_explicit_raise_and_traceback_metadata(self):
        self.check_source('''
            def describe(error):
                if isinstance(error, BaseExceptionGroup):
                    return type(error).__name__, error.message, [describe(child) for child in error.exceptions]
                return type(error).__name__, str(error)
            original = ExceptionGroup("root", [ValueError("v"), TypeError("t"), KeyError("k")])
            for action in ["bare", "explicit", "new", "cause"]:
                try:
                    try:
                        raise original
                    except* ValueError as caught:
                        print("handler", action, describe(caught))
                        if action == "bare":
                            raise
                        if action == "explicit":
                            raise caught
                        if action == "new":
                            raise RuntimeError("new")
                        raise RuntimeError("caused") from caught
                    except* TypeError:
                        print("later handler")
                except BaseException as merged:
                    print(describe(merged))
                    if action in ["new", "cause"]:
                        error = merged.exceptions[0]
                        print(describe(error.__context__), error.__suppress_context__)
                        print(error.__cause__ is error.__context__)
            try:
                try:
                    raise ValueError("naked")
                except* ValueError as caught:
                    print(type(caught).__name__, caught.message, describe(caught))
                    raise
            except BaseException as error:
                print("naked reraised", type(error).__name__, str(error))
        ''')

    def test_nested_groups_finally_alias_cleanup_and_inner_control_flow(self):
        self.check_source('''
            events = []
            try:
                raise ExceptionGroup("root", [ValueError("v"), TypeError("t")])
            except* ValueError as caught:
                for number in range(4):
                    if number == 0:
                        continue
                    events.append(number)
                    break
                def inner():
                    return 8
                events.append(inner())
                try:
                    raise ExceptionGroup("inside", [KeyError("k")])
                except* KeyError as nested:
                    events.append(nested.message)
                finally:
                    events.append("inner finally")
            except* TypeError:
                events.append("type")
            finally:
                print(events, "caught" in locals(), "nested" in locals())
            try:
                try:
                    raise ExceptionGroup("g", [ValueError("v")])
                except* ValueError as alias:
                    try:
                        raise RuntimeError("new")
                    finally:
                        print("body finally", alias.message)
            except RuntimeError:
                print("bare new", "alias" in locals())
        ''')

    def test_naked_base_exceptions_and_exception_group_catch_restrictions(self):
        self.check_source('''
            for raised in [ValueError("v"), BaseException("base")]:
                try:
                    raise raised
                except* BaseException as caught:
                    print(type(caught).__name__, caught.message, caught.exceptions[0] is raised)
            for kind in [ExceptionGroup, BaseExceptionGroup, (ValueError, ExceptionGroup), 1]:
                try:
                    try:
                        raise ExceptionGroup("g", [ValueError("v")])
                    except* kind:
                        print("wrong")
                except TypeError as error:
                    print(type(error).__name__, str(error))
            try:
                try:
                    raise ExceptionGroup("g", [ValueError("v")])
                except* ValueError:
                    print("handled all")
                except* 1:
                    print("wrong invalid")
            except TypeError:
                print("later matcher still validated")
        ''')

    def test_active_exception_context_and_matcher_failure_aborts(self):
        self.check_source('''
            import sys
            def signature(error):
                if error is None:
                    return None
                if isinstance(error, BaseExceptionGroup):
                    return error.message, tuple(type(child).__name__ for child in error.exceptions)
                return type(error).__name__, str(error)
            def matcher(kind):
                print("matcher", signature(sys.exception()), sys.exc_info()[1] is sys.exception())
                return kind
            original = ExceptionGroup("root", [ValueError("v"), TypeError("t")])
            try:
                raise original
            except* matcher(ValueError) as caught:
                print("body", signature(sys.exception()), sys.exception() is caught)
                try:
                    raise KeyError("inside")
                except KeyError:
                    print("inside", signature(sys.exception()))
                print("restored", sys.exception() is caught)
            except* matcher(TypeError) as caught:
                print("body", signature(sys.exception()), sys.exception() is caught)
            print("outside", sys.exception(), sys.exc_info())
            try:
                try:
                    raise original
                except* ValueError as caught:
                    print("first new")
                    raise RuntimeError("discarded")
                except* matcher(1):
                    print("wrong")
            except TypeError as error:
                print("matcher abort", signature(error.__context__))
            print("restored outside", sys.exception())
        ''')

    def test_generators_suspension_resume_and_handler_errors(self):
        self.check_source('''
            import sys
            def generate():
                try:
                    raise ExceptionGroup("g", [ValueError("v"), TypeError("t")])
                except* ValueError as caught:
                    yield "value", caught.message
                    print("resumed", sys.exception() is caught)
                    raise
                except* TypeError as caught:
                    yield "type", caught.message
                finally:
                    print("generator finally")
            generator = generate()
            print(next(generator), sys.exception())
            print(next(generator), sys.exception())
            try:
                next(generator)
            except ExceptionGroup as error:
                print(error.message, [type(child).__name__ for child in error.exceptions])
            print(sys.exception())
            def transfer():
                try:
                    raise ExceptionGroup("transfer", [ValueError("v"), TypeError("t")])
                except* ValueError as caught:
                    try:
                        yield caught.message
                    finally:
                        print("transfer finally")
                except* TypeError:
                    print("transfer later handler")
            generator = transfer()
            print(next(generator))
            try:
                generator.throw(RuntimeError("injected"))
            except RuntimeError as error:
                print(type(error).__name__, str(error))
            generator = transfer()
            print(next(generator))
            print(generator.close())
        ''')

    def test_aot_dynamic_exception_group_calls_share_handler_semantics(self):
        self.check_source('''
            try:
                aot_raise()
            except* ValueError as caught:
                print("from AOT", caught.message, type(caught.exceptions[0]).__name__)
            except* TypeError as caught:
                print("from AOT", caught.message, type(caught.exceptions[0]).__name__)
            def dynamic_raise():
                raise ExceptionGroup("dynamic", [ValueError("v"), TypeError("t")])
            print(aot_handle(dynamic_raise))
            def dynamic_nested():
                try:
                    aot_raise()
                except* ValueError:
                    raise RuntimeError("cross")
                except* TypeError:
                    pass
            try:
                dynamic_nested()
            except RuntimeError as error:
                print(type(error).__name__, str(error), error.__context__.message)
        ''')

    def test_scope_bindings_class_annotations_and_outer_finally_transfers(self):
        self.check_source('''
            def outer():
                changed = 0
                def inner():
                    nonlocal changed
                    try:
                        raise ExceptionGroup("closure", [ValueError("v")])
                    except* ValueError as caught:
                        changed = len(caught.exceptions)
                        local = "handler"
                    return local
                print(inner(), changed)
            outer()
            class C[T]:
                try:
                    raise ExceptionGroup("class", [ValueError("v")])
                except* ValueError:
                    field: list[T]
                except* TypeError:
                    skipped: Missing
            print(C.__annotations__)
            def leave():
                try:
                    try:
                        raise ExceptionGroup("g", [ValueError("v"), TypeError("t")])
                    except* ValueError:
                        pass
                finally:
                    return "outer return"
            print(leave())
            for number in [1]:
                try:
                    try:
                        raise ExceptionGroup("g", [ValueError("v")])
                    except* ValueError:
                        pass
                finally:
                    break
            print("outer break", number)
        ''')

    def test_alias_binding_and_cleanup_mapping_errors_abort_handler_dispatch(self):
        self.check_source('''
            def build(mode, body_raises):
                events = []
                class Namespace(dict):
                    def __setitem__(self, key, value):
                        if key == "caught":
                            events.append(("store", value is None))
                            if mode == "bind" and value is not None:
                                raise RuntimeError("bind")
                            if mode == "clear" and value is None:
                                raise RuntimeError("clear")
                        super().__setitem__(key, value)
                    def __delitem__(self, key):
                        if key == "caught":
                            events.append("delete")
                            if mode == "delete":
                                raise RuntimeError("delete")
                        super().__delitem__(key)
                class Meta(type):
                    @classmethod
                    def __prepare__(meta, name, bases):
                        return Namespace()
                try:
                    class C(metaclass=Meta):
                        try:
                            raise ExceptionGroup("g", [ValueError("v"), TypeError("t")])
                        except* ValueError as caught:
                            events.append("value")
                            if body_raises:
                                raise LookupError("body")
                        except* TypeError:
                            events.append("type")
                except BaseException as error:
                    print(mode, body_raises, type(error).__name__, str(error),
                          type(error.__context__).__name__, events)
                else:
                    print(mode, body_raises, events)
            for mode in ["bind", "clear", "delete", "none"]:
                for body_raises in [False, True]:
                    build(mode, body_raises)
        ''')

    def test_invalid_syntax_and_outward_transfers_are_rejected(self):
        self.check_source('''
            sources = [
                "try: pass\\nexcept ValueError: pass\\nexcept* TypeError: pass",
                "try: pass\\nexcept* ValueError: pass\\nexcept TypeError: pass",
                "try: pass\\nexcept*: pass",
                "def f():\\n try: pass\\n except* ValueError: return",
                "for x in [1]:\\n try: pass\\n except* ValueError: break",
                "for x in [1]:\\n try: pass\\n except* ValueError: continue",
                "def f():\\n try: pass\\n except* ValueError:\\n  try: pass\\n  finally: return",
                "for x in [1]:\\n try: pass\\n except* ValueError:\\n  for y in []: pass\\n  else: break",
                "try: pass\\nexcept* ValueError, TypeError as e: pass",
            ]
            for source in sources:
                try:
                    compile(source, "invalid_group.py", "exec")
                except SyntaxError:
                    print("syntax")
                else:
                    print("accepted")
            namespace = {}
            exec("try:\\n raise ExceptionGroup('g',[ValueError()])\\nexcept* ValueError:\\n def nested(): return 3\\n for i in [1]: break", namespace)
            print(namespace["nested"]())
        ''')
