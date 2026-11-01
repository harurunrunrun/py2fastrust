"""Canonical source metadata spans real, separate Python module ASTs."""
import ast
from pathlib import Path
import tempfile
import unittest
import os
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_module_linking import LinkedProgram


class LinkedSourceMetadataTests(unittest.TestCase):
    def program(self,main,modules):
        directory=tempfile.TemporaryDirectory(prefix="pytors-linked-source-")
        self.addCleanup(directory.cleanup)
        root=Path(directory.name)
        for name,source in modules.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
        return build_program(main,str(root/'main.py'),(root,))

    def test_source_asts_and_official_scope_tables_remain_original(self):
        program=self.program('import left\nimport right\n',{
            'left.py':'value=1\ndef read():return value\n',
            'right.py':'value=2\ndef read():return value\n'})
        before=[ast.dump(unit.tree,include_attributes=True)for unit in program.units]
        linked=LinkedProgram.from_program(program).unit
        self.assertIs(linked.tree,program.main.tree)
        self.assertEqual(linked.source_units,program.units)
        self.assertEqual(before,[ast.dump(unit.tree,include_attributes=True)for unit in program.units])
        for node in linked.iter_nodes():
            original=linked.original_unit(node)
            self.assertIn(original,program.units)
            self.assertEqual(linked.definition_key(node),(original.name,original.ordinal(node)))
        for unit in program.units:
            self.assertIs(linked.original_unit(unit.tree).table,unit.table)

    def test_node_and_scope_ids_are_unique_and_module_owners_are_distinct(self):
        program=self.program('from left import read\nfrom right import read as other\n',{
            'left.py':'value=1\ndef read():return value\n',
            'right.py':'value=2\ndef read():return value\n'})
        linked=LinkedProgram.from_program(program).unit
        ids=[linked.ordinal(node)for node in linked.iter_nodes()]
        self.assertEqual(len(ids),len(set(ids)))
        roots=tuple(linked.module_roots.values())
        self.assertEqual(len(roots),len(set(roots)))
        for unit in program.units:
            self.assertTrue(linked.is_module_scope(linked.module_roots[unit.name]))
            for node in ast.walk(unit.tree):
                if isinstance(node,ast.FunctionDef):
                    self.assertEqual(linked.unit_for_scope(linked.scope_for(node).ordinal),unit)
        for binding in linked.bindings:
            self.assertLess(binding.node,len(linked.nodes))
            self.assertLess(binding.owner,len(linked.scopes))

    def test_globals_are_per_module_and_unshadowed_builtins_stay_builtin(self):
        program=self.program('import left\nimport right\n',{
            'left.py':'value=1\nlen=7\ndef read():return value+len\n',
            'right.py':'value=2\ndef read():return value+len([])\n'})
        linked=LinkedProgram.from_program(program).unit
        left=next(unit for unit in program.units if unit.name=='left')
        right=next(unit for unit in program.units if unit.name=='right')
        a=next(node for node in ast.walk(left.tree)if isinstance(node,ast.Name)and node.id=='value')
        b=next(node for node in ast.walk(right.tree)if isinstance(node,ast.Name)and node.id=='value')
        self.assertNotEqual(linked.name_for(a),linked.name_for(b))
        self.assertEqual(linked.display_name(linked.name_for(a)),'value')
        shadow=next(node for node in ast.walk(left.tree)if isinstance(node,ast.Name)and node.id=='len')
        builtin=next(node for node in ast.walk(right.tree)if isinstance(node,ast.Name)and node.id=='len')
        self.assertNotEqual(linked.name_for(shadow),'len')
        self.assertEqual(linked.name_for(builtin),'len')

    def test_import_ir_preserves_full_loaded_module_and_lexical_destination(self):
        program=self.program('import package.child\nfrom package import child\ndef read():\n import package.child as alias\n return alias\n',{
            'package/__init__.py':'',
            'package/child.py':'value=3\n'})
        linked=LinkedProgram.from_program(program).unit
        first,second,function=program.main.tree.body
        ordinary=linked.import_bindings(first)[0]
        self.assertEqual((ordinary.module,ordinary.bound_module,ordinary.exported_name),('package.child','package',None))
        imported=linked.import_bindings(second)[0]
        self.assertEqual((imported.module,imported.exported_name,imported.children),('package','child',('package.child',)))
        local=linked.import_bindings(function.body[0])[0]
        self.assertEqual((local.module,local.bound_module,local.name),('package.child','package.child','alias'))
        self.assertFalse(linked.is_module_scope(linked.binding_for(local.node).owner))

    def test_linking_never_executes_an_imported_source(self):
        program=self.program('import forbidden\n',{'forbidden.py':'raise RuntimeError("must not execute during conversion")\n'})
        linked=LinkedProgram.from_program(program).unit
        self.assertEqual(tuple(unit.name for unit in linked.source_units),('__main__','forbidden'))
        self.assertIsInstance(next(unit for unit in linked.source_units if unit.name=='forbidden').tree.body[0],ast.Raise)

    def test_qualified_binding_keys_have_python_facing_type_names(self):
        from py2fastrust.native_classes import InstanceType
        from py2fastrust.native_diagnostics import kind_name
        from py2fastrust.native_module_linking import ModuleType,ClassReferenceType
        program=self.program('import library\n',{'library.py':'class Item:pass\n'})
        unit=LinkedProgram.from_program(program).unit
        node=next(node for node in unit.iter_nodes()if isinstance(node,ast.ClassDef))
        self.assertEqual(kind_name(InstanceType(unit.name_for(node))),'library.Item')
        self.assertEqual(kind_name(ModuleType(1)),'module')
        self.assertEqual(kind_name(ClassReferenceType(1)),'type')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeLinkedModuleTests(unittest.TestCase):
    def exercise(self,files,*,reference_root=None):
        with tempfile.TemporaryDirectory(prefix='pytors-linked-runtime-')as directory:
            root=Path(directory)
            for name,source in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
            main=root/'main.py'
            expected=subprocess.run([sys.executable,'-S',str(main)],text=True,capture_output=True,timeout=15,
                                    env={**os.environ,'PYTHONPATH':str(reference_root)if reference_root else''})
            def frames(stderr):return re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',stderr)
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy code generation entered')):
                    result=transpile(main.read_text(),TranspileOptions(filename=str(main),integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser','UNICODE LICENSE V3'):
                    self.assertNotIn(marker,result.rust_source)
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    with self.subTest(integer=mode,optimized=optimized):
                        binary=root/(mode+('_release'if optimized else'_debug'))
                        build=subprocess.run(['rustc','--edition=2021','--crate-name','linked_module_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
                        self.assertEqual(build.returncode,0,build.stderr)
                        actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=15,
                            env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                        self.assertEqual(actual.stdout,expected.stdout)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                        self.assertEqual(frames(actual.stderr),frames(expected.stderr))
                        self.assertEqual(actual.stderr.rstrip().splitlines()[-1:]if actual.stderr else[],
                                         expected.stderr.rstrip().splitlines()[-1:]if expected.stderr else[])

    def test_package_import_identity_order_and_defining_globals(self):
        self.exercise({
            'main.py':'import package.values as first\nfrom package import values\nimport other\ndef again():\n import package.values\n return package.values.add(1)\nprint(first is values,other.use(),again(),first.add())\n',
            'package/__init__.py':'print("package")\n',
            'package/values.py':'value=2\ndef add(delta=3):\n global value\n value+=delta\n return value\n',
            'other.py':'value=99\nfrom package.values import add\ndef use():return add()+value\n'})

    def test_captured_defaults_class_identity_and_defining_context(self):
        self.exercise({
            'main.py':'from library import Counter\nimport library\nseed=[100]\na=Counter()\nprint(a.add(),Counter is library.Counter)\nprint(Counter().add(),a.add())\n',
            'library.py':'seed=[4]\nclass Counter:\n def __init__(self,values=seed):self.values=values\n def add(self):\n  self.values.append(len(self.values))\n  return self.values\n'})

    def test_partial_cycles_and_original_error_files(self):
        self.exercise({'main.py':'import red\nimport blue\nprint(red.total(),blue.red is red)\n',
                       'red.py':'value=4\nimport blue\ndef total():return value+blue.value\n',
                       'blue.py':'import red\nvalue=red.value+2\n'})
        self.exercise({'main.py':'print("before")\nimport red\n',
                       'red.py':'import blue\nvalue=4\n',
                       'blue.py':'import red\nprint(red.value)\n'})

    def test_shadowed_standard_module_uses_its_real_source(self):
        self.exercise({'main.py':'from math import gcd\nprint(gcd(8,3))\n',
                       'math.py':'def gcd(a,b):return a+b\n'})

    def test_imported_closure_keeps_its_own_global_namespace(self):
        self.exercise({'main.py':'from library import make\nvalue=100\nfirst=make(2)\nsecond=make(10)\nprint(first(),second(3),first(4))\n',
                       'library.py':'value=6\ndef make(start):\n count=start\n def step(delta=1):\n  nonlocal count\n  count+=delta\n  return count+value\n return step\n'})


    def test_extended_imported_lambda_defaults_globals_and_identity(self):
        self.exercise({'main.py': 'import library\noffset=1000\nfirst=library.make(2)\nsecond=library.make(9)\nprint(first(),second(3),first(4),first is first,first is second)\n', 'library.py': 'offset=7\ndef make(start):\n return lambda step=1:offset+start+step\n'})

    def test_extended_imported_comprehension_lambda_late_and_default_cells(self):
        self.exercise({'main.py': 'from library import late,early\nprint(late[0](),late[1](),early[0](),early[1]())\n', 'library.py': 'base=10\nlate=[lambda:base+i for i in range(2)]\nearly=[lambda value=i:base+value for i in range(2)]\n'})

    def test_extended_math_member_reexport_and_mixed_callable_list(self):
        self.exercise({'main.py': 'from library import functions\nimport math\nprint(functions[0](12,18),functions[1](12,18),functions[0] is math.gcd)\n', 'library.py': 'from math import gcd\ndef add(a,b):return a+b\nfunctions=[gcd,add]\n'})

    def test_extended_module_attribute_rebinding_and_saved_function(self):
        self.exercise({'main.py': 'import library\nold=library.read\nlibrary.value=9\nprint(old(),library.read())\nlibrary.read=library.other\nprint(old(),library.read())\n', 'library.py': 'value=2\ndef read():return value\ndef other():return value+100\n'})

    def test_extended_module_attribute_augassign_rhs_rebinding_old_owner(self):
        self.exercise({'main.py': 'import first\nimport second\nsaved=first\ndef change():\n global first\n first=second\n return 3\nfirst.value+=change()\nprint(saved.value,first.value)\n', 'first.py': 'value=4\n', 'second.py': 'value=20\n'})

    def test_extended_defining_module_globals_view_and_builtin_alias(self):
        self.exercise({'main.py': 'import library\nx=100\nview=library.namespace()\nprint(view["x"],"private" in globals(),"private" in view,library.function([4,5]))\n', 'library.py': 'x=6\nprivate=9\nfunction=len\ndef namespace():return globals()\n'})

    def test_extended_ordinary_stdlib_source_shadowing(self):
        self.exercise({'main.py': 'import heapq\nfrom heapq import combine\nprint(heapq.value,combine(8,3))\n', 'heapq.py': 'value=6\ndef combine(a,b):return a+b\n'})

    def test_extended_namespace_package_metadata_and_shared_child(self):
        self.exercise({'main.py': 'import package.child as child\nimport package\nprint(package.__name__,package.__package__,package.__file__ is None,package.child is child,child.value)\n', 'package/child.py': 'value=11\n'})

    def test_extended_stdlib_member_called_from_imported_function(self):
        self.exercise({'main.py': 'import library\nprint(library.compute(12,18),library.compute(20,30))\n', 'library.py': 'from math import gcd as common\ndef compute(a,b):return common(a,b)\n'})

    def test_namespace_globals_membership_is_owned_by_the_defining_module(self):
        self.exercise({'main.py': 'import library\nprivate=100\nview=library.namespace()\nprint("private" in view,"only_main" in view,"only_main" in globals(),library.function([4,5]))\nonly_main=3\nprint("only_main" in view,"only_main" in globals(),view is library.namespace())\n', 'library.py': 'private=9\nfunction=len\ndef namespace():return globals()\n'})

    def test_namespace_module_initial_names_are_not_builtin_module_metadata(self):
        self.exercise({'main.py': 'import package.values\nprint(__name__,__package__,__doc__)\nprint(package.values.metadata())\n', 'package/__init__.py': '"Package documentation"\n', 'package/values.py': '"Library documentation"\ndef metadata():return __name__,__package__,__doc__\n'})

    def test_namespace_module_globals_presence_tracks_attribute_write_and_saved_view(self):
        self.exercise({'main.py': 'import library\nview=library.namespace()\nprint("new" in view,"other" in view)\nlibrary.new=4\nprint("new" in view,"new" in globals())\n', 'library.py': 'def namespace():return globals()\n'})

    def test_namespace_canonical_sys_member_aliases_keep_recursion_configuration(self):
        self.exercise({'main.py': 'from library import configure\nimport sys\nprint(configure(),sys.getrecursionlimit())\n', 'library.py': 'import sys as system\ndef configure():\n set_limit=system.setrecursionlimit\n set_limit(123456)\n return system.getrecursionlimit()\n'})

    def test_namespace_builtins_remain_distinct_across_shadowing_module_namespaces(self):
        self.exercise({'main.py': 'import left\nimport right\nprint(left.measure([3,4]),right.measure([3,4]))\n', 'left.py': 'def len(values):return 100\ndef measure(values):return len(values)\n', 'right.py': 'def measure(values):return len(values)\n'})

    def test_namespace_imported_builtin_shadow_binding_and_delete_fallback(self):
        self.exercise({'main.py': 'from library import len\nprint(len([3,4]))\ndel len\nprint(len([3,4]))\n', 'library.py': 'def len(values):return 100\n'})

    def test_protocol_initializing_child_is_not_yet_a_package_attribute(self):
        self.exercise({'main.py': 'import package.child\n', 'package/__init__.py': '', 'package/child.py': 'import package\nprint(package.child)\n'})

    def test_protocol_initializing_package_precedes_its_child_hint(self):
        self.exercise({'main.py': 'import package\n', 'package/__init__.py': 'import package.child\n', 'package/child.py': 'import package\nprint(package.child)\n'})

    def test_protocol_relative_imports_keep_original_package_context(self):
        self.exercise({'main.py': 'from package import child\nprint(child.run(),child.__name__,child.__package__)\n', 'package/__init__.py': '', 'package/base.py': 'value=8\ndef add(x):return value+x\n', 'package/child.py': 'from .base import add\nfrom . import base\ndef run():return add(base.value)\n'})

    def test_protocol_partial_child_from_import_preserves_same_module(self):
        self.exercise({'main.py': 'import package.child\nprint(package.child.same())\n', 'package/__init__.py': '', 'package/child.py': 'from package import child as myself\ndef same():return myself is myself.myself\n'})

    def test_protocol_missing_global_key_preserves_error_position(self):
        self.exercise({'main.py': 'import library\nprint(library.namespace()["missing"])\n', 'library.py': 'def namespace():return globals()\n'})

    def test_alias_alias_reads_current_parent_attribute(self):
        self.exercise({'main.py': 'import package.child\nold=package.child\npackage.child=None\nimport package.child as alias\nfrom package import child as another\nprint(alias is None,another is None,old.value)\n', 'package/__init__.py': '', 'package/child.py': 'value=1\n'})

    def test_alias_alias_can_point_at_a_different_module(self):
        self.exercise({'main.py': 'import package.child\nimport other\nold=package.child\npackage.child=other\nimport package.child as alias\nprint(alias is other,old.value,alias.value)\n', 'package/__init__.py': '', 'package/child.py': 'value=1\n', 'other.py': 'value=9\n'})

    def test_nullable_nullable_attribute_read(self):
        self.exercise({'main.py': 'import package.child\npackage.child=None\nprint(package.child.value)\n', 'package/__init__.py': '', 'package/child.py': 'value=1\n'})

    def test_nullable_nullable_attribute_assignment_runs_rhs_first(self):
        self.exercise({'main.py': 'import package.child\npackage.child=None\ndef effect():\n print("rhs")\n return 4\npackage.child.value=effect()\n', 'package/__init__.py': '', 'package/child.py': 'value=1\n'})

    def test_nullable_nullable_attribute_augassign_reads_before_rhs(self):
        self.exercise({'main.py': 'import package.child\npackage.child=None\ndef effect():\n print("rhs")\n return 4\npackage.child.value+=effect()\n', 'package/__init__.py': '', 'package/child.py': 'value=1\n'})

    def test_factory_function_returned_module_attribute(self):
        self.exercise({'main.py': 'import library\ndef load():\n print("load")\n return library\nprint(load().value)\n', 'library.py': 'value=4\ndef add(x):return value+x\n'})

    def test_factory_function_returned_module_assignment_order(self):
        self.exercise({'main.py': 'import library\ndef load():\n print("load")\n return library\ndef rhs():\n print("rhs")\n return 8\nload().value=rhs()\nprint(library.value)\n', 'library.py': 'value=4\ndef add(x):return value+x\n'})

    def test_factory_function_returned_module_augassign_captures_old_value(self):
        self.exercise({'main.py': 'import library\ndef load():\n print("load")\n return library\ndef rhs():\n print("rhs")\n library.value=100\n return 2\nload().value+=rhs()\nprint(library.value)\n', 'library.py': 'value=4\ndef add(x):return value+x\n'})

    def test_factory_function_returned_module_callee(self):
        self.exercise({'main.py': 'import library\ndef load():\n print("load")\n return library\nprint(load().add(3))\n', 'library.py': 'value=4\ndef add(x):return value+x\n'})

    def test_metadata_explicit_bare_annotation_names(self):
        self.exercise({'main.py': 'import library\n__annotations__=3\n__annotate__=7\nprint(__annotations__,__annotate__,library.read())\n', 'library.py': '__annotations__=4\n__annotate__=8\ndef read():return __annotations__,__annotate__\n'})

    def test_metadata_explicit_annotation_read_before_assignment(self):
        self.exercise({'main.py': 'import library\n', 'library.py': 'print(__annotations__)\n__annotations__=4\n'})

    def test_display_module_and_class_references(self):
        self.exercise({'main.py': 'import package.child\nfrom package.child import Item\nprint(package,package.child,Item)\n', 'package/__init__.py': '', 'package/child.py': 'class Item:pass\n'})

    def test_display_namespace_module_reference(self):
        self.exercise({'main.py': 'import package.child\nprint(package,package.child)\n', 'package/child.py': 'value=1\n'})

    def test_unmodified_bundled_fenwick_public_methods(self):
        from importlib.resources import files
        import json
        resources=files('py2fastrust').joinpath('vendor','ac_library_python')
        inventory=json.loads(resources.joinpath('UPSTREAM.json').read_text())
        with tempfile.TemporaryDirectory(prefix='pytors-acl-CP-reference-')as reference:
            reference_root=Path(reference)
            for name in inventory['files']:
                if not name.endswith('.py'):continue
                target=reference_root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(resources.joinpath(*name.split('/')).read_bytes())
            self.exercise({'main.py':'from atcoder import fenwicktree\nd=fenwicktree.FenwickTree(6)\nfor i,value in enumerate([3,1,4,1,5,9]):\n    d.add(i,value)\nprint(d.sum(0,6),d.sum(1,4),d.sum(3,3))\nd.add(2,-7)\nprint(d.sum(0,3),d.sum(2,6))\n'},reference_root=reference_root)



if __name__=='__main__':unittest.main()
