"""Live scalar captures and receiver calls keep their original contexts."""
import ast
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_call_context_effects as effects
from tests import test_native_lexical_closures as lexical
from tests import test_native_module_linking as modules


CASES = {
    'constant_missing_capture': (
        'def outer(flag):\n'
        ' if flag:modulus=97\n'
        ' def calculate(value):return value%modulus\n'
        ' return calculate(123)\n'
        'print(outer(int(input())))\n', ('0\n', '1\n')),
    'live_nonlocal_divisor': (
        'def factory():\n'
        ' modulus=97\n'
        ' def calculate(value):return value%modulus\n'
        ' def change(value):\n'
        '  nonlocal modulus\n'
        '  modulus=value\n'
        ' return calculate,change\n'
        'calculate,change=factory()\n'
        'print(calculate(123))\n'
        'change(int(input()))\n'
        'print(calculate(-123))\n', ('13\n', '0\n')),
    'argument_changes_capture_before_entry': (
        'def factory():\n'
        ' modulus=97\n'
        ' def calculate(value):return value%modulus\n'
        ' def argument():\n'
        '  nonlocal modulus\n'
        '  modulus=11\n'
        '  print("argument")\n'
        '  return 123\n'
        ' return calculate,argument\n'
        'calculate,argument=factory()\n'
        'print(calculate(argument()))\n', ('',)),
    'captured_scalar_kinds': (
        'def factory(text,raw,scale,empty):\n'
        ' def calculate(index):return text[index],raw[index],scale*index,empty is None\n'
        ' return calculate\n'
        'first=factory("abc",b"XYZ",1.5,None)\n'
        'second=factory("def",b"UVW",2.5,None)\n'
        'print(first(1),second(2),first(0))\n', ('',)),
    'mutated_buffer_in_source_callable': (
        'class Box:\n'
        ' def __init__(self,callback):self.values=[2,3];self.callback=callback\n'
        ' def update(self,k,value):self.values[k]=self.callback(value,self.values[k])\n'
        ' def twice(self,k,value):\n'
        '  self.update(k,value)\n'
        '  self.update(k,value+1)\n'
        ' def read(self,k):return self.values[k]\n'
        'def factory():\n'
        ' modulus=97\n'
        ' def combine(x,y):return (x+y)%modulus\n'
        ' return combine\n'
        'box=Box(factory())\n'
        'box.twice(0,99)\n'
        'print(box.read(0),box.read(1))\n'
        'box.update(int(input()),5)\n', ('-1\n', '2\n')),
}


class ScalarCaptureProofs(unittest.TestCase):
    def test_actual_lexical_parent_is_independent_of_the_module_view(self):
        source = CASES['live_nonlocal_divisor'][0]
        observed = []
        original = effects.prepare
        def prepare(model):
            before = ast.dump(model.unit.tree, include_attributes=True)
            original(model)
            self.assertEqual(before, ast.dump(model.unit.tree, include_attributes=True))
            observed.extend((plan, effects.summary(model, plan)) for plan in model.plans)
        with patch.object(effects, 'prepare', prepare):
            result = transpile(source, TranspileOptions(license='none'))
        self.assertTrue(result.success, result.diagnostics)
        summary = [summary for plan, summary in observed if getattr(plan.node, 'name', None) == 'calculate']
        self.assertTrue(summary)
        self.assertTrue(all(not item.incoming_module and item.lexical_parent for item in summary))
        # A changed/nonconstant divisor must remain a live read.
        self.assertNotIn('map(|class_scalar_actual|', result.rust_source)

    def test_closed_scalar_leaf_borrows_its_actual_parent_handle(self):
        observed=[]
        original=effects.prepare
        def prepare(model):
            original(model)
            observed.extend((model,plan)for plan in model.plans)
        with patch.object(effects,'prepare',prepare):
            result=transpile(CASES['live_nonlocal_divisor'][0],TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        plans=[(model,plan)for model,plan in observed if getattr(plan.node,'name',None)=='calculate']
        self.assertTrue(plans)
        for model,plan in plans:
            self.assertTrue(effects.borrowed_parent(model,plan))
            self.assertIn('fn class_function_'+str(plan.index)+'(class_scope:&ClassScope,class_lexical_parent:&std::rc::Rc<',result.rust_source)
        observed.clear()
        source='def factory():\n modulus=97\n def calculate(value):return abs(value)%modulus\n return calculate\nprint(factory()(-123))\n'
        with patch.object(effects,'prepare',prepare):
            retained=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(retained.success,retained.diagnostics)
        for model,plan in observed:
            if getattr(plan.node,'name',None)=='calculate':self.assertFalse(effects.borrowed_parent(model,plan))

    def test_constant_value_facts_do_not_remove_the_real_presence_check(self):
        source = CASES['constant_missing_capture'][0]
        for mode in ('i64', 'i128', 'bigint'):
            result = transpile(source, TranspileOptions(license='none', integer=mode))
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn('class_lexical_get_', result.rust_source)
            self.assertIn("cannot access free variable 'modulus'", result.rust_source)
            if mode != 'bigint':
                self.assertIn('map(|class_scalar_actual|', result.rust_source)


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ScalarCaptureExecution(unittest.TestCase):
    compare = lexical.LexicalClosureExecutionTests.compare

    def test_constant_and_live_captures_keep_source_errors_and_argument_order(self):
        for name in ('constant_missing_capture', 'live_nonlocal_divisor', 'argument_changes_capture_before_entry', 'captured_scalar_kinds', 'mutated_buffer_in_source_callable'):
            with self.subTest(name=name):
                self.compare(*CASES[name])

    def test_same_constant_environment_after_assignment_and_deletion(self):
        for name in ('late_outer_value_is_shared', 'nonlocal_deletion_shared_state', 'same_spelling_different_lexical_owners'):
            with self.subTest(name=name):
                self.compare(*lexical.CASES[name])

    def test_expanded_arguments_preserve_selected_parent_defaults_and_errors(self):
        self.compare('def factory(modulus):\n def calculate(x,y=4):return (x*y)%modulus\n return calculate\ncallback=factory(97)\nprint(callback(*(2,3)))\nitems=list(map(int,input().split()))\nprint(callback(*items))\n', ('7 9\n','7\n','\n','1 2 3\n'))

    def test_callee_environment_is_retained_before_argument_rebinding(self):
        self.compare('def factory(modulus):\n def calculate(x,y):return (x*y)%modulus\n return calculate\ncallback=factory(97)\noriginal=callback\ndef arguments():\n global callback\n callback=factory(13)\n print("arguments")\n return [7,9]\nprint(callback(*arguments()))\nprint(original(7,9),callback(7,9))\n', ('',))

    def test_distinct_factory_versions_are_not_assumed_equal(self):
        from tests.test_native_call_context_effects import PROJECTS
        modules.NativeLinkedModuleTests.exercise(self, PROJECTS['captured_environment_versions'])

    def test_foreign_callable_uses_its_actual_module_after_argument_mutation(self):
        modules.NativeLinkedModuleTests.exercise(self, {
            'main.py': 'import library\nbias=1000\n'
                       'def argument():\n library.bias=23\n print("argument")\n return 5\n'
                       'box=library.Box(library.calculate)\n'
                       'print(box.update(0,argument()))\n'
                       'print(box.update(1,2))\n',
            'library.py': 'bias=11\n'
                          'def calculate(value,old):return bias+value+old\n'
                          'class Box:\n'
                          ' def __init__(self,callback):self.callback=callback;self.values=[2,3]\n'
                          ' def update(self,index,value):\n'
                          '  self.values[index]=self.callback(value,self.values[index])\n'
                          '  return self.values[index]\n',
        })


if __name__ == '__main__':
    unittest.main()
