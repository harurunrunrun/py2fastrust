"""Original constructors and implicit methods keep their real heap effects."""
import ast
import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import native_class_value_demands
from py2fastrust.native_classes import shape
from py2fastrust.native_list_positions import allocation_origins
import test_native_private_module_demands as helpers
import test_native_lambda_callbacks as runtime_helpers


LIBRARY = '''class Context:
 stack = []
 def __init__(self, value): self.value = value
 def __enter__(self): self.stack.append(self.value)
 def __exit__(self, kind, error, trace): self.stack.pop()
 @classmethod
 def current(cls): return cls.stack[-1]
class Number:
 def __init__(self, value):
  self.value = value + Context.current()
 def __add__(self, other): return Number(self.value + other.value)
 def __iadd__(self, other):
  self.value += other.value
  return self
 def __imul__(self, other):
  self.value *= other.value
  return self
'''
MAIN = '''from arithmetic import Context, Number
with Context(int(input())):
 values = list(map(Number, [2, 7, 11]))
 copied = values[:]
 copied[1] += values[0]
 alias = copied[1]
 copied[1] *= values[2]
 fresh = copied[0] + copied[1]
 print(values[1].value, alias.value, fresh.value, Context.current())
'''


def inspect(library=LIBRARY, source=MAIN, integer='i64'):
    models=[]
    original=native_class_value_demands.prepare
    def prepare(model):
        original(model);models.append(model)
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        (root/'arithmetic.py').write_text(library)
        with patch.object(native_class_value_demands,'prepare',prepare):
            result=transpile(source,TranspileOptions(filename=str(root/'main.py'),integer=integer,license='none'))
    return result,models[-1] if models else None


class ConstructorEffectProofTests(unittest.TestCase):
    def test_direct_constructor_with_a_provisional_callable_site_is_closed(self):
        for integer in ('i64','i128','bigint'):
            with self.subTest(integer=integer):
                result,model=inspect(integer=integer)
                self.assertTrue(result.success,result.diagnostics)
                self.assertIsNone(model.source_state.barrier)
                from py2fastrust.native_finite_depth_calls import _model_proof
                self.assertTrue(_model_proof(model))
                if integer in ('i64','i128'):
                    self.assertTrue(model.source_state.bridges)
                else:
                    # BigInt is reference-backed; the Copy scalar witness ABI
                    # does not apply. Full runtime comparisons still run it.
                    self.assertFalse(model.source_state.bridges)

    def test_mutable_fields_do_not_require_loading_a_fixed_method_binding(self):
        result,model=inspect()
        self.assertTrue(result.success,result.diagnostics)
        number=next(owner for owner in model.classes.values() if owner.node.name=='Number')
        self.assertNotIn(number.index,model.value_classes.selected)
        self.assertIn(number.index,model.published_metadata)
        add=number.methods['__add__']
        self.assertIn(add.index,model.private_module_demands)
        self.assertIn(add.index,model.erased_class_contexts)
        private=re.search(r'(?:#\[inline\(always\)\]\n)?fn class_state_function_'+str(add.index)+r'\([^\n]*',result.rust_source)
        self.assertIsNotNone(private)
        self.assertTrue(private.group(0).startswith('#[inline(always)]'))

    def test_slice_registers_a_new_outer_list_and_shares_element_storage(self):
        result,model=inspect()
        self.assertTrue(result.success,result.diagnostics)
        nodes=[(plan,node)for plan in model.plans if plan.reachable
               for node in model.value_classes.own_nodes(plan)
               if isinstance(node,ast.Subscript)and isinstance(node.slice,ast.Slice)]
        self.assertTrue(nodes)
        for plan,node in nodes:
            copied=model.records[plan.index,id(node)]
            original=model.records[plan.index,id(node.value)]
            self.assertTrue(allocation_origins(copied))
            self.assertTrue(allocation_origins(original))
            self.assertTrue(allocation_origins(copied).isdisjoint(allocation_origins(original)))
            self.assertEqual(shape(copied),shape(original))
            self.assertIs(copied.root().args[0].root(),original.root().args[0].root())

    def test_constructor_that_mutates_context_invalidates_its_incoming_value(self):
        library=LIBRARY.replace('self.value = value + Context.current()',
            'Context.stack[-1] += value\n  self.value = Context.current()')
        result,model=inspect(library)
        self.assertTrue(result.success,result.diagnostics)
        number=next(owner for owner in model.classes.values()if owner.node.name=='Number')
        initializer=number.methods['__init__']
        self.assertTrue(model.source_state.effects[initializer.index])
        self.assertNotIn(initializer.index,model.source_state.abis)


@unittest.skipUnless(runtime_helpers.shutil.which('rustc'),'rustc is required')
class ConstructorEffectExecution(unittest.TestCase):
    setUpClass=classmethod(runtime_helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(runtime_helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.PrivateDemandExecution.exercise

    def test_constructor_map_slice_and_inplace_aliases_match_python(self):
        self.exercise(LIBRARY,('0\n','3\n','-2\n'),MAIN)

    def test_constructor_callback_mutation_is_visible_to_later_pulls(self):
        library=LIBRARY.replace('self.value = value + Context.current()',
            'Context.stack[-1] += value\n  self.value = Context.current()')
        self.exercise(library,('0\n','3\n','-2\n'),MAIN)

    def test_implicit_inplace_callback_mutation_invalidates_context(self):
        library=LIBRARY.replace('self.value += other.value',
            'Context.stack[-1] += other.value\n  self.value += other.value')
        self.exercise(library,('0\n','3\n','-2\n'),MAIN)


if __name__=='__main__':
    unittest.main()
