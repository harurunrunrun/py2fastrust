"""Acyclic instance fields store shared handles and retain Python aliasing."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


CASES={'acyclic_three_class_chain': ('class Leaf:\n'
                               ' def __init__(self,value):self.value=value\n'
                               'class Branch:\n'
                               ' def __init__(self,child):self.child=child\n'
                               'class Root:\n'
                               ' def __init__(self,branch):self.branch=branch\n'
                               'leaf=Leaf(4)\n'
                               'root=Root(Branch(leaf))\n'
                               'root.branch.child.value+=3\n'
                               'print(root.branch.child is leaf,leaf.value)\n',
                               ('',)),
 'child_returned_from_function': ('class Leaf:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'class Holder:\n'
                                  ' def __init__(self,child):self.child=child\n'
                                  ' def get(self):return self.child\n'
                                  'def make(value):return Holder(Leaf(value)).get()\n'
                                  'leaf=make(4)\n'
                                  'leaf.value+=3\n'
                                  'print(leaf.value)\n',
                                  ('',)),
 'child_survives_temporary_parent_drop': ('class Leaf:\n'
                                          ' def __init__(self,value):self.value=value\n'
                                          'class Holder:\n'
                                          ' def __init__(self,child):self.child=child\n'
                                          'child=Holder(Leaf(5)).child\n'
                                          'child.value+=1\n'
                                          'print(child.value)\n',
                                          ('',)),
 'constructor_default_is_shared': ('class Leaf:\n'
                                   ' def __init__(self,value):self.value=value\n'
                                   'class Holder:\n'
                                   ' def __init__(self,child=Leaf(3)):self.child=child\n'
                                   'a=Holder()\n'
                                   'b=Holder()\n'
                                   'a.child.value+=2\n'
                                   'print(a.child is b.child,b.child.value)\n',
                                   ('',)),
 'container_fields_preserve_object_identity': ('class Leaf:\n'
                                               ' def __init__(self,value):self.value=value\n'
                                               'class Holder:\n'
                                               ' def __init__(self,child):\n'
                                               '  self.pair=(child,[child])\n'
                                               'leaf=Leaf(3)\n'
                                               'item=Holder(leaf)\n'
                                               'item.pair[1][0].value=8\n'
                                               'print(item.pair[0] is leaf,item.pair[1][0] is '
                                               'leaf,leaf.value)\n',
                                               ('',)),
 'cycle_through_callback_capture': ('class Holder:\n'
                                    ' def set(self,callback):self.callback=callback\n'
                                    'def make():\n'
                                    ' holder=Holder()\n'
                                    ' def callback():return holder\n'
                                    ' holder.set(callback)\n'
                                    ' return holder\n'
                                    'item=make()\n'
                                    'print(item.callback() is item)\n',
                                    ('',)),
 'cycle_through_list_field': ('class Leaf:\n'
                              ' def __init__(self):self.items=[]\n'
                              'class Holder:\n'
                              ' def __init__(self,child):self.child=child\n'
                              'leaf=Leaf()\n'
                              'item=Holder(leaf)\n'
                              'leaf.items.append(item)\n'
                              'print(leaf.items[0] is item)\n',
                              ('',)),
 'deleted_field_lifetime': ('class Leaf:\n'
                            ' def __init__(self,value):self.value=value\n'
                            'class Holder:\n'
                            ' def __init__(self,child):self.child=child\n'
                            'leaf=Leaf(3)\n'
                            'item=Holder(leaf)\n'
                            'saved=item.child\n'
                            'del item.child\n'
                            'saved.value=8\n'
                            'print(saved is leaf,leaf.value)\n'
                            'print(item.child)\n',
                            ('',)),
 'direct_alias_mutation': ('class Leaf:\n'
                           ' def __init__(self,value):self.value=value\n'
                           'class Holder:\n'
                           ' def __init__(self,child):self.child=child\n'
                           'leaf=Leaf(3)\n'
                           'holder=Holder(leaf)\n'
                           'alias=holder.child\n'
                           'alias.value+=4\n'
                           'print(holder.child is leaf,alias is '
                           'leaf,holder.child.value,leaf.value)\n',
                           ('',)),
 'direct_reference_cycle': ('class Node:\n'
                            ' def set(self,child):self.child=child\n'
                            'item=Node()\n'
                            'item.set(item)\n'
                            'print(item.child is item)\n',
                            ('',)),
 'field_aliases_in_iteration': ('class Leaf:\n'
                                ' def __init__(self,value):self.value=value\n'
                                'class Holder:\n'
                                ' def __init__(self,child):self.child=child\n'
                                'a=Holder(Leaf(1))\n'
                                'b=Holder(Leaf(2))\n'
                                'for item in [a,b]:item.child.value+=10\n'
                                'print(a.child.value,b.child.value)\n',
                                ('',)),
 'field_replacement_keeps_old_handle': ('class Leaf:\n'
                                        ' def __init__(self,value):self.value=value\n'
                                        'class Holder:\n'
                                        ' def __init__(self,child):self.child=child\n'
                                        'first=Leaf(1)\n'
                                        'second=Leaf(2)\n'
                                        'holder=Holder(first)\n'
                                        'saved=holder.child\n'
                                        'holder.child=second\n'
                                        'saved.value=7\n'
                                        'print(saved is first,holder.child is '
                                        'second,first.value,holder.child.value)\n',
                                        ('',)),
 'mutual_reference_cycle': ('class A:\n'
                            ' def set(self,value):self.child=value\n'
                            'class B:\n'
                            ' def set(self,value):self.child=value\n'
                            'a=A()\n'
                            'b=B()\n'
                            'a.set(b)\n'
                            'b.set(a)\n'
                            'print(a.child is b,b.child is a)\n',
                            ('',)),
 'nullable_field_rebinding': ('class Leaf:\n'
                              ' def __init__(self,value):self.value=value\n'
                              'class Holder:\n'
                              ' def __init__(self,child):self.child=child\n'
                              'leaf=Leaf(3)\n'
                              'item=Holder(leaf)\n'
                              'item.child=None\n'
                              'print(item.child is None)\n'
                              'item.child=leaf\n'
                              'print(item.child is leaf)\n',
                              ('',)),
 'object_field_type_changes': ('class Leaf:\n'
                               ' def __init__(self,value):self.value=value\n'
                               'class Holder:\n'
                               ' def __init__(self,child):self.child=child\n'
                               'leaf=Leaf(3)\n'
                               'item=Holder(leaf)\n'
                               'item.child=7\n'
                               'print(item.child)\n'
                               'item.child=leaf\n'
                               'print(item.child is leaf)\n',
                               ('',)),
 'private_and_builtin_spelled_fields': ('class Leaf:\n'
                                        ' def __init__(self,value):self.value=value\n'
                                        'class Holder:\n'
                                        ' def __init__(self,child):\n'
                                        '  self.__child=child\n'
                                        '  self.int=child\n'
                                        ' def get(self):return self.__child\n'
                                        'leaf=Leaf(1)\n'
                                        'holder=Holder(leaf)\n'
                                        'holder.int.value=7\n'
                                        'print(holder.get() is holder.int,holder.get().value)\n',
                                        ('',)),
 'python_finalizer_required': ('class Leaf:\n'
                               ' def __del__(self):print("finalized")\n'
                               'class Holder:\n'
                               ' def __init__(self,child):self.child=child\n'
                               'item=Holder(Leaf())\n'
                               'saved=item.child\n'
                               'del item\n'
                               'print("retained")\n'
                               'del saved\n'
                               'print("done")\n',
                               ('',)),
 'receiver_precedes_rebinding_argument': ('class Leaf:\n'
                                          ' def __init__(self,value):self.value=value\n'
                                          ' def add(self,value):self.value+=value\n'
                                          'class Holder:\n'
                                          ' def __init__(self,child):self.child=child\n'
                                          ' def replace(self):\n'
                                          '  self.child=Leaf(90)\n'
                                          '  return 4\n'
                                          'holder=Holder(Leaf(1))\n'
                                          'saved=holder.child\n'
                                          'holder.child.add(holder.replace())\n'
                                          'print(saved.value,holder.child.value,saved is '
                                          'holder.child)\n',
                                          ('',)),
 'same_class_chain_requires_stronger_proof': ('class Node:\n'
                                              ' def __init__(self,child):self.child=child\n'
                                              'first=Node(None)\n'
                                              'second=Node(first)\n'
                                              'print(second.child is first)\n',
                                              ('',)),
 'shared_children_across_holders': ('class Leaf:\n'
                                    ' def __init__(self,value):self.value=value\n'
                                    'class Holder:\n'
                                    ' def __init__(self,child):self.child=child\n'
                                    'child=Leaf(1)\n'
                                    'a=Holder(child)\n'
                                    'b=Holder(child)\n'
                                    'a.child.value=9\n'
                                    'print(a is b,a.child is b.child,b.child.value)\n',
                                    ('',)),
 'unbound_field_before_assignment': ('class Leaf:\n'
                                     ' def __init__(self,value):self.value=value\n'
                                     'class Holder:\n'
                                     ' def __init__(self,flag):\n'
                                     '  if flag:self.child=Leaf(3)\n'
                                     'item=Holder(int(input()))\n'
                                     'print("before")\n'
                                     'print(item.child.value)\n',
                                     ('0\n', '1\n'))}


def frames(text):
    return re.findall(r'File "[^\"]+", line (\d+), in ([^\n]+)',text)


def final_error(text):
    line=text.rstrip().splitlines()[-1]if text.strip()else""
    return re.sub(r"\. Did you mean: .*$","",line)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeInstanceFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="pytors-instance-fields-")
        cls.cache={}

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def compare(self,name,*,prune=True):
        source,inputs=CASES[name]
        expected=[subprocess.run([sys.executable,"-I","-S","-c",source],input=data,text=True,capture_output=True,timeout=10)for data in inputs]
        for mode in ("i64","i128","bigint"):
            with patch("py2fastrust.codegen.generate",side_effect=AssertionError("universal execution backend")):
                result=transpile(source,TranspileOptions(integer=mode,filename="instance_fields.py",optimize=prune))
            self.assertTrue(result.success,result.diagnostics)
            if prune:self.assertLess(len(result.rust_source.encode()),512*1024)
            for marker in ("enum Value","enum Op","struct Runtime","struct PegParser"):
                self.assertNotIn(marker,result.rust_source)
            for optimized in (False,True):
                key=(source,mode,optimized,prune)
                if key not in self.cache:
                    stem=hashlib.sha256(repr(key).encode()).hexdigest()
                    rust=Path(self.directory.name,stem+".rs");rust.write_text(result.rust_source)
                    binary=rust.with_suffix("")
                    compiled=subprocess.run(["rustc","--edition=2021","--crate-name","instance_fields",*(["-O"]if optimized else[]),str(rust),"-o",str(binary)],text=True,capture_output=True,timeout=120)
                    self.assertEqual(compiled.returncode,0,compiled.stderr)
                    self.cache[key]=binary
                for data,reference in zip(inputs,expected):
                    with self.subTest(name=name,mode=mode,optimized=optimized,input=data,prune=prune):
                        actual=subprocess.run([str(self.cache[key])],input=data,text=True,capture_output=True,timeout=10,env={**os.environ,"PATH":"/no-python-runtime"})
                        self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                        self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                        self.assertEqual(final_error(actual.stderr),final_error(reference.stderr))

    def test_aliases_and_rebinding_preserve_original_objects(self):
        for name in ("direct_alias_mutation","shared_children_across_holders","field_replacement_keeps_old_handle"):
            self.compare(name)

    def test_receiver_capture_precedes_argument_rebinding(self):
        self.compare("receiver_precedes_rebinding_argument")

    def test_acyclic_chains_and_nested_containers_preserve_handles(self):
        for name in ("acyclic_three_class_chain","container_fields_preserve_object_identity","field_aliases_in_iteration"):
            self.compare(name)

    def test_defaults_and_temporary_parent_drop_preserve_child_lifetime(self):
        for name in ("constructor_default_is_shared","child_survives_temporary_parent_drop","child_returned_from_function"):
            self.compare(name)

    def test_unbound_field_raises_before_nested_access(self):
        self.compare("unbound_field_before_assignment")

    def test_private_and_builtin_spelled_fields_keep_their_bindings(self):
        self.compare("private_and_builtin_spelled_fields")

    def test_no_optimize_uses_the_same_reference_storage(self):
        self.compare("receiver_precedes_rebinding_argument",prune=False)

    def test_reference_cycles_and_same_class_chains_require_a_collector_or_proof(self):
        for name in ("same_class_chain_requires_stronger_proof","direct_reference_cycle","mutual_reference_cycle","cycle_through_list_field","cycle_through_callback_capture"):
            source,_=CASES[name]
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                message=result.diagnostics[0].message
                self.assertIn("cycle",message)
                self.assertTrue("collector"in message or"collection"in message)
                self.assertNotIn("field representation is not implemented",message)

    def test_python_finalizers_remain_an_explicit_protocol_boundary(self):
        for mode in ("i64","i128","bigint"):
            result=transpile(CASES["python_finalizer_required"][0],TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertIn("__del__",result.diagnostics[0].message)


if __name__=="__main__":unittest.main()
