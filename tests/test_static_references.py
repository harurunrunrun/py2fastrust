"""A source spelling alone never proves builtin or stream callable identity."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native import _Binding,_Specializations,_function_plans
from py2fastrust.native_scalar import ScalarGenerator
from py2fastrust.native_module_calls import ModuleRef,MEMBERS,reference as module_reference
from py2fastrust.native_stdio import SYS,TEXT,BINARY,READERS,reference as stream_reference
from py2fastrust.references import (BuiltinIdentity,UnboundReference,UnknownReference,
                                    callable_reference,resolve_static_callable)


def expression(source):return ast.parse(source,mode="eval").body


class StaticReferenceTests(unittest.TestCase):
    def test_builtin_identity_is_canonical_and_actual_bindings_take_precedence(self):
        first=resolve_static_callable(expression("int"),{})
        second=resolve_static_callable(expression("int"),{})
        self.assertIs(first,second)
        self.assertEqual(first,BuiltinIdentity("int"))
        self.assertIs(resolve_static_callable(expression("renamed"),{"renamed":first}),first)
        actual=BuiltinIdentity("list")
        self.assertIs(resolve_static_callable(expression("int"),{"int":actual}),actual)
        self.assertIsInstance(resolve_static_callable(expression("int"),{"int":None}),UnknownReference)

    def test_unbound_function_local_is_distinct_from_global_or_default_builtin(self):
        result=resolve_static_callable(expression("input"),{},local_names={"input"},
              global_environment={"input":READERS[(True,True)]},global_bound_names={"input"},function_scope=True)
        self.assertEqual(result,UnboundReference("input",True))
        self.assertEqual(resolve_static_callable(expression("not_a_builtin"),{}),UnboundReference("not_a_builtin",False))
        self.assertIsInstance(resolve_static_callable(expression("input"),{},function_scope=True),UnknownReference)

    def test_non_static_globals_remain_shadow_masks_after_capture_filtering(self):
        result=resolve_static_callable(expression("int"),{},global_environment={},global_bound_names={"int"},function_scope=True)
        self.assertIsInstance(result,UnknownReference)
        self.assertIn("shadowed",result.reason)
        actual=BuiltinIdentity("str")
        self.assertIs(resolve_static_callable(expression("int"),{},global_environment={"int":actual},
                      global_bound_names={"int"},function_scope=True),actual)

    def test_module_members_and_builtin_module_attributes_use_identity_records(self):
        actual=resolve_static_callable(expression("alias.isqrt"),{"alias":ModuleRef("math")})
        self.assertIs(actual,MEMBERS["math"]["isqrt"])
        self.assertIsInstance(resolve_static_callable(expression("math.isqrt"),{}),UnboundReference)
        self.assertEqual(resolve_static_callable(expression("b.int"),{"b":ModuleRef("builtins")}),BuiltinIdentity("int"))
        self.assertIsInstance(resolve_static_callable(expression("obj.isqrt"),{"obj":7}),UnknownReference)

    def test_reader_identity_preserves_text_binary_line_and_builtin_eof_policy(self):
        values={"stream":SYS}
        for path,expected in [("stream.stdin",TEXT),("stream.stdin.buffer",BINARY),
                              ("stream.stdin.readline",READERS[(False,True)]),
                              ("stream.stdin.buffer.readline",READERS[(True,True)]),
                              ("stream.stdin.buffer.read",READERS[(True,False)])]:
            self.assertIs(resolve_static_callable(expression(path),values),expected)
        builtin=resolve_static_callable(expression("input"),{})
        raw=resolve_static_callable(expression("input"),{"input":READERS[(True,True)]})
        self.assertEqual(builtin,BuiltinIdentity("input"))
        self.assertIs(raw,READERS[(True,True)])
        self.assertNotEqual(builtin,raw)

    def test_legacy_module_and_stream_helpers_delegate_to_the_same_resolver(self):
        with patch("py2fastrust.references.resolve_static_callable",wraps=resolve_static_callable)as shared:
            self.assertIs(module_reference(expression("m.isqrt"),{"m":ModuleRef("math")}),MEMBERS["math"]["isqrt"])
            self.assertIs(stream_reference(expression("s.stdin.readline"),{"s":SYS}),READERS[(False,True)])
            self.assertEqual(shared.call_count,2)

    def test_synthetic_callback_names_use_lexical_private_context(self):
        unit=build_program("class C:\n def method(self):pass\n").main
        function=SimpleNamespace(node=unit.tree.body[0].body[0],local_names={"self","_C__convert"},
                                 global_names=frozenset(),required=set(),absent_globals=set())
        generator=SimpleNamespace(function=function,source_unit=unit,global_names=frozenset(),global_environment={})
        target=BuiltinIdentity("int")
        result=callable_reference(generator,ast.Name(id="__convert",ctx=ast.Load()),{"_C__convert":target})
        self.assertIs(result,target)
        self.assertEqual(function.required,set())
        self.assertEqual(function.absent_globals,set())

    def test_entry_function_wrapper_retains_unbound_local_mask(self):
        generator=SimpleNamespace(function=None,entry_scope="main",entry_local_names={"input"},
                                  global_names=frozenset({"main"}),global_environment=None,source_unit=None)
        self.assertEqual(callable_reference(generator,expression("input"),{}),UnboundReference("input",True))

    def test_resolved_global_members_and_default_builtins_record_caller_constraints(self):
        function=SimpleNamespace(node=None,local_names=set(),global_names=frozenset({"m"}),required=set(),absent_globals=set())
        generator=SimpleNamespace(function=function,global_names=frozenset({"m"}),
                                  global_environment={"m":ModuleRef("math")},source_unit=None)
        callable_reference(generator,expression("m.isqrt"),{})
        callable_reference(generator,expression("int"),{})
        self.assertEqual(function.required,{"m"})
        self.assertEqual(function.absent_globals,{"int"})

    def test_specializations_retain_masks_in_cache_keys_and_nested_calls(self):
        source="def first(value):return value+1\ndef second(value):return first(value)\n"
        unit=build_program(source).main
        functions=_function_plans(unit.tree,unit.table,64,ScalarGenerator)
        specializations=_Specializations(64,functions,{},False,ScalarGenerator)
        specializations.source_unit=unit
        namespace={name:function for name,function in functions.items()}
        masked={**namespace,"int":_Binding("discarded_numeric_global","int")}
        specializations.get(functions["second"],("int",),masked)
        self.assertGreaterEqual(len(specializations.generators),2)
        for generator in specializations.generators:
            self.assertNotIn("int",generator.global_environment)
            self.assertIn("int",generator.global_names)
            self.assertIsInstance(callable_reference(generator,expression("int"),{}),UnknownReference)
        first_masked=specializations.get(functions["first"],("int",),masked)
        first_default=specializations.get(functions["first"],("int",),namespace)
        self.assertIsNot(first_masked,first_default)
        generator=specializations.generators[-1]
        self.assertEqual(callable_reference(generator,expression("int"),{}),BuiltinIdentity("int"))
        self.assertIn("int",first_default.absent_globals)



if __name__=="__main__":unittest.main()
