"""One semantic plan per identity and lexical context, before Rust emission."""

import ast
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import unittest

from py2fastrust.call_semantics import CallBindingError
from py2fastrust.native_stdio import READERS
from py2fastrust.native_stream_plans import ConsumerKind, DeferredProducer, Normalizer, ProducerKind
from py2fastrust.references import BuiltinIdentity, UnknownReference, UnboundReference, resolve_static_callable


def expression(source):
    return ast.parse(source,mode="eval").body


class NativeStreamPlanTests(unittest.TestCase):
    def normalizer(self,environment=None,locals=(),globals=()):
        env={}if environment is None else environment
        generator=SimpleNamespace(function=None,entry_scope=None,entry_local_names=frozenset(locals),
                                  global_names=frozenset(globals),global_environment={},source_unit=None)
        return Normalizer(generator,env)

    def test_all_core_consumers_share_the_same_producer_structure(self):
        for consumer in ("sum","any","all","min","max","list","sorted","next"):
            with self.subTest(consumer=consumer):
                plan=self.normalizer().consumer(expression(consumer+"(map(int,input().split()))"))
                self.assertEqual(plan.source.kind,ProducerKind.MAP)
                self.assertEqual(plan.source.callback,BuiltinIdentity("int"))
                self.assertEqual(plan.source.sources[0].kind,ProducerKind.METHOD)
                self.assertEqual(plan.source.sources[0].member,"split")
                reader=plan.source.sources[0].receiver
                self.assertEqual(self.normalizer().invocation(reader).identity,BuiltinIdentity("input"))

    def test_for_and_unpack_use_the_same_source_plan(self):
        normalizer=self.normalizer()
        loop=normalizer.consumer(ast.parse("for value in map(int,input().split()):pass").body[0])
        unpack=normalizer.consumer(ast.parse("left,right=map(int,input().split())").body[0])
        self.assertEqual((loop.kind,unpack.kind),(ConsumerKind.FOR,ConsumerKind.UNPACK))
        self.assertEqual(loop.source.kind,unpack.source.kind)
        self.assertEqual(loop.source.callback,unpack.source.callback)
        self.assertEqual(loop.source.sources[0].member,unpack.source.sources[0].member)

    def test_captured_aliases_have_canonical_identity(self):
        env={"consume":BuiltinIdentity("sum"),"transform":BuiltinIdentity("map"),"convert":BuiltinIdentity("int")}
        plan=self.normalizer(env).consumer(expression("consume(transform(convert,range(4)))"))
        self.assertEqual(plan.kind,ConsumerKind.SUM)
        self.assertEqual(plan.source.kind,ProducerKind.MAP)
        self.assertEqual(plan.source.callback,BuiltinIdentity("int"))
        self.assertEqual(plan.source.sources[0].kind,ProducerKind.RANGE)

    def test_shadowed_core_names_do_not_select_a_builtin_plan(self):
        plan=self.normalizer({"sum":object()}).consumer(expression("sum(range(3))"))
        self.assertIsNone(plan)
        source=self.normalizer({"map":object()}).producer(expression("map(int,range(3))"))
        self.assertEqual(source.kind,ProducerKind.VALUE)
        self.assertIsInstance(source.invocation.identity,UnknownReference)

    def test_unbound_local_and_incomplete_global_mask_are_distinct(self):
        local=resolve_static_callable(expression("input"),{},local_names={"input"},function_scope=True,global_bound_names=set())
        missing=resolve_static_callable(expression("input"),{},function_scope=True)
        self.assertIsInstance(local,UnboundReference)
        self.assertTrue(local.local)
        self.assertIsInstance(missing,UnknownReference)

    def test_reader_alias_preserves_binary_and_line_identity(self):
        reader=READERS[(True,True)]
        normalizer=self.normalizer({"read":reader})
        plan=normalizer.consumer(expression("list(map(int,read().split()))"))
        read=normalizer.invocation(plan.source.sources[0].receiver)
        self.assertIs(read.identity,reader)
        self.assertTrue(read.identity.binary)
        self.assertTrue(read.identity.line)

    def test_argument_order_is_independent_of_parameter_projection(self):
        plan=self.normalizer().consumer(expression("sorted(range(3),reverse=flag(),key=keyfn)"))
        self.assertEqual([value.parameter for value in plan.binding.explicit_order],["iterable","reverse","key"])
        self.assertEqual(plan.binding.binding.parameters,("iterable","key","reverse"))
        self.assertEqual(ast.unparse(plan.binding.binding["reverse"].expression),"flag()")

    def test_default_absence_and_explicit_none_are_separate(self):
        missing=self.normalizer().consumer(expression("next(iter([]))"))
        explicit=self.normalizer().consumer(expression("next(iter([]),None)"))
        self.assertNotIn("default",missing.binding.binding.explicit)
        self.assertIn("default",explicit.binding.binding.explicit)
        self.assertIsNone(explicit.binding.binding["default"].expression.value)
        self.assertIsNotNone(missing.binding.binding["default"].default)

    def test_generator_scope_defers_only_inner_iterables(self):
        plan=self.normalizer().producer(expression("(x+y for x in range(3) if x for y in range(x))"))
        self.assertEqual(plan.kind,ProducerKind.GENERATOR)
        self.assertEqual(plan.frame,"<genexpr>")
        self.assertEqual(plan.clauses[0].source.kind,ProducerKind.RANGE)
        self.assertIsInstance(plan.clauses[1].source,DeferredProducer)
        self.assertEqual(ast.unparse(plan.clauses[1].source.expression),"range(x)")

    def test_list_comprehension_is_an_eager_consumer_of_scoped_plan(self):
        plan=self.normalizer().consumer(expression("[str(x) for x in range(3)]"))
        self.assertEqual(plan.kind,ConsumerKind.LIST)
        self.assertEqual(plan.source.kind,ProducerKind.GENERATOR)
        self.assertIsNone(plan.source.frame)
        self.assertEqual(plan.source.clauses[0].source.kind,ProducerKind.RANGE)

    def test_one_invocation_is_normalized_once_per_context(self):
        calls=[]
        node=expression("sum(range(3))")
        def resolve(value):
            calls.append(value.id)
            return BuiltinIdentity(value.id)
        normalizer=Normalizer(None,{},resolver=resolve)
        first=normalizer.consumer(node)
        second=normalizer.consumer(node)
        self.assertIs(first.source,second.source)
        self.assertEqual(calls,["sum","range"])

    def test_plans_are_frozen_and_do_not_execute_source(self):
        plan=self.normalizer().consumer(expression("sum(range(side_effect()),start=other())"))
        self.assertEqual(ast.unparse(plan.binding.binding["start"].expression),"other()")
        with self.assertRaises(FrozenInstanceError):
            plan.source.kind=ProducerKind.VALUE
        self.assertEqual(self.normalizer().consumer(expression("list()" )).source.elements,())

    def test_invalid_bindings_do_not_fabricate_an_argument_order(self):
        for source in ("sum(iterable=range(3))","next(iter([]),default=3)","map(int)","range()","sum(*values)"):
            with self.subTest(source=source):
                with self.assertRaises(CallBindingError):
                    normalizer=self.normalizer()
                    normalizer.producer(expression(source)) if source.startswith(("range","map")) else normalizer.consumer(expression(source))


if __name__=="__main__":
    unittest.main()
