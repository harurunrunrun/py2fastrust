"""Symbolic receiver paths retain canonical identity and solved builtin kinds."""
import ast
from dataclasses import replace
import shutil
import unittest
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze,MethodValue,Projection
from py2fastrust.native_text_receiver_facts import builtin_text_receiver_kinds
from tests import test_native_frame_splits as text_helpers


class ReceiverFactTests(unittest.TestCase):
    def test_projected_identity_uses_only_its_own_solved_attribute_read(self):
        source="rows=[(b'aaa',b'a',b'x')]\nfor text,old,new in rows:print(text.replace(old,new))\n"
        unit=build_program(source,'main.py').main
        analysis=analyze(unit);facts=analysis.scope()
        call=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute))
        fact=facts.calls[unit.ordinal(call)]
        identity=next(value for value in fact.identity.alternatives if isinstance(value,MethodValue))
        symbolic=identity.receiver
        self.assertTrue(any(isinstance(value,Projection)for value in symbolic.alternatives))
        self.assertEqual(builtin_text_receiver_kinds(unit,facts,call,identity),frozenset({'bytes'}))
        self.assertIs(identity.receiver,symbolic)
        unrelated=replace(identity,site=unit.ordinal(call.func.value))
        self.assertEqual(builtin_text_receiver_kinds(unit,facts,call,unrelated),frozenset())


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ProjectedTextExecutionTests(unittest.TestCase):
    exercise=text_helpers.SplitExecutionTests.exercise

    def test_projected_rsplit(self):
        self.exercise("rows=[(' a b ',None),('a,b,c',',')]\nfor text,separator in rows:print(text.rsplit(separator,1))\n")

    def test_projected_split(self):
        self.exercise("rows=[(' a b ',None),('a,b,c',',')]\nfor text,separator in rows:print(text.split(separator,1))\n")

    def test_projected_text_strip(self):
        self.exercise("rows=[(' a ',None),('abXbaa','ab')]\nfor text,characters in rows:print(text.rstrip(characters))\n")

    def test_projected_bytes_strip(self):
        self.exercise("rows=[(b' a ',None),(b'abXbaa',b'ab')]\nfor text,characters in rows:print(text.rstrip(characters))\n")
