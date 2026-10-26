"""NFKC applies to identifier values while keyword recognition uses raw text."""

import shutil
import textwrap
import unittest

from py2fastrust import transpile, TranspileOptions
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class IdentifierNormalizationTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def both_paths(self, source):
        source = textwrap.dedent(source)
        self.run_source(source + "\nexec(" + repr(source) + ", {})\n")

    def test_bindings_composition_and_raw_keyword_lookalikes(self):
        self.both_paths('''
            K = 3
            ｖａｌｕｅ = 5
            å = 7
            𝒾𝒻 = 11
            𝒻ℴ𝓇 = 13
            ｃｌａｓｓ = 17
            print(K, value, å, 𝒾𝒻, 𝒻ℴ𝓇, ｃｌａｓｓ)
            print(True, None)
            print([name for name in globals() if name in ["K", "value", "å", "if", "for", "class", "True", "None"]])
            del K
            print("K" in globals())
        ''')

    def test_functions_parameters_attributes_and_private_names(self):
        self.both_paths('''
            def ｆｕｎｃ(K, /, *, ｖａｌｕｅ=2):
                return K + value
            print(func(3, ｖａｌｕｅ=5), func.__name__)
            class Ｅｘａｍｐｌｅ:
                def __init__(self, ｖａｌｕｅ):
                    self.__ｖａｌｕｅ = value
                def ｇｅｔ(self):
                    return self.__value
            value = Example(7)
            print(value.get(), value._Example__value, Example.__name__)
            print(value.__dict__)
        ''')

    def test_closure_global_and_comprehension_bindings(self):
        self.both_paths('''
            K = 3
            def outer():
                ｖａｌｕｅ = 5
                def inner():
                    nonlocal value
                    global K
                    value += 2
                    K += 1
                    return ｖａｌｕｅ, K
                print([ｖ + value for ｖ in range(3)])
                return inner
            f = outer()
            print(f(), f(), K)
            print([(ｙ := ｘ) for ｘ in range(3)], y)
        ''')

    def test_future_features_aliases_and_annotation_names(self):
        self.both_paths('''
            from __ｆｕｔｕｒｅ__ import ａｎｎｏｔａｔｉｏｎｓ as ｓｔｒｉｎｇｓ
            import ｍａｔｈ as ｍ
            def ｆ(K: ｌｉｓｔ[ｉｎｔ]) -> Ｆｏｒｗａｒｄ: pass
            class Ｃ:
                __ｖａｌｕｅ: Ｍｉｓｓｉｎｇ
            print(strings.compiler_flag, m.isqrt(81))
            print(f.__annotations__, C.__annotations__)
        ''')

    def test_normalized_constants_are_invalid_identifiers(self):
        sources = ["Ｔｒｕｅ=1", "Ｆａｌｓｅ", "x.Ｎｏｎｅ", "def Ｔｒｕｅ(): pass", "def f(Ｎｏｎｅ):pass"]
        for source in sources:
            with self.subTest(static=source):
                result = transpile(source, TranspileOptions(optimize=False))
                self.assertFalse(result.success)
                self.assertIn("identifier field can't represent", str(result.diagnostics[0]))
        self.run_source("sources=" + repr(sources) + '''
for source in sources:
    try:
        compile(source, "identifier.py", "exec")
    except ValueError as error:
        print(type(error).__name__, str(error))
    else:
        print("incorrectly accepted")
''')


if __name__ == "__main__":
    unittest.main()
