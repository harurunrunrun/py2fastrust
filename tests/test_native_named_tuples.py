"""Canonical NamedTuple factories preserve typed tuple and source-class semantics."""
import ast
import shutil
import unittest
from py2fastrust import transpile
from tests import test_native_frame_splits as support

CASES = {'fields_repr': 'from typing import NamedTuple\n'
                'class Point(NamedTuple):\n'
                ' x:int\n'
                ' y:int\n'
                'p=Point(2,3)\n'
                'print(p,p.x,p.y,len(p),bool(p),p[0],p[-1])\n',
 'keyword_defaults': 'from typing import NamedTuple\n'
                     'class Edge(NamedTuple):\n'
                     ' src:int\n'
                     ' dst:int=2\n'
                     ' cap:int=3\n'
                     'print(Edge(1),Edge(cap=9,src=4),Edge(dst=7,src=5))\n',
 'nested_edge': 'from typing import NamedTuple\n'
                'class Graph:\n'
                ' class Edge(NamedTuple):\n'
                '  src:int\n'
                '  dst:int\n'
                '  cap:int\n'
                '  flow:int\n'
                'print(Graph.Edge(0,1,4,2),Graph.Edge(0,1,4,2).cap)\n',
 'captured_factory_alias': 'import typing as types\n'
                           'Maker=types.NamedTuple\n'
                           'class Pair(Maker):\n'
                           ' left:int\n'
                           ' right:str\n'
                           'print(Pair(1,"a"))\n',
 'unpack_iteration': 'from typing import NamedTuple\n'
                     'class Triple(NamedTuple):\n'
                     ' x:int\n'
                     ' y:int\n'
                     ' z:int\n'
                     'p=Triple(2,3,5)\n'
                     'a,b,c=p\n'
                     'print(a,b,c,list(p),sum(p),tuple(p))\n'
                     'for value in p:print(value,end="|")\n'
                     'print()\n',
 'mixed_unpack': 'from typing import NamedTuple\n'
                 'class Row(NamedTuple):\n'
                 ' number:int\n'
                 ' word:str\n'
                 'r=Row(3,"cat")\n'
                 'a,b=r\n'
                 'print(a,b,list(r),tuple(r))\n',
 'empty_record': 'from typing import NamedTuple\n'
                 'class Empty(NamedTuple):pass\n'
                 'x=Empty()\n'
                 'print(x,len(x),bool(x),tuple(x),x==(),isinstance(x,tuple))\n',
 'structural_equality': 'from typing import NamedTuple\n'
                        'class Left(NamedTuple):\n'
                        ' x:int\n'
                        ' y:int\n'
                        'class Right(NamedTuple):\n'
                        ' x:int\n'
                        ' y:int\n'
                        'a=Left(1,2)\n'
                        'b=Right(1,2)\n'
                        'print(a==b,a==(1,2),(1,2)==a,a!=b,a<Left(2,1))\n',
 'nominal_isinstance': 'from typing import NamedTuple\n'
                       'class Left(NamedTuple):\n'
                       ' x:int\n'
                       'class Right(NamedTuple):\n'
                       ' x:int\n'
                       'for value in [Left(1),Right(1),(1,)]:\n'
                       ' '
                       'print(isinstance(value,Left),isinstance(value,Right),isinstance(value,tuple))\n',
 'slice_returns_plain_tuple': 'from typing import NamedTuple\n'
                              'class Triple(NamedTuple):\n'
                              ' x:int\n'
                              ' y:int\n'
                              ' z:int\n'
                              'p=Triple(1,2,3)\n'
                              'print(p[1:],p[::-1],isinstance(p[1:],Triple),isinstance(tuple(p),Triple))\n',
 'starred_calls': 'from typing import NamedTuple\n'
                  'class Pair(NamedTuple):\n'
                  ' x:int\n'
                  ' y:int\n'
                  'def add(a,b):return a+b\n'
                  'p=Pair(3,4)\n'
                  'print(*p,sep=":")\n'
                  'print(add(*p))\n',
 'field_metadata': 'from typing import NamedTuple\n'
                   'class Point(NamedTuple):\n'
                   ' x:int\n'
                   ' y:str\n'
                   'p=Point(1,"a")\n'
                   'print(Point._fields,p._fields)\n',
 'mutable_field_alias': 'from typing import NamedTuple\n'
                        'class Record(NamedTuple):\n'
                        ' items:list\n'
                        ' number:int\n'
                        'items=[1]\n'
                        'p=Record(items,2)\n'
                        'copy=p\n'
                        'items.append(7)\n'
                        'print(p,copy,p.items is items)\n',
 'shared_mutable_default': 'from typing import NamedTuple\n'
                           'class Record(NamedTuple):\n'
                           ' items:list=[]\n'
                           'a=Record()\n'
                           'b=Record()\n'
                           'a.items.append(3)\n'
                           'print(a,b,a.items is b.items)\n',
 'sort_records': 'from typing import NamedTuple\n'
                 'class Point(NamedTuple):\n'
                 ' x:int\n'
                 ' y:int\n'
                 'values=[Point(2,1),Point(1,5),Point(1,2)]\n'
                 'print(sorted(values),sorted(values,key=lambda p:(-p.x,p.y)))\n',
 'annotations_do_not_coerce': 'from typing import NamedTuple\n'
                              'class Item(NamedTuple):\n'
                              ' value:int\n'
                              'print(Item("text"),Item(3),Item(None))\n',
 'constructor_missing': 'from typing import NamedTuple\n'
                        'class Point(NamedTuple):\n'
                        ' x:int\n'
                        ' y:int\n'
                        'print("before")\n'
                        'Point(1)\n',
 'constructor_extra': 'from typing import NamedTuple\n'
                      'class Point(NamedTuple):\n'
                      ' x:int\n'
                      ' y:int\n'
                      'Point(1,2,3)\n',
 'constructor_keyword_error': 'from typing import NamedTuple\n'
                              'class Point(NamedTuple):\n'
                              ' x:int\n'
                              ' y:int\n'
                              'Point(x=1,z=2)\n',
 'constructor_duplicate': 'from typing import NamedTuple\n'
                          'class Point(NamedTuple):\n'
                          ' x:int\n'
                          ' y:int\n'
                          'Point(1,x=2,y=3)\n',
 'default_evaluation_order': 'from typing import NamedTuple\n'
                             'def mark(label,value):\n'
                             ' print(label)\n'
                             ' return value\n'
                             'class Point(NamedTuple):\n'
                             ' x:int=mark("x",1)\n'
                             ' y:int=mark("y",2)\n'
                             'print(Point(),Point(4))\n',
 'constructor_argument_order': 'from typing import NamedTuple\n'
                               'def mark(label,value):\n'
                               ' print(label)\n'
                               ' return value\n'
                               'class Point(NamedTuple):\n'
                               ' x:int\n'
                               ' y:int\n'
                               'print(Point(y=mark("y",2),x=mark("x",1)))\n',
 'unknown_forward_annotations': 'from typing import NamedTuple\n'
                                'class Item(NamedTuple):\n'
                                ' value:UnknownType\n'
                                'print(Item(3))\n',
 'dictionary_key_repr': 'from typing import NamedTuple\n'
                        'class Point(NamedTuple):\n'
                        ' x:int\n'
                        ' y:int\n'
                        'p=Point(1,2)\n'
                        'd={p:3}\n'
                        'print(d,d[(1,2)],next(iter(d)).x)\n',
 'set_key_equality': 'from typing import NamedTuple\n'
                     'class Point(NamedTuple):\n'
                     ' x:int\n'
                     ' y:int\n'
                     'a=Point(1,2)\n'
                     'b=Point(1,2)\n'
                     's={a,b}\n'
                     'print(len(s),a in s,(1,2) in s)\n',
 'dictionary_record_values': 'from typing import NamedTuple\n'
                             'class Edge(NamedTuple):\n'
                             ' to:int\n'
                             ' cap:int\n'
                             'd={1:Edge(2,7),2:Edge(3,4)}\n'
                             'for key,edge in d.items():print(key,edge.to,edge.cap)\n',
 'function_tuple_result': 'from typing import NamedTuple\n'
                          'class Pair(NamedTuple):\n'
                          ' x:int\n'
                          ' y:int\n'
                          'def make(x):return Pair(x,x+1)\n'
                          'a=make(4)\n'
                          'print(a,a.x,a.y)\n',
 'nested_tuple_field': 'from typing import NamedTuple\n'
                       'class Point(NamedTuple):\n'
                       ' x:int\n'
                       ' y:int\n'
                       'class Item(NamedTuple):\n'
                       ' point:Point\n'
                       ' cost:int\n'
                       'a=Item(Point(2,5),7)\n'
                       'print(a,a.point.x,tuple(a),a==(Point(2,5),7))\n',
 'nested_missing_argument': 'from typing import NamedTuple\n'
                            'class Graph:\n'
                            ' class Edge(NamedTuple):\n'
                            '  to:int\n'
                            '  cap:int\n'
                            'Graph.Edge(1)\n',
 'future_annotations': 'from __future__ import annotations\n'
                       'from typing import NamedTuple\n'
                       'class Item(NamedTuple):\n'
                       ' payload:UnknownType\n'
                       'print(Item(3))\n'}

BOUNDARIES = {'identity': 'from typing import NamedTuple\n'
             'class Item(NamedTuple):\n'
             ' value:int\n'
             'x=Item(1)\n'
             'print(x is x)\n',
 'functional_factory': 'from typing import NamedTuple\n'
                       'Point=NamedTuple("Point",[("x",int)])\n'
                       'print(Point(1))\n',
 'observable_annotation_call': 'from typing import NamedTuple\n'
                               'def marker():\n'
                               ' print("annotation")\n'
                               ' return int\n'
                               'class Item(NamedTuple):\n'
                               ' value:marker()\n'
                               'print(Item(3))\n',
 'custom_record_protocol': 'from typing import NamedTuple\n'
                           'class Item(NamedTuple):\n'
                           ' value:int\n'
                           ' def __repr__(self):return "custom"\n'
                           'print(Item(3))\n',
 'field_mutation': 'from typing import NamedTuple\n'
                   'class Point(NamedTuple):\n'
                   ' x:int\n'
                   'p=Point(1)\n'
                   'p.x=2\n',
 'field_descriptor_replacement': 'from typing import NamedTuple\n'
                                 'class Point(NamedTuple):\n'
                                 ' x:int\n'
                                 'p=Point(1)\n'
                                 'Point.x=7\n'
                                 'print(p.x)\n',
 'metadata_replacement': 'from typing import NamedTuple\n'
                         'class Point(NamedTuple):\n'
                         ' x:int\n'
                         'Point._fields=("changed",)\n'
                         'print(Point._fields)\n',
 'dynamic_slice': 'from typing import NamedTuple\n'
                  'class Pair(NamedTuple):\n'
                  ' x:int\n'
                  ' y:int\n'
                  'p=Pair(3,4)\n'
                  'n=int(input())\n'
                  'print(p[n:])\n',
 'arbitrary_base': 'class Base:pass\nclass Child(Base):pass\nprint(Child())\n',
 'effectful_annotation_subscript': 'from typing import NamedTuple\n'
                                   'def marker():\n'
                                   ' print("annotation")\n'
                                   ' return int\n'
                                   'class Point(NamedTuple):\n'
                                   ' x:list[marker()]\n'
                                   'print(Point([3]))\n',
 'tuple_key_alias': 'from typing import NamedTuple\n'
                    'class Point(NamedTuple):\n'
                    ' x:int\n'
                    ' y:int\n'
                    'p=Point(1,2)\n'
                    'd={p:3}\n'
                    'print(d[(1,2)],next(iter(d)).x)\n'
                    'd[(1,2)]=7\n'
                    'print(d,len(d),isinstance(next(iter(d)),Point))\n',
 'constructor_starred': 'from typing import NamedTuple\n'
                        'class Pair(NamedTuple):\n'
                        ' x:int\n'
                        ' y:int\n'
                        'args=(3,8)\n'
                        'print(Pair(*args))\n'}

class NamedTupleProtocolTests(unittest.TestCase):
    def test_unsupported_protocols_are_positioned_and_named(self):
        for name,source in BOUNDARIES.items():
            with self.subTest(case=name):
                result=transpile(source)
                self.assertFalse(result.success,result.diagnostics)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertGreater(result.diagnostics[0].line,0)
                self.assertIn('Source:',str(result.diagnostics[0]))

    def test_factory_keeps_original_ast_nodes(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_module_linking import generate_linked
        source=CASES['nested_edge']
        program=build_program(source,'main.py')
        original=[(unit,ast.dump(unit.tree,include_attributes=True),tuple(ast.walk(unit.tree)))for unit in program.units]
        self.assertIsNotNone(generate_linked(program,'i64'))
        for unit,dump,nodes in original:
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),dump)
            self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_nominal_kind_has_python_facing_diagnostic(self):
        result=transpile(BOUNDARIES['identity'])
        self.assertFalse(result.success)
        self.assertIn('Item[int]',str(result.diagnostics[0]))
        self.assertNotIn('unresolved NamedTupleType',str(result.diagnostics[0]))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NamedTupleExecutionTests(unittest.TestCase):
    exercise=support.SplitExecutionTests.exercise


def execution(source):
    def test(self):self.exercise(source)
    return test

for name,source in CASES.items():
    setattr(NamedTupleExecutionTests,'test_'+name,execution(source))
