"""Original-owner class namespaces, nested definitions and shared class data."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from tests import test_native_module_linking as support

CASES = {'nested_constructor': {'main.py': 'class Outer:\n'
                                   ' class Inner:\n'
                                   '  def __init__(self,value):self.value=value\n'
                                   '  def get(self):return self.value+1\n'
                                   'print(Outer.Inner(4).get())\n'},
 'nested_same_spelling': {'main.py': 'class Left:\n'
                                     ' class Item:\n'
                                     '  def __init__(self,value):self.value=value+1\n'
                                     'class Right:\n'
                                     ' class Item:\n'
                                     '  def __init__(self,value):self.value=value+10\n'
                                     'print(Left.Item(2).value,Right.Item(2).value)\n'},
 'nested_three_levels': {'main.py': 'class Outer:\n'
                                    ' class Middle:\n'
                                    '  class Inner:\n'
                                    '   def __init__(self,value):self.value=value\n'
                                    'print(Outer.Middle.Inner(7).value)\n'},
 'nested_private': {'main.py': 'class Outer:\n'
                               ' class __Inner:\n'
                               '  def __init__(self,value):self.value=value\n'
                               ' def run(self,value):return Outer.__Inner(value).value\n'
                               'print(Outer().run(3),Outer._Outer__Inner(8).value)\n'},
 'nested_alias': {'main.py': 'class Outer:\n'
                             ' class Inner:\n'
                             '  def __init__(self,value):self.value=value\n'
                             ' Saved=Inner\n'
                             'Alias=Outer.Inner\n'
                             'print(Alias(2).value,Outer.Saved(3).value,Alias is Outer.Inner)\n'},
 'nested_default_capture': {'main.py': 'class Outer:\n'
                                       ' class Inner:\n'
                                       '  def __init__(self,value):self.value=value\n'
                                       ' def make(self,value,kind=Inner):return kind(value)\n'
                                       'print(Outer().make(7).value)\n'},
 'nested_definition_order': {'main.py': 'def mark(value):\n'
                                        ' print(value)\n'
                                        ' return value\n'
                                        'class Outer:\n'
                                        ' class Inner:\n'
                                        '  def __init__(self,value=mark("inner")):self.value=value\n'
                                        ' def method(self,value=mark("outer")):return value\n'
                                        'print(Outer.Inner().value,Outer().method())\n'},
 'class_scalar_namespace': {'main.py': 'class Box:\n'
                                       ' value=2\n'
                                       ' def read(self):return Box.value\n'
                                       'print(Box.value,Box().read())\n'
                                       'Box.value=9\n'
                                       'print(Box.value,Box().read())\n'},
 'class_list_namespace': {'main.py': 'class Box:\n'
                                     ' values=[]\n'
                                     ' def add(self,value):Box.values.append(value)\n'
                                     'def run():\n'
                                     ' b=Box()\n'
                                     ' b.add(2)\n'
                                     ' b.add(5)\n'
                                     ' print(Box.values)\n'
                                     'run()\n'},
 'class_alias_namespace': {'main.py': 'class Box:\n'
                                      ' values=[1]\n'
                                      'Alias=Box\n'
                                      'old=Box.values\n'
                                      'Alias.values=[2]\n'
                                      'print(old,Box.values,Alias is Box)\n'},
 'class_body_local_order': {'main.py': 'value=100\n'
                                       'class Box:\n'
                                       ' value=value+1\n'
                                       ' other=value+1\n'
                                       'print(value,Box.value,Box.other)\n'},
 'nested_scope_global_fallback': {'main.py': 'value=100\n'
                                             'class Outer:\n'
                                             ' value=5\n'
                                             ' class Inner:\n'
                                             '  snapshot=value\n'
                                             '  def read(self):return value\n'
                                             'print(Outer.value,Outer.Inner.snapshot,Outer.Inner().read())\n'},
 'class_method_global_lookup': {'main.py': 'value=100\n'
                                           'class Box:\n'
                                           ' value=5\n'
                                           ' def read(self):return value\n'
                                           'print(Box.value,Box().read())\n'},
 'class_field_tuple_list_alias': {'main.py': 'class Box:\n'
                                             ' values=[1]\n'
                                             ' pair=(values,2)\n'
                                             'Box.pair[0].append(7)\n'
                                             'print(Box.values,Box.pair)\n'},
 'class_missing_attribute': {'main.py': 'class Box:pass\nprint("before")\nprint(Box.missing)\n'},
 'class_delete_attribute': {'main.py': 'class Box:\n'
                                       ' value=7\n'
                                       'print(Box.value)\n'
                                       'del Box.value\n'
                                       'print(Box.value)\n'},
 'class_attribute_union': {'main.py': 'class Left:\n'
                                      ' value=1\n'
                                      'class Right:\n'
                                      ' value=2\n'
                                      'for selected in [Left,Right]:\n'
                                      ' print(selected.value)\n'
                                      ' selected.value+=10\n'
                                      'print(Left.value,Right.value)\n'},
 'imported_nested': {'main.py': 'import records\n'
                                'from records import Outer\n'
                                'print(records.Outer.Inner(8).get(),Outer.Inner(3).get(),Outer is '
                                'records.Outer)\n',
                     'records.py': 'class Outer:\n'
                                   ' class Inner:\n'
                                   '  def __init__(self,value):self.value=value\n'
                                   '  def get(self):return self.value+1\n'},
 'instance_class_fallback': {'main.py': 'class Box:\n'
                                        ' value=1\n'
                                        ' def read(self):return self.value\n'
                                        'b=Box()\n'
                                        'print(b.value,b.read())\n'
                                        'b.value=2\n'
                                        'print(b.value,b.read(),Box.value)\n'
                                        'del b.value\n'
                                        'print(b.value,b.read())\n'},
 'instance_mutable_class_alias': {'main.py': 'class Box:\n'
                                             ' values=[1]\n'
                                             ' def add(self,value):self.values.append(value)\n'
                                             'b=Box()\n'
                                             'old=b.values\n'
                                             'b.add(2)\n'
                                             'print(old,Box.values,b.values is Box.values)\n'
                                             'b.values=[7]\n'
                                             'b.add(8)\n'
                                             'print(old,Box.values,b.values)\n'},
 'class_field_type_rebinding': {'main.py': 'class Box:\n'
                                           ' value=1\n'
                                           'print(Box.value)\n'
                                           'Box.value="changed"\n'
                                           'print(Box.value)\n'
                                           'Box.value=None\n'
                                           'print(Box.value)\n'},
 'class_name_not_in_globals': {'main.py': 'class Box:\n'
                                          ' values=[1]\n'
                                          ' class Inner:pass\n'
                                          'print("values"in globals(),"Inner"in globals(),"Box"in '
                                          'globals())\n'},
 'class_delete_name_fallback': {'main.py': 'value=5\n'
                                           'class Box:\n'
                                           ' value=6\n'
                                           ' del value\n'
                                           ' snapshot=value\n'
                                           'print(value,Box.snapshot)\n'},
 'class_delete_missing_name': {'main.py': 'class Box:\n del xyzzy_no_field\n'},
 'instance_private_class_fallback': {'main.py': 'class Box:\n'
                                                ' __value=3\n'
                                                ' def read(self):return self.__value\n'
                                                'print(Box().read(),Box._Box__value)\n'},
 'class_field_loop_mutation': {'main.py': 'class Box:\n'
                                          ' value=1\n'
                                          ' def run(self):\n'
                                          '  for i in range(3):\n'
                                          '   print(self.value)\n'
                                          '   Box.value=i+4\n'
                                          'Box().run()\n'},
 'class_list_loop_rebind': {'main.py': 'class Box:\n'
                                       ' values=[1]\n'
                                       ' def run(self):\n'
                                       '  for i in range(3):\n'
                                       '   print(self.values)\n'
                                       '   Box.values=[i+4]\n'
                                       'Box().run()\n'},
 'class_local_augment': {'main.py': 'class Box:\n value=1\n value+=2\nprint(Box.value)\n'},
 'class_local_global_fallback_augment': {'main.py': 'value=5\n'
                                                    'class Box:\n'
                                                    ' value+=2\n'
                                                    'print(value,Box.value)\n'},
 'class_local_list_augment': {'main.py': 'class Box:\n values=[1]\n values += [2,3]\nprint(Box.values)\n'},
 'class_attribute_augment': {'main.py': 'class Box:\n value=1\nBox.value+=2\nprint(Box.value)\n'},
 'class_local_type_changing_augment': {'main.py': 'class Box:\n value=1\n value+=1.5\nprint(Box.value)\n'}}
UNSUPPORTED = {'method_rebind_guard': 'class Box:\n'
                        ' def read(self):return 1\n'
                        'def other(self):return 2\n'
                        'Box.read=other\n'
                        'print(Box().read())\n',
 'method_delete_guard': 'class Box:\n def read(self):return 1\ndel Box.read\n',
 'class_metadata_guard': 'class Box:pass\nmetadata=Box.__dict__\n',
 'finite_class_constructor_union': 'class Outer:\n'
                                   ' class Inner:\n'
                                   '  def __init__(self,value):self.value=value\n'
                                   'class Other:\n'
                                   ' def __init__(self,value):self.value=value+10\n'
                                   'def argument():\n'
                                   ' Outer.Inner=Other\n'
                                   ' return 2\n'
                                   'old=Outer.Inner\n'
                                   'print(Outer.Inner(argument()).value,Outer.Inner(2).value,old(2).value)\n'}


class ClassNamespaceCapabilityTests(unittest.TestCase):
    def test_class_local_builtin_fallback_remains_a_precise_required_boundary(self):
        source='class Box:\n int=int\nprint(Box.int)\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('builtin fallback',result.diagnostics[0].message)
            self.assertGreater(result.diagnostics[0].line,0)

    def test_implicit_class_metadata_lookup_is_not_confused_with_module_globals(self):
        source='class Box:\n "class doc"\n value=__doc__\nprint(Box.value)\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('metadata',result.diagnostics[0].message)
            self.assertIn('__doc__',result.diagnostics[0].message)
            self.assertGreater(result.diagnostics[0].line,0)

    def test_special_class_data_cannot_silently_change_python_layout_protocols(self):
        source='class Box:\n __slots__=()\n def __init__(self):self.value=1\nBox()\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('__slots__',result.diagnostics[0].message)
            self.assertIn('metadata',result.diagnostics[0].message)

    def test_generation_is_deterministic_across_python_hash_seeds(self):
        source=CASES['class_name_not_in_globals']['main.py']
        script=('import hashlib;from py2fastrust import transpile,TranspileOptions;'
                'source='+repr(source)+';result=transpile(source,TranspileOptions(filename="stable.py",integer=MODE,license="none"));'
                'assert result.success,result.diagnostics;print(hashlib.sha256(result.rust_source.encode()).hexdigest())')
        for mode in ('i64','i128','bigint'):
            hashes=[]
            for seed in ('0','1','2','23'):
                result=subprocess.run([sys.executable,'-B','-c',script.replace('MODE',repr(mode))],
                    cwd='/tmp',env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]),'PYTHONHASHSEED':seed},text=True,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                hashes.append(result.stdout.strip())
            self.assertEqual(len(set(hashes)),1,hashes)

    def test_original_ast_nodes_and_official_scope_tables_are_retained(self):
        from py2fastrust.native_linked_frames import LinkedModel
        from py2fastrust.native_module_linking import LinkedProgram
        source=CASES['nested_default_capture']['main.py']
        program=build_program(source,'main.py')
        unit=program.main
        before=ast.dump(unit.tree,include_attributes=True)
        nodes=tuple(ast.walk(unit.tree));table=unit.table
        linked=LinkedProgram.from_program(program)
        model=LinkedModel(linked,'main.py','i64','ascii').run()
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)
        self.assertIs(unit.table,table)
        self.assertEqual(len(model.classes),2)
        for owner in model.classes.values():
            self.assertIn(owner.node,nodes)
            self.assertIs(model.class_namespaces.scopes[linked.unit.scope_for(owner.node).ordinal],owner)

    def test_same_spelling_nested_classes_use_distinct_original_definition_keys(self):
        from py2fastrust.native_linked_frames import LinkedModel
        from py2fastrust.native_module_linking import LinkedProgram
        program=build_program(CASES['nested_same_spelling']['main.py'],'main.py')
        linked=LinkedProgram.from_program(program)
        model=LinkedModel(linked,'main.py','i64','ascii').run()
        children=[owner for owner in model.classes.values()if owner.node.name=='Item']
        self.assertEqual(len(children),2)
        self.assertNotEqual(model.class_key(children[0]),model.class_key(children[1]))
        self.assertNotEqual(linked.unit.ordinal(children[0].node),linked.unit.ordinal(children[1].node))

    def test_class_objects_used_as_values_select_the_existing_linked_carrier(self):
        from py2fastrust.native_module_linking import needs_linking
        for source in ('class Item:pass\nsaved=Item\n',
                       'class Item:pass\nprint(isinstance(Item(),Item))\n'):
            self.assertTrue(needs_linking(build_program(source,'main.py')))

    def test_existing_call_only_instance_lowering_keeps_its_ordinary_path(self):
        from py2fastrust.native_module_linking import needs_linking
        source='class Box:\n def __init__(self,value):self.value=value\nprint(Box(3).value)\n'
        self.assertFalse(needs_linking(build_program(source,'main.py')))

    def test_native_adapter_helper_classes_do_not_select_source_class_namespaces(self):
        from py2fastrust.native_class_namespaces import requires_namespaces
        from py2fastrust.native_module_linking import native_adapter_module_names
        source="from collections import deque\nvalues=deque([1,2])\nprint(*values,sep=':')\n"
        program=build_program(source,'main.py')
        adapters=native_adapter_module_names(program)
        self.assertIn('collections',adapters)
        self.assertFalse(requires_namespaces(program))

    def test_descriptor_mutation_metadata_and_unproved_constructor_union_are_positioned(self):
        for name,source in UNSUPPORTED.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename='main.py',integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertTrue(result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassNamespaceExecutionTests(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise


def _execution(files):
    def test(self):self.exercise(files)
    return test


for _name,_files in CASES.items():
    setattr(ClassNamespaceExecutionTests,'test_'+_name,_execution(_files))
