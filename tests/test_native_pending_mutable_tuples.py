"""Retain pending pair producers in their real mutable allocation family."""
import shutil,unittest
from types import SimpleNamespace
from py2fastrust.native_classes import Cell,Model,shape
from py2fastrust.native_types import TupleType
import test_native_stdio as stdio_tests

SOURCE='class Labels:\n    def __init__(self,adj):self.n=len(adj)\n    def build(self):\n        components=[-1]*self.n\n        links=[]\n        for i in range(self.n):\n            components[i]=i%3\n            if i:\n                if i%2:links.append((components[i],i))\n                else:links.append((i,components[i]))\n        return components,links\nitem=Labels([[] for _ in range(int(input()))])\nfor _ in range(2):pass\ncomponents,_=item.build()\nlinks=_\ngroups={}\nfor i,component in enumerate(components):\n    if component in groups:groups[component].append(i)\n    else:groups[component]=[i]\nprint(len(groups),components,links)\nfor key in groups:print(key,groups[key])\n'

class PendingMutableProducerContracts(unittest.TestCase):
    def model(self,members):
        model=Model.__new__(Model)
        model.namespace=SimpleNamespace(contribute=lambda *args,**kwargs:False,detached=lambda value:value)
        model.member_allocations={member:object()for member in members}
        model.final=False
        return model

    def test_registered_element_retains_partial_pair_producer(self):
        destination=Cell();source=Cell('tuple',(Cell(),Cell('int')))
        model=self.model([destination])
        Model.contribute(model,destination,source,None)
        self.assertEqual(shape(destination),TupleType((None,'int')))
        self.assertIsNone(source.args[0].root().tag)
        self.assertIsNot(destination.root(),source.root())

    def test_registered_element_alias_uses_current_root_identity(self):
        member=Cell();destination=Cell();member.parent=destination
        model=self.model([member]);source=Cell('tuple',(Cell('int'),Cell()))
        Model.contribute(model,destination,source,None)
        self.assertEqual(shape(destination),TupleType(('int',None)))
        self.assertIs(member.root(),destination.root())

    def test_nonallocation_result_keeps_existing_deferred_abi(self):
        model=self.model([Cell()]);destination=Cell();source=Cell('tuple',(Cell(),Cell('none')))
        Model.contribute(model,destination,source,None)
        self.assertIsNone(shape(destination))
        self.assertEqual(shape(source),TupleType((None,'none')))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PendingMutableTupleTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_partial_pair_appends_keep_sibling_return_lists_distinct(self):
        self.differential(SOURCE,[b'0\n',b'1\n',b'8\n'],profiles=(False,True))

