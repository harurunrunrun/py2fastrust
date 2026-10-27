"""PEP 709 scopes and PEP 667 snapshots, through AST and runtime CST."""

import textwrap
import unittest

import test_runtime as _runtime


class ComprehensionScopeTests(unittest.TestCase):
    def compare_both(self, source):
        source = textwrap.dedent(source)
        runner = _runtime.RuntimeTests()
        runner.run_source(source)
        runner.run_source("exec(" + repr(source) + ")")

    def test_function_snapshots_include_owner_and_isolate_mutations(self):
        self.compare_both('''
            def f(arg):
                before = 7
                x = 90
                snapshots = [locals() for x in [2, 3]]
                print([(list(d), d['arg'], d['before'], d['x']) for d in snapshots])
                print(snapshots[0] is snapshots[1], x, list(locals()))
                edits = [(locals().update({'x': 999}), x)[1] for x in [4, 5]]
                print(edits, x)
                print([eval('arg + x') for x in [6, 7]])
                print([(exec('x = 888'), x)[1] for x in [8, 9]], x)
            def repeated():
                a = [list(locals()) for x in [1]]
                b = [list(locals()) for x in [2]]
                print(a, b, list(locals()))
            repeated()
            f(10)
        ''')

    def test_mapping_scopes_use_isolated_fast_locals(self):
        self.compare_both('''
            outside = 70
            x = 90
            print([locals() for x in [2, 3]], x)
            print([dir() for x in [2]])
            print([[locals() for y in [4]] for x in [2]])
            class C:
                outside = 80
                x = 91
                snapshots = [locals() for x in [5, 6]]
                nested = [[locals() for y in [7]] for x in [8]]
                print(snapshots, nested, x)
            print(C.x, x)
        ''')

    def test_cells_survive_restoration_nested_and_later_mutations(self):
        self.compare_both('''
            def outer():
                x = 90
                old = lambda: x
                values = [lambda: x for x in [2, 3]]
                nested = [[lambda: (x, y) for y in [4, 5]] for x in [6, 7]]
                print(x, old(), [fn() for fn in values])
                print([[fn() for fn in row] for row in nested])
                x = 91
                print(old(), [fn() for fn in values])
                return values
            values = outer()
            import gc
            gc.collect()
            print([fn() for fn in values])
            class C:
                x = 99
                values = [lambda: x for x in [8, 9]]
            print(C.x, [fn() for fn in C.values])
        ''')

    def test_zero_iterations_exceptions_and_unbound_targets(self):
        self.compare_both('''
            def f():
                x = 90
                print([x for x in []], x)
                saved = []
                try:
                    [(saved.append(lambda: x), 1 // (3-x)) for x in [2, 3, 4]]
                except ZeroDivisionError:
                    print(x, [fn() for fn in saved])
                try:
                    [y for y, z in [(1,)]]
                except ValueError:
                    print('unpack', x, 'y' in locals(), 'z' in locals())
                print([x for x in []], x)
            f()
            x = 100
            def g():
                print([x for x in [3]], x)
                try:
                    print([y for y in []], y)
                except NameError:
                    print('not leaked')
            g()
        ''')

    def test_global_nonlocal_and_walrus_owner_bindings(self):
        self.compare_both('''
            x = 90
            def f():
                global x
                print([x for x in [2, 3]], x)
                print([(last := x) for x in [4, 5]], last)
                print([[(deep := y) for y in [x]] for x in [6, 7]], deep)
                print([(list(locals()), x) for x in [8]], x)
            f()
            def outer():
                x = 80
                last = 0
                def inner():
                    nonlocal x, last
                    print([(last := x) for x in [2, 3]], x, last)
                    print([[(last := y) for y in [x]] for x in [4, 5]], x, last)
                inner()
                print(x, last)
                def relay():
                    nonlocal x
                    [x for x in [7]]
                    return lambda: x
                print(relay()())
            outer()
            print([[(module_last := y) for y in [x]] for x in [6, 7]], module_last, x)
        ''')

    def test_first_iterable_timing_class_lookup_and_all_container_kinds(self):
        self.compare_both('''
            x = [8, 9]
            print([x for x in x], x)
            class C:
                x = [2, 3]
                vals = [x for x in x]
                try:
                    hidden = [vals for y in [1]]
                except NameError:
                    print('class names hidden')
            print(C.x, C.vals)
            def f():
                a = 7
                x = 90
                print({x: (a, sorted(locals())) for x in [2, 3]})
                print(sorted({(x, tuple(sorted(locals()))) for x in [4, 5]}))
                print(x)
            f()
        ''')

    def test_completed_comprehensions_release_hidden_roots(self):
        self.compare_both('''
            import gc
            events = []
            class Tracked:
                def __init__(self, value): self.value = value
                def __del__(self): events.append(self.value)
            [item for item in [Tracked(1)]]
            gc.collect()
            print(events)
            def f():
                [item for item in [Tracked(2)]]
                gc.collect()
                print(events)
                try:
                    [1 // 0 for item in [Tracked(3)]]
                except ZeroDivisionError:
                    pass
                gc.collect()
                print(events)
            f()
        ''')

    def test_generator_expressions_remain_separate_and_capture_inline_cells(self):
        self.compare_both('''
            def f():
                a = 7
                x = 90
                gen = (sorted(locals()) for x in [2, 3])
                print(list(gen), x)
                nested = [(x for y in [0]) for x in [4, 5]]
                print([list(gen) for gen in nested], x)
                values = [list(x for y in [0]) for x in [6, 7]]
                print(values, x)
            f()
        ''')

    def test_exception_trace_has_owner_frame_and_gc_roots(self):
        self.compare_both('''
            import gc
            def f():
                keep = [1, 2]
                x = keep
                values = [(gc.collect(), locals()['keep'], x)[1:] for x in [[3], [4]]]
                print(values, x is keep)
                try:
                    [1 // x for x in [0]]
                except ZeroDivisionError as error:
                    trace = error.__traceback__
                    frames = []
                    while trace:
                        frames.append(trace.tb_frame.f_code.co_name)
                        trace = trace.tb_next
                    print(frames, x is keep)
            f()
        ''')

    def test_class_mapping_separate_exec_namespaces_and_implicit_class_cells(self):
        self.compare_both('''
            class M(type):
                @classmethod
                def __prepare__(meta, name, bases):
                    class D(dict):
                        def __setitem__(self, key, value):
                            if key in ('x', 'y'):
                                print('store', key)
                            super().__setitem__(key, value)
                    return D()
            class C(metaclass=M):
                x = 9
                a = [(x, locals()) for x in [2]]
                print(a, x)
            class B:
                def m(self): return 12
            class Child(B):
                def m(self):
                    return [(super().m(), __class__.__name__) for x in [1]]
            print(Child().m())
            g = {'source': [7, 8], 'outside': 40}
            l = {'source': [2, 3], 'outside': 90}
            exec("result = [(x, outside, locals()) for x in source]", g, l)
            print(l['result'])
            print('x' in l, l['outside'], g['outside'])
            exec("global outside; result = [outside for x in source]", g, l)
            print(l['result'])
        ''')

    def test_captured_free_cells_do_not_become_unbound_fast_slots(self):
        self.compare_both('''
            def f():
                x = 9
                def g():
                    nonlocal x
                    a = [x for x in [2, 3]]
                    return a, lambda: x
                return g()
            a, b = f()
            print(a, b())
            def outer():
                z = 15
                def f():
                    nonlocal z
                    before = lambda: z
                    snapshots = [locals() for z in [2, 3]]
                    after = lambda: z
                    print(before(), after(), [(d['z'], list(d)) for d in snapshots])
                f()
            outer()
        ''')

    def test_class_visible_annotation_comprehensions_keep_their_own_frames(self):
        self.compare_both('''
            class C:
                x = 10
                y: [list(locals()) for _ in [1]]
                type Alias = [list(locals()) for _ in [1]]
            print(C.__annotations__)
            print(C.Alias.__value__)
            value: [list(locals()) for x in [2]]
            # Module annotations inline into their lazy annotation frame.
            print(__annotations__['value'])
        ''')

    def test_sibling_comprehension_targets_do_not_capture_global_loads(self):
        self.compare_both('''
            x = 99
            def f():
                first = [x for x in [1, 2]]
                second = [x for y in [3, 4]]
                third = [(x, y) for y in [5]]
                print(first, second, third)
            f()
            def outer():
                x = 88
                def inner():
                    nonlocal x
                    first = [x for x in [6]]
                    second = [x for y in [7]]
                    print(first, second)
                inner()
            outer()
        ''')
