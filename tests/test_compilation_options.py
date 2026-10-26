"""Runtime compilation levels use CPython's assertion, debug and doc rules."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class CompilationOptionTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_optimization_levels_assertion_effects_debug_and_docstrings(self):
        self.run_source('''
            source = '"module doc"\\nevents=[]\\ndef f():\\n "function doc"\\n return __debug__\\nclass C:\\n "class doc"\\n pass\\nprint(__debug__,f(),f.__doc__,C.__doc__)\\nassert events.append("test") or False, events.append("message")\\nevents.append("after")'
            for level in [-1,0,1,2]:
                namespace={"__doc__":"previous"}
                try:exec(compile(source,"optimized.py","exec",optimize=level),namespace)
                except AssertionError:print("assertion")
                print(level,namespace["__doc__"],namespace["events"])
                print(eval(compile("__debug__","debug.py","eval",optimize=level),{"__debug__": "shadowed"}))
        ''')

    def test_function_doc_metadata_is_independent_of_first_instruction(self):
        self.run_source('''
            def returned():return "payload"
            anonymous=lambda:"payload"
            def generated():yield "payload"
            def documented():
                "  retained without cleaning\\n indented"
                return "result"
            print(returned.__doc__,anonymous.__doc__,generated.__doc__,repr(documented.__doc__))
            source='def returned():return "payload"\\ndef generated():yield "payload"\\ndef documented():\\n "doc"\\n return "result"'
            for level in [0,1,2]:
                namespace={}
                exec(compile(source,"docs.py","exec",optimize=level),namespace)
                print(level,namespace["returned"].__doc__,namespace["generated"].__doc__,namespace["documented"].__doc__)
        ''')

    def test_docstring_indentation_retains_blank_lines_in_every_scope(self):
        samples = ["", "  first  ", "\n\n alpha\n beta\n\n", " \t\n\tfoo\n\tbar  ",
                   "\n   a\n b", "a\n\n\n", "\t", " \n  ", "\u2003foo\n\u2003bar",
                   "\r\n a\r\n b", " \x00\n  text"]
        self.run_source('samples=' + repr(samples) + '\n' + '''
for text in samples:
    source=repr(text)+'\\nclass C:\\n '+repr(text)+'\\ndef f():\\n '+repr(text)
    for level in [0,1,2]:
        namespace={}
        exec(compile(source,"indent.py","exec",optimize=level),namespace)
        print(level,repr(namespace.get("__doc__")),repr(namespace["C"].__doc__),repr(namespace["f"].__doc__))
''')

    def test_optimized_assertions_keep_static_binding_analysis(self):
        self.run_source('''
            source='def f():\\n assert (bound := 19)\\n return bound\\ndef outer():\\n captured=23\\n def inner():\\n  assert captured\\n  return 7\\n return inner\\n'
            for level in [0,1,2]:
                namespace={}
                exec(compile(source,"bindings.py","exec",optimize=level),namespace)
                try:print(namespace["f"]())
                except UnboundLocalError:print("unbound")
                print(namespace["outer"]()())
        ''')

    def test_interactive_strings_and_nested_compile_default_level(self):
        self.run_source('''
            for level in [0,1,2]:
                exec(compile("'interactive'","interactive.py","single",optimize=level),{})
                namespace={}
                source='print(__debug__)\\nprint(eval(compile("__debug__", "nested.py", "eval")))\\nprint(eval(compile("__debug__", "nested.py", "eval", optimize=-1)))'
                exec(compile(source,"outer.py","exec",optimize=level),namespace)
        ''')

    def test_lazy_annotations_aliases_and_template_values_use_their_code_level(self):
        self.run_source('''
            source='type Alias = __debug__\\ndef f(value: __debug__):pass\\nvalue=t"{__debug__}"\\nprint(Alias.__value__, f.__annotations__, value.values, value.interpolations[0].expression)'
            for level in [0,1,2]:
                exec(compile(source,"lazy.py","exec",optimize=level),{})
                exec(compile('from __future__ import annotations\\ndef f(value: __debug__):pass\\nprint(f.__annotations__)',"future.py","exec",optimize=level),{})
            print(__debug__)
        ''')

    def test_optimization_argument_index_and_invalid_debug_bindings(self):
        self.run_source('''
            class Index:
                def __index__(self):return 2
            print(eval(compile("__debug__","index.py","eval",optimize=Index())))
            for level in [-2,3,1.0,"1",None]:
                try:compile("pass","invalid.py","exec",optimize=level)
                except (ValueError,TypeError) as error:print(type(error).__name__)
            invalid=['__debug__=1','del __debug__','object.__debug__=1','del object.__debug__',
                     'def f(__debug__):pass','def __debug__():pass','class __debug__:pass',
                     'import sys as __debug__','type __debug__ = int','type Alias[__debug__] = int',
                     'assert (__debug__ := 1)']
            for level in [0,1,2]:
                for source in invalid:
                    try:compile(source,"binding.py","exec",optimize=level)
                    except SyntaxError:print(level,"syntax")
        ''')


if __name__ == "__main__":
    unittest.main()
