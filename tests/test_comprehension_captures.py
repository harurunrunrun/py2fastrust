"""Ordinary closure classification around PEP 709's isolated fast slots."""

import textwrap
import unittest
import subprocess
import tempfile
from pathlib import Path

import test_runtime
from py2fastrust import TranspileOptions, transpile


class ComprehensionCaptureTests(unittest.TestCase):
    def compare_ast_and_cst(self, source):
        source=textwrap.dedent(source)
        # Execute each fixture through both compilers in one standalone binary.
        test_runtime.RuntimeTests().run_source(source+"\nexec("+repr(source)+", {})\n")

    def test_post_comprehension_lambda_captures_unbound_local_slot(self):
        self.compare_ast_and_cst('''
            def show(callback):
                try: print(callback())
                except NameError: print('NameError')
            def f(values):
                result = [x for x in values]
                return result, lambda: x
            for values in [[], [2], [3, 4]]:
                result, callback = f(values)
                print(result)
                show(callback)
            x = 99
            result, callback = f([5])
            print(result, x)
            show(callback)
            def outer(values):
                x = 88
                def inner():
                    result = [x for x in values]
                    return result, lambda: x
                result, callback = inner()
                print(result, x)
                show(callback)
            outer([])
            outer([6])
        ''')

    def test_pre_and_post_lambdas_share_the_restored_empty_cell(self):
        self.compare_ast_and_cst('''
            x = 99
            def show(callback):
                try: print(callback())
                except NameError: print('NameError')
            def f(values):
                before = lambda: x
                captured = [lambda: x for x in values]
                after = lambda: x
                print([fn() for fn in captured])
                show(before)
                show(after)
            f([])
            f([2, 3])
            print(x)
        ''')

    def test_exception_and_first_iterator_failure_restore_the_empty_cell(self):
        self.compare_ast_and_cst('''
            x = 99
            def show(callback):
                try: print(callback())
                except NameError: print('NameError')
            def f(values):
                saved = []
                try:
                    [(saved.append(lambda: x), 1 // x) for x in values]
                except ZeroDivisionError:
                    print('caught')
                print([fn() for fn in saved])
                return lambda: x
            show(f([]))
            show(f([2, 0]))
            def fail(): raise ValueError('first iterable')
            def g():
                try: [x for x in fail()]
                except ValueError: print('first')
                return lambda: x
            show(g())
            print(x)
        ''')

    def test_repeated_comprehensions_retain_separate_capture_cells(self):
        self.compare_ast_and_cst('''
            def f():
                first = [lambda: x for x in [2, 3]]
                second = [lambda: x for x in [4, 5]]
                empty = [lambda: x for x in []]
                print([fn() for fn in first], [fn() for fn in second], empty)
                return lambda: x
            try: print(f()())
            except NameError: print('NameError')
            def outer():
                x = 90
                def inner():
                    first = [x for x in [6]]
                    second = [x for x in []]
                    return lambda: x
                callback = inner()
                print(x)
                try: print(callback())
                except NameError: print('NameError')
            outer()
        ''')

    def test_real_local_global_nonlocal_and_generator_bindings(self):
        self.compare_ast_and_cst('''
            x = 99
            def local(values):
                x = 80
                result = [lambda: x for x in values]
                return [fn() for fn in result], lambda: x
            def global_value(values):
                global x
                [x for x in values]
                return lambda: x
            def outer(values):
                x = 70
                def inner():
                    nonlocal x
                    [x for x in values]
                    return lambda: x
                return inner()
            def generator(values):
                result = (x for x in values)
                return list(result), lambda: x
            for values in [[], [2, 3]]:
                result, callback = local(values)
                print(result, callback(), global_value(values)(), outer(values)())
                result, callback = generator(values)
                print(result, callback())
        ''')

    def test_direct_owner_reads_override_comp_only_local_classification(self):
        self.compare_ast_and_cst('''
            x = 99
            def f():
                [x for x in [2, 3]]
                print(x)
                return lambda: x
            print(f()())
            def outer():
                x = 88
                def inner():
                    [x for x in [4, 5]]
                    print(x)
                    return lambda: x
                callback = inner()
                print(callback(), x)
            outer()
        ''')

    def test_lambda_expression_scopes_all_compile_modes_and_future_flags(self):
        self.compare_ast_and_cst('''
            import __future__
            def show(callback):
                try: print(callback())
                except NameError: print('NameError')
            show((lambda: ([x for x in [1, 2]], lambda: x)[1])())
            show((lambda: ([x for x in []], lambda: x)[1])())
            for flags in [0, __future__.annotations.compiler_flag]:
                for values in ['[]', '[2, 3]']:
                    expression = '(lambda: ([x for x in ' + values + '], lambda: x)[1])()'
                    for mode in ['exec', 'single', 'eval']:
                        source = expression if mode == 'eval' else 'callback = ' + expression
                        code = compile(source, 'closure.py', mode, flags=flags, dont_inherit=True)
                        namespace = {}
                        if mode == 'eval':
                            callback = eval(code, namespace)
                        else:
                            exec(code, namespace)
                            callback = namespace['callback']
                        print(flags, mode, values)
                        show(callback)
        ''')

    def test_sibling_free_reads_use_owner_fast_slot_error_kind(self):
        self.compare_ast_and_cst('''
            x = 99
            def f():
                first = [x for x in [1]]
                second = [x for y in [2]]
                print(first, second)
            f()
            def outer():
                x = 88
                def inner():
                    first = [x for x in []]
                    try: print([x for y in [2]])
                    except UnboundLocalError: print('UnboundLocalError')
                inner()
                print(x)
            outer()
        ''')

    def test_parent_free_cell_restoration_matches_between_compilers(self):
        # CPython 3.14.4's MAKE_CELL/STORE_FAST indices leak the comprehension
        # cell into a same-named owner free slot. PEP 709 instead requires the
        # entire original cell to be restored. This is a specification test,
        # deliberately separate from the CPython differential families above.
        source=textwrap.dedent('''
            def outer(values, fail):
                x = 9
                def f():
                    nonlocal x
                    callbacks = []
                    try:
                        callbacks = [(lambda: x, 1 // x if fail else 0)[0] for x in values]
                    except ZeroDivisionError:
                        pass
                    print([fn() for fn in callbacks], x)
                    return lambda: x
                callback = f()
                print(callback(), x)
            outer([], False)
            outer([1, 2], False)
            outer([1, 0], True)
        ''')
        source += "\nfor flag in [0, 16777216]:\n exec(compile("+repr(source)+", 'free_cell.py', 'exec', flags=flag, dont_inherit=True), {})\n"
        result=transpile(source,TranspileOptions(filename="free_cell.py",optimize=False))
        self.assertTrue(result.success,"\n".join(map(str,result.diagnostics)))
        with tempfile.TemporaryDirectory(prefix="py2fastrust-comp-cells-") as directory:
            root=Path(directory)
            target=root/"main.rs"
            target.write_text(result.rust_source,encoding="utf-8")
            compiled=subprocess.run(["rustc","--edition=2021",str(target),"-o",str(root/"main")],capture_output=True,text=True,timeout=90)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            actual=subprocess.run([str(root/"main")],capture_output=True,text=True,timeout=15)
            self.assertEqual(actual.returncode,0,actual.stderr)
            self.assertEqual(actual.stdout,("[] 9\n9 9\n[2, 2] 9\n9 9\n[] 9\n9 9\n")*3)

    def test_nested_inline_targets_and_declarations_use_lexical_bindings(self):
        self.compare_ast_and_cst('''
            y = 99
            def show(callback):
                try: print(callback())
                except NameError: print('NameError')
            def f(values):
                result = [[lambda: y for y in [x]] for x in values]
                print([[fn() for fn in row] for row in result])
                return lambda: y
            show(f([]))
            show(f([2, 3]))
            def outer(values):
                y = 88
                def f():
                    result = [[y for y in [x]] for x in values]
                    return lambda: y
                callback = f()
                show(callback)
                print(y)
            outer([])
            outer([4, 5])
            def declared_global():
                [y for y in [6]]
                global y
                return lambda: y
            print(declared_global()())
            invalid = "def f():\\n [x for x in []]\\n def child():\\n  nonlocal x\\n  return x\\n"
            try: exec(invalid)
            except SyntaxError: print('no ordinary binding')
        ''')

    def test_nonlocal_setter_can_fill_the_restored_lexical_cell(self):
        self.compare_ast_and_cst('''
            def outer():
                x = 88
                def f():
                    [x for x in [1, 2]]
                    def setter(value):
                        nonlocal x
                        x = value
                    def getter(): return x
                    try: print(getter())
                    except NameError: print('empty')
                    setter(7)
                    print(getter(), locals()['x'])
                    return setter, getter
                setter, getter = f()
                print(x)
                setter(9)
                print(getter(), x)
            outer()
        ''')
