"""Template object protocols preserve values instead of eagerly formatting."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class TemplateRuntimeTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_constructors_normalization_metadata_and_string_subclasses(self):
        self.run_source('''
            import string
            print(hasattr(string, "templatelib"))
            from string import templatelib
            import string.templatelib as module
            Template = module.Template
            Interpolation = module.Interpolation
            print(string.templatelib is module, templatelib is module)
            value = []
            item = Interpolation(value, expression="value", conversion="r", format_spec="!raw")
            template = Template("a", "b", item, item, "c", "d")
            print(template.strings, template.interpolations, template.values)
            print(template.strings is template.strings,
                  template.interpolations is template.interpolations,
                  template.values is template.values,
                  template.values[0] is value,
                  template.interpolations[0] is item)
            print(Template(), Interpolation(1), Interpolation(value=2))
            class Text(str):
                def __add__(self, other):
                    raise RuntimeError("must not call")
            expression = Text("expr")
            conversion = Text("s")
            spec = Text("spec")
            item = Interpolation(value, expression, conversion, spec)
            print(item.value is value, item.expression is expression,
                  item.conversion is conversion, item.format_spec is spec)
            print(Template(expression).strings[0] is expression,
                  type(Template(expression, "").strings[0]) is str)
            print((Template(expression) + Template(spec)).strings)
            for cls in [Template, Interpolation]:
                print(cls.__module__, cls.__name__, cls.__qualname__,
                      type(cls[int]).__name__, cls[int].__origin__ is cls)
                print(cls.__bases__, cls.__mro__,
                      cls.__bases__ is cls.__bases__, cls.__mro__ is cls.__mro__)
            print(Template.__module__ is Interpolation.__module__,
                  Interpolation.__match_args__ is Interpolation.__match_args__)
        ''')

    def test_constructor_errors_final_classes_readonly_fields_and_protocols(self):
        self.run_source('''
            from string.templatelib import Template, Interpolation
            for arguments in [(1,), ([],), (Template(),)]:
                try:
                    Template(*arguments)
                except TypeError as error:
                    print(type(error).__name__)
            try:
                Template(strings=("a",))
            except TypeError as error:
                print(type(error).__name__)
            for arguments in [(), (1, None), (1, "x", 1), (1, "x", "bad"),
                              (1, "x", None, 1), (1, "x", "bad", 1)]:
                try:
                    Interpolation(*arguments)
                except (TypeError, ValueError) as error:
                    print(type(error).__name__)
            for cls in [Template, Interpolation]:
                try:
                    type("Child", (cls,), {})
                except TypeError as error:
                    print(type(error).__name__)
            template = Template()
            item = Interpolation([])
            for target, name in [(template, "strings"), (item, "value"), (item, "new")]:
                try:
                    setattr(target, name, None)
                except AttributeError as error:
                    print(type(error).__name__)
            print(bool(template), bool(item), hasattr(template, "__dict__"))
            for call in [lambda:len(template), lambda:template[0], lambda:list(item),
                         lambda:template < template, lambda:template * 2,
                         lambda:template + "s", lambda:"s" + template]:
                try:
                    call()
                except TypeError as error:
                    print(type(error).__name__)
        ''')

    def test_concatenation_iteration_hints_and_identity(self):
        self.run_source('''
            from string.templatelib import Template, Interpolation
            import operator
            first = Interpolation([], "first")
            second = Interpolation({}, "second")
            left = Template("a", first, "b")
            right = Template("c", second, "d")
            combined = left + right
            print(combined.strings, combined.interpolations)
            print(combined.interpolations[0] is first,
                  combined.interpolations[1] is second,
                  combined is left, combined is right)
            print((left + Template()).interpolations is left.interpolations,
                  (Template() + left).interpolations is left.interpolations)
            alias = left
            left += right
            print(left is alias, left.strings, alias.strings)
            iterator = iter(Template("", first, "", second, ""))
            print(type(iterator).__name__, operator.length_hint(iterator),
                  hasattr(iterator, "__length_hint__"))
            print(next(iterator) is first, operator.length_hint(iterator),
                  next(iterator) is second)
            print(next(iterator, "end"), next(iterator, "end"))
            print(list(Template()), list(Template("hello")), first in combined)
        ''')

    def test_convert_defers_hooks_and_accepts_conversion_protocol(self):
        self.run_source('''
            from string.templatelib import Interpolation, Template, convert
            events = []
            class Value:
                def __repr__(self):
                    events.append("repr")
                    return "é"
                def __str__(self):
                    events.append("str")
                    return "日"
                def __format__(self, spec):
                    events.append("format")
                    return "formatted"
            value = Value()
            item = Interpolation(value, "value", "r", "custom")
            template = Template(item)
            print(events, template.values[0] is value,
                  convert(value, None) is value)
            print(convert(value, "r"), convert(value, conversion="s"),
                  convert(value, "a"), events)
            class Conversion:
                def __eq__(self, other):
                    events.append(other)
                    return other == "s"
            print(convert(value, Conversion()), events)
            for conversion in ["bad", 1, b"s"]:
                try:
                    convert(value, conversion)
                except ValueError as error:
                    print(type(error).__name__)
            try:
                convert(obj=value, conversion=None)
            except TypeError as error:
                print(type(error).__name__)
        ''')

    def test_identity_hash_mutable_values_repr_cycles_and_class_patterns(self):
        self.run_source('''
            from string.templatelib import Template, Interpolation
            import gc
            values = []
            item = Interpolation(values, "values")
            template = Template("a", item)
            other = Template("a", item)
            print(template == other, template == template,
                  item == Interpolation(values, "values"), item == item)
            old_hash = hash(template)
            item_hash = hash(item)
            mapping = {template:"template", item:"item"}
            values.append(7)
            gc.collect()
            print(hash(template) == old_hash, hash(item) == item_hash,
                  mapping[template], mapping[item])
            print(str(template) == repr(template), format(item) == repr(item))
            match item:
                case Interpolation(value, expression, conversion, spec):
                    print(value is values, expression, conversion, spec)
            match template:
                case Template(strings=strings, interpolations=items, values=contents):
                    print(strings, items[0] is item, contents[0] is values)
            match template:
                case [first, second]: print("sequence")
                case _: print("not a sequence")
            values.clear()
            values.append(item)
            print(repr(item))
            values.append(template)
            print(repr(template))
        ''')
