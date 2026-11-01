"""Canonical builtin namespace state, captured calls and module fallback."""
import unittest
import test_native_module_linking as linked_support


class NativeLinkedBuiltinsTests(unittest.TestCase):
    exercise=linked_support.NativeLinkedModuleTests.exercise

    def test_before_import_alias(self):
        self.exercise({'main.py': 'import helper\nold=len\nimport builtins\ndef replacement(values):return 19\nbuiltins.len=replacement\nprint(old([1,2]),len([1,2]),builtins.len([1,2]),old is builtins.len)\n', 'helper.py': ''})

    def test_global_shadow_delete(self):
        self.exercise({'main.py': 'import library\nimport builtins\ndef replacement(values):return 17\nbuiltins.len=replacement\nlen=3\nprint(len)\ndel len\nprint(len([]),library.measure([]))\n', 'library.py': 'def measure(values):return len(values)\n'})

    def test_local_and_per_module_shadows(self):
        self.exercise({'main.py': 'import left\nimport right\nimport builtins\ndef replacement(values):return 13\nbuiltins.len=replacement\ndef local(len):return len+1\nprint(left.measure([1]),right.measure([1]),local(5))\n', 'left.py': 'def len(values):return 50\ndef measure(values):return len(values)\n', 'right.py': 'def measure(values):return len(values)\n'})

    def test_callee_before_argument_rebind(self):
        self.exercise({'main.py': 'import helper\nimport builtins\noriginal=len\ndef replacement(values):return 23\ndef change():\n builtins.len=replacement\n print("change")\n return [3,4]\nprint(len(change()),len([]))\nbuiltins.len=original\nprint(builtins.len(change()),len([]))\n', 'helper.py': ''})

    def test_other_builtin_identities(self):
        self.exercise({'main.py': 'import helper\nimport builtins\nold_abs=abs\nold_bool=bool\ndef absolute(value):return 31\ndef boolean(value):return True\nbuiltins.abs=absolute\nbuiltins.bool=boolean\nprint(old_abs(-4),abs(-4),builtins.abs(-4),old_bool(0),bool(0))\n', 'helper.py': ''})

    def test_noncallable_error_after_arguments(self):
        self.exercise({'main.py': 'import helper\nimport builtins\ndef argument():\n print("argument")\n return [1]\nbuiltins.len=None\nlen(argument())\n', 'helper.py': ''})

    def test_imported_mutation_default_order(self):
        self.exercise({'main.py': 'import library\nprint(library.saved([1,2]),len([1,2]),library.function())\n', 'library.py': 'import builtins\nsaved=len\ndef replacement(values):return 41\ndef set_length():\n builtins.len=replacement\n print("default")\n return len([])\ndef function(value=set_length()):return value\n'})

    def test_canonical_receiver_alias_and_factory(self):
        self.exercise({'main.py': 'import helper\nimport builtins as runtime\nsaved=len\ndef module():\n print("module")\n return runtime\ndef replacement(values):return 29\nmodule().len=replacement\nprint(saved([1]),len([1]),module().len([1]))\n', 'helper.py': ''})

    def test_noncallable_global_shadow_delete(self):
        self.exercise({'main.py': 'import helper\nimport builtins\nbuiltins.len=None\nlen=8\nprint(len)\ndel len\nprint("before")\nlen([])\n', 'helper.py': ''})

    def test_builtin_export_alias_preserves_identity(self):
        self.exercise({'main.py': 'import helper\nfrom builtins import len as before\nimport builtins\ndef replacement(values):return 43\nbuiltins.len=replacement\nfrom builtins import len as after\nprint(before([1,2]),after([]),after is builtins.len,before is after)\n', 'helper.py': ''})

    def test_original_builtin_print(self):
        self.exercise({'main.py': 'import helper\nimport builtins\noriginal=print\ndef replacement(value):\n original(value+10)\nbuiltins.print=replacement\nprint(2)\n', 'helper.py': 'value=1\n'})

    def test_original_builtin_len(self):
        self.exercise({'main.py': 'import helper\nimport builtins\ndef replacement(value):\n return 7\nbuiltins.len=replacement\nprint(len([1,2]))\n', 'helper.py': 'value=1\n'})

    def test_builtins_import_uses_same_namespace_without_user_module(self):
        self.exercise({'main.py': 'import builtins\noriginal=len\ndef replacement(values):return 7\nbuiltins.len=replacement\nprint(original([1,2]),len([]),builtins.len([]))\n'})

    def test_canonical_builtin_from_import_captures_ordinary_aliases(self):
        source='from builtins import sum as total,int as parse\nprint(total([1,2,3]),parse("7"))\n'
        self.exercise({'main.py':source})

    def test_intrinsic_identity_proof_tracks_canonical_builtin_alternatives(self):
        import ast
        from py2fastrust.frontend import build_program
        from py2fastrust.native_module_linking import LinkedProgram
        from py2fastrust.native_linked_frames import LinkedModel
        from py2fastrust.references import BuiltinIdentity,UnknownReference
        source='import builtins\ndef replacement(value):return 9\nbuiltins.int=replacement\nprint(int("2"),len([1,2]))\n'
        program=build_program(source,'/tmp/builtin_identity.py',())
        linked=LinkedProgram.from_program(program)
        model=LinkedModel(linked,'/tmp/builtin_identity.py','i64','ascii').run()
        nodes={node.id:node for node in ast.walk(program.main.tree)if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)}
        self.assertIsInstance(model.builtin_identity(model.module,nodes['int'],{}),UnknownReference)
        self.assertEqual(model.builtin_identity(model.module,nodes['len'],{}),BuiltinIdentity('len'))
        self.exercise({'main.py':source})

    def test_added_value(self):
        self.exercise({'main.py': 'import helper\nimport builtins\nbuiltins.answer=7\nprint(answer)\n', 'helper.py': ''})

    def test_added_function(self):
        self.exercise({'main.py': 'import helper\nimport builtins\ndef replacement(value):return value+10\nbuiltins.transform=replacement\nprint(transform(2))\n', 'helper.py': ''})

    def test_added_shadow_delete(self):
        self.exercise({'main.py': 'import helper\nimport builtins\nbuiltins.answer=7\nanswer=3\nprint(answer)\ndel answer\nprint(answer)\n', 'helper.py': ''})

    def test_added_defined_later(self):
        self.exercise({'main.py': 'import helper\nimport builtins\nprint(answer)\nbuiltins.answer=7\n', 'helper.py': ''})

    def test_added_foreign_lookup(self):
        self.exercise({'main.py': 'import library\nimport builtins\nbuiltins.answer=17\nprint(library.read())\n', 'library.py': 'def read():return answer\n'})

