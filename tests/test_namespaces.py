"""Visible namespace order and optimized locals follow Python's scope rules."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NamespaceTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare_static_and_dynamic(self, source):
        import textwrap
        source = textwrap.dedent(source)
        self.run_source(source + "\nexec(" + repr(source) + ", {})\n")

    def test_globals_instances_and_keyword_expansion_keep_order(self):
        self.compare_static_and_dynamic('''
            alpha = 1
            beta = 2
            gamma = 3
            alpha = 4
            selected = {"alpha", "beta", "gamma"}
            print([name for name in globals() if name in selected])
            del beta
            beta = 5
            print([name for name in globals() if name in selected])
            class Example:
                pass
            value = Example()
            value.first = 1
            value.second = 2
            value.first = 3
            print(vars(value))
            del value.first
            value.first = 4
            print(list(vars(value)), list(vars(value).items()))
            def collect(**keywords):
                print(list(keywords.items()))
            collect(**vars(value))
        ''')

    def test_function_parameter_cell_and_free_variable_order(self):
        self.compare_static_and_dynamic('''
            def outer():
                z = 11
                a = 13
                def f(flag, /, q=17, *items, k=19, **keywords):
                    if flag:
                        x = 1
                    else:
                        y = 2
                    y = 3
                    x = 4
                    ordinary = 5
                    def child():
                        return x + z + a
                    snapshot = locals()
                    print(list(snapshot), snapshot["a"], snapshot["z"], child())
                    snapshot["a"] = 99
                    print(a, list(eval("locals()")))
                return f
            f = outer()
            f(False, 23, 29, 31, k=37, extra=41)
            f(True)
        ''')

    def test_class_dictionary_order_after_delete_and_reinsert(self):
        self.compare_static_and_dynamic('''
            class Example:
                first = 1
                second = 2
                first = 3
                del first
                first = 4
            print([name for name in vars(Example) if name in {"first", "second"}])
            class Prepared(dict):
                pass
            class Meta(type):
                @classmethod
                def __prepare__(mcls, name, bases):
                    return Prepared()
            class Custom(metaclass=Meta):
                first = 1
                second = 2
            print([name for name in vars(Custom) if name in {"first", "second"}])
        ''')


if __name__ == "__main__":
    unittest.main()
