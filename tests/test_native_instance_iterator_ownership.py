"""Shared typed iterator fields use registered families and complete ownership edges."""
import ast
from dataclasses import dataclass,field
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_class_storage import validate,validate_instance_graph
from py2fastrust.native_classes import Cell,ClassUnsupported,InstanceType
from py2fastrust.native_types import ListType,TupleType,NullableType


CASES={'bound_method_callback_cycle': 'class Holder:\n'
                                ' def accept(self,value):return value>0\n'
                                ' def initialize(self):self.stream=filter(self.accept,[1,2])\n'
                                'item=Holder()\n'
                                'item.initialize()\n'
                                'print(list(item.stream))\n',
 'closure_callback_cycle': 'class Holder:pass\n'
                           'def make():\n'
                           ' holder=Holder()\n'
                           ' def accept(value):return holder is holder\n'
                           ' holder.stream=filter(accept,[1])\n'
                           ' return holder\n'
                           'item=make()\n'
                           'print(list(item.stream))\n',
 'direct_shared_cursor': 'class Holder:\n'
                         ' def __init__(self,stream):self.stream=stream\n'
                         'stream=iter([1,2,3])\n'
                         'item=Holder(stream)\n'
                         'print(item.stream is '
                         'stream,next(item.stream),next(stream),next(item.stream))\n',
 'field_rebind_keeps_old_cursor': 'class Holder:\n'
                                  ' def __init__(self,stream):self.stream=stream\n'
                                  'stream=iter([1,2])\n'
                                  'item=Holder(stream)\n'
                                  'saved=item.stream\n'
                                  'item.stream=stream\n'
                                  'print(next(saved),next(item.stream),saved is item.stream)\n',
 'filter_closure_without_cycle': 'class Holder:\n'
                                 ' def __init__(self,stream):self.stream=stream\n'
                                 ' def values(self):return list(self.stream)\n'
                                 'def make(limit):\n'
                                 ' def accept(value):return value>limit\n'
                                 ' return Holder(filter(accept,[1,4,2,5]))\n'
                                 'item=make(2)\n'
                                 'print(item.values(),item.values())\n',
 'lambda_callback_cycle': 'class Holder:pass\n'
                          'def make():\n'
                          ' holder=Holder()\n'
                          ' holder.stream=filter(lambda value:holder is holder,[1])\n'
                          ' return holder\n'
                          'item=make()\n'
                          'print(list(item.stream))\n',
 'list_iterator_cycle': 'class Holder:pass\n'
                        'values=[]\n'
                        'stream=iter(values)\n'
                        'values.append(stream)\n'
                        'print(next(stream) is stream)\n',
 'nested_object_source_cycle': 'class Holder:\n'
                               ' def __init__(self):self.streams=(iter([self]),)\n'
                               'item=Holder()\n'
                               'print(next(item.streams[0]) is item)\n',
 'nested_tuple_and_list_cursor_aliases': 'class Holder:\n'
                                         ' def '
                                         '__init__(self,stream):self.pair=(stream,[stream,stream])\n'
                                         'stream=iter([2,4,6])\n'
                                         'item=Holder(stream)\n'
                                         'print(item.pair[0] is '
                                         'item.pair[1][0],next(item.pair[0]),next(item.pair[1][1]),next(stream))\n',
 'object_source_cycle': 'class Holder:\n'
                        ' def __init__(self):self.stream=iter([self])\n'
                        'item=Holder()\n'
                        'print(next(item.stream) is item)\n',
 'repeated_list_cursor_aliases': 'class Holder:\n'
                                 ' def __init__(self,stream):self.streams=[stream]*2\n'
                                 'stream=iter([3,5,7])\n'
                                 'item=Holder(stream)\n'
                                 'print(item.streams[0] is '
                                 'item.streams[1],next(item.streams[0]),next(item.streams[1]),next(stream))\n',
 'source_objects_keep_identity': 'class Leaf:\n'
                                 ' def __init__(self,value):self.value=value\n'
                                 'class Holder:\n'
                                 ' def __init__(self,source):self.stream=iter(source)\n'
                                 'leaf=Leaf(3)\n'
                                 'item=Holder([leaf])\n'
                                 'saved=next(item.stream)\n'
                                 'saved.value=8\n'
                                 'print(saved is leaf,leaf.value)\n'}

@dataclass(frozen=True)
class OwnedDescriptor:
    index:int
    record:object=field(compare=False,hash=False)
    _native_class_iterator=True
    # The iterator branch must still validate ownership before this old escape.
    _native_stored_reference=True
    @property
    def _native_owned_kinds(self):return self.record.owned


class IteratorOwnershipMetadataTests(unittest.TestCase):
    def descriptor(self,index=0,owned=()):
        return OwnedDescriptor(index,SimpleNamespace(owned=owned))

    def model(self,*descriptors):
        records=[kind.record for kind in descriptors]
        return SimpleNamespace(iterators=SimpleNamespace(owns=lambda kind:
            isinstance(kind,OwnedDescriptor)and 0<=kind.index<len(records)and records[kind.index]is kind.record))

    def test_registered_families_are_valid_inside_nested_storage(self):
        kind=self.descriptor();model=self.model(kind);node=ast.parse('value').body[0]
        for cell in (Cell(kind),Cell('list',(Cell(kind),)),Cell('tuple',(Cell(kind),Cell('list',(Cell(kind),))))):
            validate(cell,node,'i64',model=model)

    def test_unregistered_or_foreign_families_cannot_use_reference_escape(self):
        kind=self.descriptor();other=self.descriptor();node=ast.parse('value').body[0]
        for model in (None,self.model(),self.model(other)):
            for cell in (Cell(kind),Cell('list',(Cell(kind),)),Cell('tuple',(Cell(kind),))):
                with self.assertRaisesRegex(ClassUnsupported,'current typed iterator registry'):
                    validate(cell,node,'i64',model=model)

    def test_method_shadow_store_reports_the_descriptor_boundary(self):
        source='class Holder:\n def method(self):return 1\nitem=Holder()\nitem.method=3\n'
        result=transpile(source,TranspileOptions(filename='ownership.py'))
        self.assertFalse(result.success)
        self.assertRegex(str(result.diagnostics),'instance-dictionary storage and descriptor lookup')
        self.assertNotIn('reading this method',str(result.diagnostics))

    def graph(self,fields):
        classes={name:SimpleNamespace(used=True,node=ast.parse('class '+name+':pass').body[0],
            fields={str(i):SimpleNamespace(cell=cell)for i,cell in enumerate(cells)})for name,cells in fields.items()}
        return SimpleNamespace(classes=classes,display_name=lambda name:name)

    def test_descriptor_source_shapes_add_direct_instance_edges(self):
        kind=self.descriptor(owned=(ListType(InstanceType('Holder')),))
        with self.assertRaisesRegex(ClassUnsupported,'Holder -> Holder'):
            validate_instance_graph(self.graph({'Holder':[Cell(kind)]}))

    def test_nested_owned_shapes_close_indirect_instance_cycles(self):
        kind=self.descriptor(owned=(TupleType((NullableType(ListType(InstanceType('Leaf'))),)),))
        with self.assertRaisesRegex(ClassUnsupported,'reference cycle'):
            validate_instance_graph(self.graph({'Holder':[Cell('tuple',(Cell(kind),))],'Leaf':[Cell('object',('Holder',))]}))

    def test_descriptor_expansion_is_finite_and_acyclic_object_edges_stay_valid(self):
        kind=self.descriptor();kind.record.owned=(ListType(kind),InstanceType('Leaf'))
        validate_instance_graph(self.graph({'Holder':[Cell(kind)],'Leaf':[Cell('int')]}))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class InstanceIteratorExecutionTests(unittest.TestCase):
    def check(self,name):
        source=CASES[name]
        expected=subprocess.run([sys.executable,'-I','-S','-c',source],text=True,capture_output=True,timeout=10)
        self.assertEqual(expected.returncode,0,expected.stderr)
        with tempfile.TemporaryDirectory(prefix='pytors-instance-iterator-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend')):
                    result=transpile(source,TranspileOptions(integer=mode,filename='ownership.py'))
                self.assertTrue(result.success,result.diagnostics)
                rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    build=subprocess.run(['rustc','--edition=2021','--crate-name','ownership',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    with self.subTest(name=name,mode=mode,optimized=optimized):
                        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected.stdout,''))

    def test_direct_and_nested_shared_cursor_fields(self):
        for name in ('direct_shared_cursor','nested_tuple_and_list_cursor_aliases','repeated_list_cursor_aliases'):
            with self.subTest(name=name):self.check(name)

    def test_source_instance_identity_and_shared_filter_lifetime(self):
        for name in ('source_objects_keep_identity','filter_closure_without_cycle','field_rebind_keeps_old_cursor'):
            with self.subTest(name=name):self.check(name)

    def test_actual_ownership_cycles_keep_the_required_collector_boundary(self):
        for name in ('object_source_cycle','nested_object_source_cycle','closure_callback_cycle','lambda_callback_cycle','list_iterator_cycle'):
            for mode in ('i64','i128','bigint'):
                result=transpile(CASES[name],TranspileOptions(integer=mode,filename='ownership.py'))
                self.assertFalse(result.success,name)
                self.assertRegex(str(result.diagnostics),'cycle|recursive',name)
                self.assertNotIn('RecursionError',str(result.diagnostics))

    def test_bound_method_callback_cycle_remains_an_explicit_collector_gap(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['bound_method_callback_cycle'],TranspileOptions(integer=mode,filename='ownership.py'))
            self.assertFalse(result.success)
            self.assertRegex(str(result.diagnostics),"reference cycle.*collector")


if __name__=='__main__':unittest.main()
