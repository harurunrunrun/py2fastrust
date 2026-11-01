"""Native field deletion preserves presence, aliases and ordered target effects."""
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


CASES={'bound_none_delete_and_restore': 'class Box:\n'
                                  ' def __init__(self):self.value=None\n'
                                  'item=Box()\n'
                                  'del item.value\n'
                                  'item.value=None\n'
                                  'print(item.value is None)\n'
                                  'del item.value\n'
                                  "print('before missing')\n"
                                  'del item.value\n',
 'empty_loop_does_not_delete': 'class Box:\n'
                               ' def __init__(self,value):self.value=value\n'
                               'item=Box(3)\n'
                               'for _ in range(0):del item.value\n'
                               'print(item.value)\n',
 'known_missing_field': "class Box:pass\nitem=Box()\nprint('before missing')\ndel item.missing\n",
 'method_deletes_through_an_alias': 'class Box:\n'
                                    ' def __init__(self,value):self.value=value\n'
                                    ' def clear(self):del self.value\n'
                                    'item=Box(3)\n'
                                    'alias=item\n'
                                    'alias.clear()\n'
                                    'item.value=8\n'
                                    'print(alias is item,alias.value)\n',
 'multiple_targets_keep_original_order': 'class Box:\n'
                                         ' def __init__(self,value):self.value=value\n'
                                         'items=[Box(1),Box(2),Box(3)]\n'
                                         'del items.pop().value,items.pop().value\n'
                                         'print(len(items),items[0].value)\n',
 'multiple_targets_stop_at_first_error': 'class Box:\n'
                                         ' def __init__(self,value):self.value=value\n'
                                         'items=[Box(1),Box(2)]\n'
                                         "print('before deletion')\n"
                                         'del items.pop().missing,items.pop().value\n',
 'nested_delete_targets': 'class Box:\n'
                          ' def __init__(self,value):self.value=value\n'
                          'item=Box(1)\n'
                          'other=Box(2)\n'
                          'name=3\n'
                          'del (item.value,(name,other.value))\n'
                          'item.value=7\n'
                          'other.value=8\n'
                          'print(item.value,other.value)\n',
 'original_deleted_field_lifetime': 'class Leaf:\n'
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
 'private_field_and_name_deletion': 'class Box:\n'
                                    ' def __init__(self):self.__value=3\n'
                                    ' def clear(self):\n'
                                    '  del self.__value\n'
                                    'item=Box()\n'
                                    'item.clear()\n'
                                    "print('cleared')\n"
                                    'item.clear()\n',
 'receiver_is_evaluated_once': 'class Box:\n'
                               ' def __init__(self,value):self.value=value\n'
                               'items=[Box(1),Box(2)]\n'
                               'del items.pop().value\n'
                               'print(len(items),items[0].value)\n'}


def frames(text):return re.findall(r'File "[^\"]+", line (\d+), in ([^\n]+)',text)

def final_error(text):
    line=text.rstrip().splitlines()[-1]if text.strip()else''
    return re.sub(r"\. Did you mean: .*$",'',line)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class InstanceFieldDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-field-delete-')
        cls.cache={}

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def check(self,name,*,prune=True):
        source=CASES[name]
        expected=subprocess.run([sys.executable,'-I','-S','-c',source],text=True,capture_output=True,timeout=10)
        for mode in ('i64','i128','bigint'):
            with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend')):
                result=transpile(source,TranspileOptions(integer=mode,filename='field_delete.py',optimize=prune))
            self.assertTrue(result.success,result.diagnostics)
            for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                self.assertNotIn(marker,result.rust_source)
            for optimized in (False,True):
                key=source,mode,optimized,prune
                if key not in self.cache:
                    rust=Path(self.directory.name,hashlib.sha256(repr(key).encode()).hexdigest()+'.rs');rust.write_text(result.rust_source)
                    binary=rust.with_suffix('')
                    build=subprocess.run(['rustc','--edition=2021','--crate-name','field_delete',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    self.cache[key]=binary
                actual=subprocess.run([str(self.cache[key])],text=True,capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                with self.subTest(name=name,mode=mode,optimized=optimized,prune=prune):
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    self.assertEqual(frames(actual.stderr),frames(expected.stderr))
                    self.assertEqual(final_error(actual.stderr),final_error(expected.stderr))

    def test_original_shared_child_survives_parent_attribute_deletion(self):
        self.check('original_deleted_field_lifetime')

    def test_bound_none_and_known_missing_fields_keep_distinct_presence(self):
        for name in ('bound_none_delete_and_restore','known_missing_field'):
            with self.subTest(name=name):self.check(name)

    def test_receiver_expression_is_evaluated_once(self):self.check('receiver_is_evaluated_once')

    def test_multiple_targets_preserve_order_and_stop_at_first_error(self):
        for name in ('multiple_targets_keep_original_order','multiple_targets_stop_at_first_error'):
            with self.subTest(name=name):self.check(name)

    def test_private_fields_and_method_alias_receivers(self):
        for name in ('private_field_and_name_deletion','method_deletes_through_an_alias'):
            with self.subTest(name=name):self.check(name)

    def test_nested_targets_reuse_canonical_name_deletion(self):self.check('nested_delete_targets')

    def test_zero_trip_loop_does_not_delete_a_field(self):self.check('empty_loop_does_not_delete')

    def test_no_optimize_preserves_presence_errors_and_original_child_lifetime(self):
        self.check('original_deleted_field_lifetime',prune=False)

    def test_dictionary_descriptor_and_finalizer_protocols_remain_explicit(self):
        sources={
            '__dict__':"class Box:pass\nitem=Box()\ndel item.__dict__\n",
            '__delattr__':"class Box:\n def __delattr__(self,name):print('hook')\nitem=Box()\ndel item.value\n",
            '__delete__':"class Descriptor:\n def __delete__(self,instance):print('deleted')\nclass Box:\n value=Descriptor()\nitem=Box()\ndel item.value\n",
            '__del__':"class Leaf:\n def __del__(self):print('drop')\nclass Box:\n def __init__(self):self.value=Leaf()\nitem=Box()\ndel item.value\n"}
        for protocol,source in sources.items():
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertIn(protocol,str(result.diagnostics))
                self.assertRegex(str(result.diagnostics),'protocol|descriptor|dictionary')


if __name__=='__main__':unittest.main()
