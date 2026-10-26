"""Runtime t-string lowering shares the generated PEG tokenizer and CST."""

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class DynamicTemplateTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-dynamic-template-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile("import sys\nexec(sys.stdin.read())\n",
                           TranspileOptions(filename="dynamic_templates.py", optimize=False))
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
        expected = subprocess.run([sys.executable, "-I", "-c", source],
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                             expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_metadata_raw_expressions_debug_and_escaped_braces(self):
        self.check_source(r'''
            from string.templatelib import Template, Interpolation
            x = 7
            K = 3
            values = [t"", t"plain", t"{x}", t"a{x}b{x + 1}c", t"{  x  }",
                      t"{ K + 1 }", t"{x=}", t"{ x = }", t"{x=:5}", t"{x=:}",
                      t"{x =  !a:>{2}}", t"{{braces}}", t"\x7b1\x7d",
                      t"\u007b1\u007d", t"\173x\175", tr"\n{x}",
                      t"" t"{x}" t"!", t"a" t"b", t"{x}{x}"]
            for value in values:
                print(type(value).__module__, type(value).__name__, value.strings)
                print([(i.value, i.expression, i.conversion, i.format_spec)
                       for i in value.interpolations])
                print(value.values, len(list(value)))
                print(all(isinstance(i, Interpolation) for i in value.interpolations))
        ''')

    def test_conversion_is_deferred_and_format_spec_evaluation_order(self):
        self.check_source('''
            events = []
            class Value:
                def __repr__(self):
                    events.append("repr")
                    return "representation"
                def __str__(self):
                    events.append("str")
                    return "string"
                def __format__(self, spec):
                    events.append(("format", spec))
                    return "formatted"
            item = Value()
            def value():
                events.append("value")
                return item
            def width():
                events.append("width")
                return 8
            template = t"{value()!r:>{width()}}/{value()!s}/{value()!a}/{value():}"
            print(events)
            print([i.value is item for i in template.interpolations])
            print([(i.expression, i.conversion, i.format_spec) for i in template.interpolations])
            nested_spec = t"{item:{2:{3}}}"
            print(nested_spec.interpolations[0].format_spec)
            spec = t"{item:{width()!r}.{2}f}"
            print(events, spec.interpolations[0].format_spec)
            nested = t"{item:{item!s}}"
            print(events, nested.interpolations[0].format_spec)
        ''')

    def test_comments_nested_literals_and_quote_reuse(self):
        source = '\n'.join([
            'x = 5',
            'values = [',
            't"{x # } and an unmatched quote \'',
            '}",',
            't"{(x # comment',
            ' + 1 # trailing',
            ')}",',
            't"{len("{hello}")}",',
            't"{len("""quote \\" } {""")}",',
            't"{t\'{x}\'}",',
            't"{f\'{x!r:>3}\'}",',
            't"{ {\'key\': (1, 2)}[\'key\'][0] }",',
            ']',
            'for value in values:',
            ' print(value.strings)',
            ' print([(i.expression, i.conversion, i.format_spec) for i in value.interpolations])',
            ' print([type(i.value).__name__ for i in value.interpolations])',
        ])
        self.check_source(source)

    def test_expressions_scope_closure_and_evaluation_errors(self):
        self.check_source('''
            events = []
            def record(value):
                events.append(value)
                return value
            template = t"{record(1)}{record(2):>{record(3)}}{record(4)}"
            print(events, template.values)
            try:
                t"{record(5)}{1 // 0}{record(6)}"
            except ZeroDivisionError:
                print(events)
            def outer():
                value = 8
                def inner():
                    return t"{value}"
                value = 9
                return inner()
            print(outer().values)
            class C:
                __value = 10
                template = t"{__value}"
                def fn(self):
                    return t"{self.__value}"
            print(C.template.values, C().fn().values)
            print(C.template.interpolations[0].expression, C().fn().interpolations[0].expression)
            print([t"{number}".values for number in range(3)])
            print(eval("t'{1 + 2}'").values)
            namespace = {}
            exec(compile("value = t'{3 + 4}'", "template.py", "exec"), namespace)
            print(namespace["value"].values)
        ''')

    def test_fstrings_use_the_same_cst_literal_decoding_and_debug_rules(self):
        self.check_source(r'''
            x = 3
            print(f"\x7b1\x7d", f"\u007b1\u007d", f"\173x\175")
            print(f"{{x}}", f"{x=}", f"{x=:5}", f"{x=:}", f"{x = !s:>{2}}")
            print(f"{1!r:0>{3}}", f"{len("{x}")}")
            print(f"a{x}" "tail", "head" f"{x}" f"{x+1}")
        ''')
        self.check_source('x = 4\nprint(f"{x # } unmatched\n}")\n')

    def test_invalid_template_syntax_is_rejected_before_execution(self):
        self.check_source(r'''
            sources = [
                't"{1! r}"', 't"{1:{2:{3:{4}}}}"',
                't"a" "b"', '"a" t"b"', 't"a" f"b"', 'b"a" t"b"',
                't"{}"', 't"{1!z}"', 't"{1!rr}"', 't"{1"', 't"}"',
                'bt"a"', 'tf"a"', 't"{lambda: 1}"', 't"{1:>{2}"',
            ]
            for source in sources:
                try:
                    compile(source, "invalid_template.py", "eval")
                except SyntaxError:
                    print("syntax")
                else:
                    print("accepted")
            template = t"{(lambda: 1)()}"
            print(template.values)
        ''')
