"""Builtin namespace values retain identity separately from operation support."""
import unittest
import test_native_module_linking as linked
from py2fastrust import transpile, TranspileOptions


class NativeBuiltinNamespaceValueTests(unittest.TestCase):
    exercise=linked.NativeLinkedModuleTests.exercise

    def test_round_function_from_failed_generation_is_the_actual_fallback(self):
        self.exercise({
            'main.py': 'import state\n\ndef load(value):\n    import worker\n    return value\n\nprint(list(map(load, [1])))\nimport worker\nfirst, second = state.saved\nprint(first(2).value, second(2).value)\n',
            'state.py': 'attempts = 0\nsaved = []\n\ndef keep(value):\n    saved.append(value)\n',
            'worker.py': 'import state\nimport builtins\n\nstate.attempts += 1\nseed = 10 * state.attempts\n\nclass Mark:\n    def __init__(self, value):\n        self.value = value\n\ndef bridge(value):\n    return round(value)\n\nif state.attempts == 2:\n    print("fallback", bridge(1).value)\n\ndef round(value):\n    return Mark(seed + value)\n\nstate.keep(round)\nif state.attempts == 1:\n    builtins.round = round\n    next(iter([]))\n'})

    def test_non_adapter_builtin_slots_and_injected_names(self):
        self.exercise({'main.py': 'import builtins as table\nfrom supplier import render\ntable.hash=render\nsaved=table.hash\nprint(hash(7))\ntable.contest_helper=render\nprint(contest_helper(9))\nprint(saved(8))\n',
                       'supplier.py': 'prefix="supplier:"\ndef render(value):return prefix+str(value)\n'})

    def test_foreign_builtin_payload_alias(self):
        self.exercise({'main.py': 'import builtins as table\nfrom supplier import accept\ntable.callable=accept\nsaved=table.callable\nprint(saved(7),saved(2))\n',
                       'supplier.py': 'threshold=5\ndef accept(value):return value>threshold\n'})

    def test_value_identity_is_independent_of_operation_capability(self):
        from py2fastrust.native_builtin_identities import names, binding_error
        from py2fastrust.native_class_builtins import SUPPORTED
        self.assertIn('hash',names())
        self.assertNotIn('hash',SUPPORTED)
        self.assertIn('round',SUPPORTED)
        self.assertEqual(binding_error('hash',0,()),'TypeError: hash() takes exactly one argument (0 given)')
        self.assertEqual(binding_error('hash',1,('obj',)),'TypeError: hash() takes no keyword arguments')
        result=transpile('import builtins\nsaved=builtins.hash\nprint(saved(7))\n',TranspileOptions(filename='/tmp/builtin_capability.py'))
        self.assertFalse(result.success)
        self.assertIn("captured builtin 'hash'",str(result.diagnostics[0]))
        self.assertIn('valid call form',str(result.diagnostics[0]))

    def test_single_instance_field_reads_keep_the_established_projection(self):
        import ast
        from py2fastrust.frontend import build_program
        from py2fastrust.native_classes import Model, InstanceType, shape
        from py2fastrust.native_finite_attributes import selected
        source='class Point:\n def __init__(self,value):self.value=value\n def read(self):return self.value\nprint(Point(7).read())\n'
        unit=build_program(source,'/tmp/single_instance_projection.py',()).main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        checked=0
        for plan in model.plans:
            for node in ast.walk(plan.node):
                if not isinstance(node,ast.Attribute)or node.attr!='value':continue
                cell=model.records.get((plan.index,id(node.value)))
                if cell is not None and isinstance(shape(cell),InstanceType):
                    self.assertFalse(selected(model,plan,node))
                    checked+=1
        self.assertGreater(checked,0)

    def test_real_signature_error_without_an_operation_adapter(self):
        self.exercise({'main.py':'import builtins\nsaved=builtins.hash\nsaved()\n'})
