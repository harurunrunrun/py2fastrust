"""Missing namespace fallback reports the original class or instance receiver."""
import ast
from itertools import count
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.native_class_namespaces import ClassMember, ClassNamespaces
from py2fastrust.native_classes import Cell, Expression, InstanceType
from py2fastrust.native_module_linking import ClassReferenceType
import test_native_source_state as source_tests


SOURCE = '''class Stack:
    items = []
    def __init__(self, value):
        self.value = value
    def __enter__(self):
        self.items.append(self.value)
    def __exit__(self, kind, error, trace):
        self.items.pop()
    @classmethod
    def current(cls):
        return cls.items[-1]
with Stack(7):
    del Stack.items
    print(Stack.current())
'''


def fixture():
    node=ast.parse('receiver.items',mode='eval').body
    owner=SimpleNamespace(index=0,node=ast.parse('class Stack: pass').body[0],fields={})
    member=ClassMember(owner,'items','slot')
    namespace=SimpleNamespace(index=lambda key:0,fields=lambda:[('slot','int')])
    registry=ClassNamespaces.__new__(ClassNamespaces)
    registry.model=SimpleNamespace(namespace=namespace)
    registry.attribute_reads={(17,id(node)):(member,)}
    registry.instance_reads={}
    sequence=count()
    sites=[]
    emitter=SimpleNamespace(plan=SimpleNamespace(index=17),
        kind=lambda node:'int',fresh=lambda:'temporary_'+str(next(sequence)),
        at=lambda code,site:sites.append(site)or code,
        coerce=lambda value,wanted,node:value.code)
    return registry,emitter,node,member,sites


class NamespaceAttributeErrorContracts(unittest.TestCase):
    def test_checked_get_changes_only_the_error_recipient(self):
        registry,emitter,node,member,sites=fixture()
        reference=Expression('captured_class',ClassReferenceType(0))
        with patch('py2fastrust.native_immutable_class_functions.emit',return_value=None):
            class_value=registry.emit_get(emitter,node,reference,member)
            instance_value=registry.emit_get(emitter,node,reference,member,instance=True)
        self.assertIn("type object 'Stack'",class_value.code)
        self.assertIn("'Stack' object",instance_value.code)
        self.assertNotIn('type object',instance_value.code)
        self.assertEqual(class_value.code.replace("type object 'Stack'","'Stack' object"),instance_value.code)
        self.assertEqual(sites,[node,node])
        self.assertEqual(class_value.kind,instance_value.kind)

    def test_instance_namespace_lookup_retains_actual_capture_and_source_error_site(self):
        registry,emitter,node,member,sites=fixture()
        registry.instance_reads[17,id(node)]=False
        receiver=Expression('captured_instance',InstanceType('Stack'))
        with patch('py2fastrust.native_immutable_class_functions.emit',return_value=None):
            value=registry.emit_attribute(emitter,node,receiver)
        self.assertIn('captured_instance.borrow().class_definition.clone()',value.code)
        self.assertIn("'Stack' object",value.code)
        self.assertNotIn('type object',value.code)
        self.assertEqual(sites,[node])

    def test_own_field_fallback_and_direct_class_read_keep_distinct_errors(self):
        registry,emitter,node,member,sites=fixture()
        member.owner.fields['items']=SimpleNamespace(cell=Cell('int'))
        registry.instance_reads[17,id(node)]=True
        with patch('py2fastrust.native_immutable_class_functions.emit',return_value=None), \
                patch('py2fastrust.native_copy_scalar_fields.load',return_value='own_field_option'):
            value=registry.emit_attribute(emitter,node,Expression('captured_instance',InstanceType('Stack')))
        self.assertIn('Some(value)=>',value.code)
        self.assertIn('None=>',value.code)
        self.assertIn("'Stack' object",value.code)
        registry.instance_reads.clear()
        with patch('py2fastrust.native_immutable_class_functions.emit',return_value=None), \
                patch('py2fastrust.native_immediate_classmethod.direct_payload',return_value=None):
            value=registry.emit_attribute(emitter,node,Expression('captured_class',ClassReferenceType(0)))
        self.assertIn("type object 'Stack'",value.code)


@unittest.skipUnless(source_tests.shutil.which('rustc'),'rustc is required')
class NamespaceAttributeErrorExecution(unittest.TestCase):
    def test_original_namespace_deletion_preserves_both_errors_and_cleanup_frames(self):
        with patch.dict(source_tests.SOURCES,{'namespace_delete':SOURCE}):
            source_tests.NativeSourceStateExecutionTests.exercise(self,'namespace_delete',('',))


if __name__=='__main__':
    unittest.main()
