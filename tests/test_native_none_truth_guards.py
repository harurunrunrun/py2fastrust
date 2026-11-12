"""Concrete None guards retain evaluation, names and possible later types."""
import shutil
import ast
import unittest
from types import SimpleNamespace
import test_native_class_iterators as helpers
from py2fastrust import transpile
from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Cell
from py2fastrust.native_guard_flow import unbound_local


CASES={
 'default_none_skips_iteration':'def total(values=None):\n if values:\n  for a,b in values:print(a,b)\n else:\n  print("none")\n return 3\nprint(total())\n',
 'effectful_append':'events=[]\nif events.append("condition"):\n print("wrong")\nelse:\n events.append("else")\nprint(events)\n',
 'effectful_function':'def note():\n print("condition")\n return None\nif note():\n print("wrong")\nelse:\n print("else")\n',
 'negated_none':'events=[]\nif not events.append(3):\n print("yes",events)\nelse:\n print("wrong")\n',
 'double_negated_none':'events=[]\nif not not events.append(3):\n print("wrong")\nelse:\n print("else",events)\n',
 'symbol_table_local':'value=7\ndef read():\n if None:\n  value=3\n return value\nprint(read())\n',
 'symbol_table_nonlocal':'def outer():\n value=7\n def read():\n  if None:\n   value=3\n  return value\n return read()\nprint(outer())\n',
 'deleted_local':'def read():\n value=7\n del value\n if None:\n  value="wrong"\n return value\nprint(read())\n',
 'deleted_formal':'def read(value):\n del value\n if None:\n  value="wrong"\n return value\nprint(read(7))\n',
 'global_binding':'value=7\ndef read():\n global value\n if None:\n  value=3\n return value\nprint(read())\n',
 'nonlocal_binding':'def outer():\n value=7\n def read():\n  nonlocal value\n  if None:\n   value=3\n  return value\n return read()\nprint(outer())\n',
 'missing_global':'if None:\n missing=3\nprint(missing)\n',
 'missing_global_presence':'if None:\n missing=3\nprint("missing" in globals())\n',
 'comprehension_ownership':'value=9\ndef values():\n if None:\n  value=3\n return [value for value in range(3)]\nprint(values(),value)\n',
 'branch_binding':'value=7\nif None:\n value="wrong"\nelse:\n value+=2\nprint(value)\n',
 'none_or_integer':'def choose(flag):\n if flag:return 1\n return None\nfor flag in (False,True):\n if choose(flag):print("true")\n else:print("false")\n',
 'none_or_empty_string':'def choose(flag):\n if flag:return "x"\n return None\nfor flag in (False,True):\n if not choose(flag):print("false")\n else:print("true")\n',
}


class NoneTruthProtocolTests(unittest.TestCase):
    def test_unresolved_values_and_other_binding_owners_are_not_unbound_locals(self):
        unit=parse_source('global_value=3\ndef read(value):\n local=0\n return value,local,global_value,[item for item in (1,)]\n')
        names={node.id:node for node in ast.walk(unit.tree)if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)}
        bindings={binding.node:binding for binding in unit.bindings}
        owner=bindings[unit.ordinal(names['value'])].owner
        model=SimpleNamespace(none_truth_guards=True,unit=unit,
            lexical=SimpleNamespace(scope=lambda plan:owner),
            namespace=SimpleNamespace(owners=bindings),
            resolved_name=lambda plan,node:unit.name_for(node))
        plan=SimpleNamespace(arguments={'value':Cell()})
        self.assertIsNone(unbound_local(model,plan,names['value'],{}))
        self.assertIsNone(unbound_local(model,plan,names['local'],{'local':Cell()}))
        self.assertIsNone(unbound_local(model,plan,names['global_value'],{}))
        self.assertIsNone(unbound_local(model,plan,names['item'],{}))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NoneTruthExecutionTests(unittest.TestCase):
    cases=CASES
    check=helpers.IteratorExecutionTests.check

    def test_none_and_effects(self):
        for name in ('default_none_skips_iteration','effectful_append','effectful_function','negated_none','double_negated_none','branch_binding'):
            with self.subTest(name=name):self.check(name)

    def test_symbol_table_bindings_remain_local(self):
        for name in ('symbol_table_local','symbol_table_nonlocal','deleted_local','global_binding',
                     'nonlocal_binding','missing_global','missing_global_presence','comprehension_ownership'):
            with self.subTest(name=name):self.check(name)

    def test_unsolved_or_widened_results_keep_all_paths(self):
        for name in ('none_or_integer','none_or_empty_string'):
            with self.subTest(name=name):self.check(name)

    def test_deleted_formal_retains_unbound_error(self):self.check('deleted_formal')
