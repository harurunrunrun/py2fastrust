"""Tuple constructor ABIs do not feed storage unions into producer point values."""
import ast
import shutil
import unittest
import test_native_union_ordering as helpers
from py2fastrust import transpile,TranspileOptions
from unittest.mock import patch


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DirectionalTupleConstructorTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise


    def test_guarded_recursive_partition(self):
        self.exercise('class Node:\n def __init__(self,value,left=None,right=None):self.value=value;self.left=left;self.right=right\ndef divide(node,key):\n if not node:return None,None\n if key<node.value:\n  low,high=divide(node.left,key)\n  node.left=high\n  return low,node\n low,high=divide(node.right,key)\n node.right=low\n return node,high\nroot=Node(7,Node(3),Node(9))\na,b=divide(root,5)\nprint(a.value,b.value,b.left is None)\n',('',))

    def test_guarded_recursive_pairs(self):
        self.exercise('class Link:\n def __init__(self,value,next=None):self.value=value;self.next=next\ndef cut(link,count):\n if link is None:return None,None\n if count<=0:\n  print("cut",link.value)\n  return None,link\n first,last=cut(link.next,count-1)\n link.next=first\n print("keep",link.value)\n return link,last\nhead=Link(2,Link(5,Link(8)))\na,b=cut(head,int(input()))\nprint(a is head)\nif b is not None:print(b.value)\n',('0\n', '1\n', '5\n'))

    def test_loop_tuple_values(self):
        self.exercise('class Box:\n def __init__(self,value):self.value=value\ndef pack(value):return value,value\nfor index in range(4):\n value=None if index%2 else Box(index)\n if value is None:\n  pair=pack(value)\n  print(pair)\n else:\n  pair=pack(value)\n  print(value.value,pair[0] is value,pair[1] is value)\n',('',))

    def test_captured_tuple_values(self):
        self.exercise('def factory(first):\n def pack(second):return (first,second),(second,first)\n return pack\nfirst=factory(3)\nprint(first(4))\nsecond=factory("text")\nprint(second(False))\nprint(first(5))\n',('',))

    def test_pending_nested_tuple_list(self):
        self.exercise('def produce(number):return ((number,number+1),[number])\ndef collect(number):\n result=produce(number)\n result[1].append(number+2)\n return result\nprint(collect(4))\nprint(collect(8))\n',('',))

    def test_mutable_tuple_aliases(self):
        self.exercise('def pack(first,second):return first,(second,first)\na=[]\nb=[]\npair=pack(a,b)\na.append(3)\npair[1][0].append("other")\nprint(pair,a,b,pair[0] is pair[1][1],pair[0] is a)\n',('',))

    def test_pending_source_method_tuple(self):
        self.exercise('class Box:\n def __init__(self,value):self.value=value\n def pair(self,other):return self.value,other\ndef invoke(box,other):return box.pair(other)\nprint(invoke(Box(3),"x"))\nprint(invoke(Box("y"),False))\n',('',))

    def test_guards_after_tuple_creation(self):
        self.exercise('class Box:\n def __init__(self,value):self.value=value\ndef pack(box,flag):\n if box is None:return None,None\n pair=(box,None)\n if flag:return None,box\n print(box.value)\n return pair\nfor flag in (False,True):\n a,b=pack(Box(7),flag)\n print(a is None,b is None)\n',('',))

    def test_class_positional_tuple_retyping(self):
        self.exercise('class Pack:\n def pair(self,value):return value,(value,False)\npack=Pack()\nfor value in (3,"text",None):\n result=pack.pair(value)\n print(result)\n',('',))

    def test_abrupt_tuple_operand_order(self):
        self.exercise('class Box:\n def __init__(self,value):self.value=value\ndef observe(tag,value):\n print(tag,end="|")\n return value\ndef choose(flag):\n if flag:return Box(7)\n return None\nvalue=choose(int(input()))\nresult=(observe("first",1),observe("second",value.value),observe("third",3))\nprint(result)\n',('0\n', '1\n'))

    def test_zero_trip_unbound_tuple(self):
        self.exercise('class Box:\n def __init__(self,value):self.value=value\ndef pack(flag):\n for unused in range(flag):value=Box(7)\n return value.value,(value,None)\nresult=pack(int(input()))\nprint(result[0],result[1][0].value,result[1][1] is None)\n',('0\n', '1\n'))

    def test_return_tuple_defaults(self):
        self.exercise('def factory(value=[1]):\n def pack(other=2):return (value,other)\n return pack\nf=factory()\na=f()\na[0].append(3)\nprint(f(9),a)\n',('',))

    def test_loop_tuple_retains_mutable_handles(self):
        self.exercise('values=[]\nfor index in range(3):\n items=[]\n pair=(items,index)\n values.append(pair)\n pair[0].append(index)\nvalues[0][0].append(7)\nprint(values,values[0][0] is values[1][0])\n',('',))

    def test_none_object_none_positions(self):
        self.exercise('class Box:\n def __init__(self,value):self.value=value\ndef pack(value):return value,None\nfor value in (None,Box(7),None):\n pair=pack(value)\n if value is None:print(pair[0] is None,pair[1] is None)\n else:print(value.value,pair[0] is value,pair[1] is None)\n',('',))

    def test_distinct_list_producer_aliases(self):
        self.exercise('def pack(value):return value,(value,)\na=[1]\nb=["x"]\nleft=pack(a)\nright=pack(b)\na.append(2)\nb.append("y")\nprint(a,b,left,right,left[0] is a,right[1][0] is b,a[0]+9,b[0]+"z")\n',('',))

    def test_closure_retains_tuple_list(self):
        self.exercise('def capture(items):\n pair=(items,None)\n def read():return pair\n return read\nfirst_items=[1]\nsecond_items=["x"]\nfirst=capture(first_items)\nsecond=capture(second_items)\nfirst_items.append(2)\nsecond_items.append("y")\nprint(first(),second(),first()[0] is first_items,second()[0] is second_items)\n',('',))

    def test_ordered_tuple_callbacks(self):
        self.exercise('value=3\ndef first():\n print("first",value,end="|")\n return value\ndef later():\n global value\n value="changed"\n print("later",end="|")\n return value\npair=(first(),later())\nprint(pair,value)\n',('',))


class TupleConstructorFacts(unittest.TestCase):
    def test_guarded_operands_keep_point_kinds_after_final_tuple_transport(self):
        from py2fastrust.native_classes import Model,InstanceType,shape
        from py2fastrust.native_types import NullableType,TupleType
        original=Model.run
        for integer in ('i64','i128','bigint'):
            observed=[]
            def run(model):
                result=original(model)
                for plan in model.plans:
                    if getattr(plan.node,'name',None)!='divide':continue
                    if not isinstance(shape(plan.arguments['node']),NullableType):continue
                    point=[];constructors=[]
                    for node in ast.walk(plan.node):
                        if isinstance(node,ast.Attribute)and node.attr=='value':
                            point.append(shape(model.records[plan.index,id(node.value)]))
                        if isinstance(node,ast.Tuple)and any(isinstance(child,ast.Name)and child.id=='node'for child in node.elts):
                            raw=shape(model.constructors[plan.index,id(node)])
                            constructors.extend(raw.fields[index]for index,child in enumerate(node.elts)
                                                if isinstance(child,ast.Name)and child.id=='node')
                    observed.append((point,constructors,shape(plan.result)))
                return result
            with patch.object(Model,'run',run):
                result=transpile('class Node:\n def __init__(self,value,left=None,right=None):self.value=value;self.left=left;self.right=right\ndef divide(node,key):\n if not node:return None,None\n if key<node.value:\n  low,high=divide(node.left,key)\n  node.left=high\n  return low,node\n low,high=divide(node.right,key)\n node.right=low\n return node,high\nroot=Node(7,Node(3),Node(9))\na,b=divide(root,5)\nprint(a.value,b.value,b.left is None)\n',TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            self.assertTrue(observed)
            for point,constructors,output in observed:
                self.assertTrue(point)
                self.assertTrue(constructors)
                self.assertTrue(all(isinstance(kind,InstanceType)for kind in point),observed)
                self.assertTrue(all(kind==point[0]or kind==NullableType(point[0])for kind in constructors),observed)
                self.assertIsInstance(output,TupleType)
                self.assertTrue(all(isinstance(kind,NullableType)for kind in output.fields))
