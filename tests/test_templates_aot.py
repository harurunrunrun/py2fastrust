"""Template-string AST lowering and CPython 3.14 differential execution."""

import ast
import shutil
import unittest

from py2fastrust.codegen import operation
from py2fastrust.compiler import Compiler
from py2fastrust.diagnostics import CompilationError
from py2fastrust.ir import Instruction
import test_runtime


class TemplateFrontendTests(unittest.TestCase):
    def test_official_interpolation_metadata_and_source_order(self):
        source = 'value=t"a{ x = }{x!a:>{width}}"\n'
        program = Compiler("templates.py").compile(source)
        operations = program.codes[0].ops
        interpolations = [op for op in operations if op.op == "MakeInterpolation"]
        official = [node for node in ast.parse(source).body[0].value.values
                    if isinstance(node, ast.Interpolation)]
        self.assertEqual([op.args for op in interpolations],
                         [(node.str, node.conversion, node.format_spec is not None)
                          for node in official])
        self.assertEqual([op.args for op in operations if op.op == "BuildTemplate"], [(3,)])
        self.assertLess(next(i for i, op in enumerate(operations) if op.op == "FormatValue"),
                        next(i for i, op in enumerate(operations) if op is interpolations[1]))
        self.assertEqual([(op.line, op.column) for op in interpolations], [(1, 10), (1, 17)])

    def test_codegen_represents_absent_expression_and_imports_public_types(self):
        self.assertEqual(operation(Instruction("MakeInterpolation", (None, -1, False))),
                         "Op::MakeInterpolation { expression:None,conversion:-1,spec:false }")
        self.assertIn('expression:Some(" x"',
                      operation(Instruction("MakeInterpolation", (" x", 115, True))))
        program = Compiler().compile("import string.templatelib\nfrom string.templatelib import Template, Interpolation\n")
        self.assertTrue(any(op.op == "Import" and op.args[0] == "string.templatelib"
                            for op in program.codes[0].ops))

    def test_invalid_mixed_literals_and_template_patterns_use_official_checks(self):
        for source in ['t"" ""', 't"" f""', 't"" b""',
                       'match t"x":\n case t"x": pass']:
            with self.subTest(source=source), self.assertRaises(CompilationError):
                Compiler().compile(source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class TemplateAotTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_parts_empty_literals_adjacent_interpolations_and_value_identity(self):
        self.run_source('''
            from string.templatelib import Template, Interpolation
            left=[]
            right={}
            template=t"start{left}{right}end"
            print(type(template).__name__,type(template).__module__)
            print(template.strings,len(template.interpolations))
            print(template.values[0] is left,template.values[1] is right)
            print([(i.expression,i.conversion,i.format_spec) for i in template.interpolations])
            left.append(7)
            print(template.values)
            print(t"".strings,t"".interpolations,t"".values,list(t""))
            print(t"a" t"b",t"{1}" t"" t"{2}")
            print(isinstance(template,Template),isinstance(template.interpolations[0],Interpolation))
        ''')

    def test_value_then_nested_spec_order_and_outer_conversion_is_deferred(self):
        self.run_source('''
            events=[]
            class Value:
                def __repr__(self):
                    events.append("repr")
                    return "REPRESENTED"
                def __str__(self):
                    events.append("str")
                    return "STRING"
                def __format__(self,spec):
                    events.append("format:"+spec)
                    return "4"
            value=Value()
            def mark(label,result):
                events.append(label)
                return result
            template=t"{mark('value',value)!r:{mark('spec',value)}} {mark('last',9)}"
            print(events)
            print(template.interpolations[0].value is value)
            print([(i.expression,i.conversion,i.format_spec) for i in template.interpolations])
            arbitrary=t"{value:arbitrary invalid format}"
            print(arbitrary.interpolations[0].format_spec,events)
        ''')

    def test_debug_fields_preserve_lexical_expression_text(self):
        self.run_source('''
            x=7
            templates=[t"{ x }",t"{ x = }",t"{x=:}",t"{x = !s:>5}",t"{𝓍}",
                       t"""{x # middle
                        + 1 # trailing
                       }""",t"""{ x # note
                        = }"""]
            for template in templates:
                print(template.strings)
                print([(i.expression,i.conversion,i.format_spec,i.value) for i in template.interpolations])
        ''')

    def test_raw_prefixes_escapes_nested_templates_and_fstring_specs(self):
        self.run_source(r'''
            value=3.14159
            width=8
            precision=2
            print(rt"\n{{{value}}}".strings)
            print(TR"\n{value}".interpolations[0].value)
            print(t"\x7b1\x7d".strings,t"\u007b1\u007d".interpolations)
            print(t"\N{LEFT CURLY BRACKET}x\N{RIGHT CURLY BRACKET}".strings)
            template=t"{value!a:{width}.{precision}f}"
            interpolation=template.interpolations[0]
            print(interpolation.value,interpolation.conversion,interpolation.format_spec)
            inner=t"inner {value}"
            outer=t"outer {inner}"
            print(outer.values[0] is inner,outer.interpolations[0].expression)
            print(t"{t'{value}'}".values[0].values)
        ''')

    def test_closures_comprehensions_private_names_and_named_expressions(self):
        self.run_source('''
            def outer(value):
                return t"{value}",lambda:t"{value}",[t"{value+i}" for i in range(2)]
            first,closure,items=outer(9)
            print(first.values,closure().values,[item.values for item in items])
            class C:
                __value=11
                def template(self): return t"{self.__value = }"
            private=C().template()
            print(private.strings,private.values,private.interpolations[0].expression)
            template=t"{(assigned:=13)}{assigned+1}"
            print(assigned,template.values)
            def generate():
                yield t"{(yield 17)}"
            iterator=generate()
            print(next(iterator),iterator.send(19).values)
        ''')

    def test_interpolation_and_template_class_patterns(self):
        self.run_source('''
            from string.templatelib import Template,Interpolation
            interpolation=t"{1+2!r:.2f}".interpolations[0]
            match interpolation:
                case Interpolation(value,expression,conversion,format_spec):
                    print(value,expression,conversion,format_spec)
            match t"{3}":
                case Template(strings=("",""),interpolations=(Interpolation(value=3),)):
                    print("keyword template match")
            match t"{3}":
                case [value]: print("sequence")
                case _: print("not a match sequence")
            try:
                match t"":
                    case Template(strings,interpolations): pass
            except TypeError:
                print("no positional template patterns")
        ''')

    def test_lazy_annotation_and_type_alias_scopes_build_templates(self):
        self.run_source('''
            def f[T](value:t"{T}")->t"{list[T]}": pass
            T=f.__type_params__[0]
            print(f.__annotations__["value"].values[0] is T)
            print(f.__annotations__["return"].values[0].__args__[0] is T)
            class C[U]:
                field:t"{U}"
                type Alias[V=U] = t"{U}{V}"
            U=C.__type_params__[0]
            alias=C.Alias
            print(C.__annotations__["field"].values[0] is U)
            print(alias.__value__.values[0] is U,alias.__value__.values[1] is alias.__type_params__[0])
            print(alias.__type_params__[0].__default__ is U)
        ''')

    def test_future_annotations_stringify_template_source(self):
        self.run_source('''
            from __future__ import annotations
            def f(value:t"{Missing}")->t"{Missing!r:>5}": pass
            class C:
                field:t"{Missing = }"
            print(f.__annotations__,C.__annotations__)
        ''')

    def test_public_type_monkeypatching_cannot_replace_literal_construction(self):
        self.run_source('''
            import string.templatelib as templates
            Template=templates.Template
            Interpolation=templates.Interpolation
            templates.Template=object
            templates.Interpolation=object
            template=t"{3}"
            print(type(template) is Template,type(template.interpolations[0]) is Interpolation)
        ''')

    def test_exception_order_and_gc_protect_intermediate_values(self):
        self.run_source('''
            import gc
            events=[]
            def fail():
                events.append("failed")
                raise ValueError("marker")
            def later():
                events.append("later")
                return 3
            try: t"{fail():{later()}}"
            except ValueError: print(events)
            try: t"{later():{fail()}}{later()}"
            except ValueError: print(events)
            def collect():
                gc.collect()
                return None
            template=t"{['payload']}{collect()}"
            gc.collect()
            print(template.values,template.interpolations[0].value is template.values[0])
        ''')


if __name__ == "__main__":
    unittest.main()
