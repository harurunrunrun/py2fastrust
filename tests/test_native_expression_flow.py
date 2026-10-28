"""Conditional expression effects join pure allocation epochs and Rust facts."""
import ast
import unittest
from unittest.mock import patch

from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import Allocation,MethodValue,analyze
from py2fastrust.native_types import EMPTY,ListType,join_types


class ConditionalConstraintFactsTests(unittest.TestCase):
    def facts(self,expression):
        source=("values=[1]\nalias=values\nflag=bool(input())\nresult="+expression+
                "\nobserved=values\nobserved_alias=alias\nitem=values[0]\n")
        unit=build_program(source,"effects.py").main
        analysis=analyze(unit);scope=analysis.scope()
        observations={node.targets[0].id:unit.ordinal(node.value)
                      for node in unit.tree.body if isinstance(node,ast.Assign)
                      and isinstance(node.targets[0],ast.Name)}
        return unit,scope,observations

    def allocations(self,scope,site):
        return {part for part in scope.values[site].alternatives if isinstance(part,Allocation)}

    def test_first_two_comparison_operands_are_unconditional(self):
        for expression in("values.clear()==None","None==values.clear()"):
            with self.subTest(expression=expression):
                _,scope,sites=self.facts(expression)
                self.assertEqual(scope.expressions[sites["observed"]],ListType(EMPTY))
                self.assertEqual(scope.expressions[sites["item"]],EMPTY)
                self.assertEqual(len(self.allocations(scope,sites["observed"])),1)
                self.assertEqual(self.allocations(scope,sites["observed"]),self.allocations(scope,sites["observed_alias"]))

    def test_later_comparison_operand_joins_original_and_reset_alias_epochs(self):
        for expression in("2<1<values.clear()","0<1<values.clear()"):
            with self.subTest(expression=expression):
                _,scope,sites=self.facts(expression)
                self.assertEqual(scope.expressions[sites["observed"]],ListType("int"))
                self.assertEqual(scope.expressions[sites["item"]],"int")
                self.assertEqual(len(self.allocations(scope,sites["observed"])),2)
                self.assertEqual(self.allocations(scope,sites["observed"]),self.allocations(scope,sites["observed_alias"]))

    def test_boolean_later_operands_join_effects_but_first_operand_does_not(self):
        for expression in("False and values.clear()","True or values.clear()"):
            _,scope,sites=self.facts(expression)
            self.assertEqual(scope.expressions[sites["observed"]],ListType("int"))
            self.assertEqual(len(self.allocations(scope,sites["observed"])),2)
        _,scope,sites=self.facts("values.clear() or False")
        self.assertEqual(scope.expressions[sites["observed"]],ListType(EMPTY))
        self.assertEqual(len(self.allocations(scope,sites["observed"])),1)

    def test_multiple_boolean_reset_epochs_keep_the_skipped_path(self):
        _,scope,sites=self.facts("False and values.clear() and values.clear()")
        self.assertEqual(scope.expressions[sites["observed"]],ListType("int"))
        self.assertEqual(len(self.allocations(scope,sites["observed"])),3)
        self.assertEqual(self.allocations(scope,sites["observed"]),self.allocations(scope,sites["observed_alias"]))

    def test_conditional_arms_start_from_the_same_post_condition_state(self):
        unit,scope,sites=self.facts("values.clear() if flag else values.clear()")
        original_site=unit.ordinal(unit.tree.body[0].value)
        post=self.allocations(scope,sites["observed"])
        self.assertEqual(scope.expressions[sites["observed"]],ListType(EMPTY))
        self.assertEqual(len(post),2)
        self.assertFalse(any(part.site[1]==original_site for part in post))
        for node in ast.walk(unit.tree):
            if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr=="clear":
                identities=scope.calls[unit.ordinal(node)].identity.alternatives
                receivers={part for identity in identities if isinstance(identity,MethodValue)
                           for part in identity.receiver.alternatives if isinstance(part,Allocation)}
                self.assertEqual(len(receivers),1)
                self.assertTrue(all(part.site[1]==original_site for part in receivers))

    def test_single_conditional_reset_preserves_original_content_type(self):
        _,scope,sites=self.facts("values.clear() if flag else None")
        self.assertEqual(scope.expressions[sites["observed"]],ListType("int"))
        self.assertEqual(scope.expressions[sites["item"]],"int")
        self.assertEqual(len(self.allocations(scope,sites["observed"])),2)

    def test_conditional_insertions_remain_conservative_content_lower_bounds(self):
        _,scope,sites=self.facts('False and values.append("later")')
        self.assertEqual(scope.expressions[sites["observed"]],ListType(join_types("int","str")))

    def test_solver_never_calls_a_rust_emitter_for_expression_effects(self):
        with patch("py2fastrust.native._Generator.expression",side_effect=AssertionError("emitter probe")):
            self.facts("0<1<values.clear()")


if __name__=="__main__":unittest.main()
