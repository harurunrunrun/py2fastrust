"""Exact builtin list insertion/removal across owned and shared native storage."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from tests import test_native_frame_splits as support

CASES = {'insert_positions': {'source': 'a=[2,4]\n'
                                'print(a.insert(0,1),a)\n'
                                'print(a.insert(-1,3),a)\n'
                                'print(a.insert(-100,0),a)\n'
                                'print(a.insert(100,5),a)\n'
                                'print(a.insert(True,9),a)\n',
                      'expected_by_integer': {}},
 'frame_insert_positions': {'source': 'class Scope:\n'
                                      ' pass\n'
                                      'a=[2,4]\n'
                                      'print(a.insert(0,1),a)\n'
                                      'print(a.insert(-1,3),a)\n'
                                      'print(a.insert(-100,0),a)\n'
                                      'print(a.insert(100,5),a)\n'
                                      'print(a.insert(True,9),a)\n',
                            'expected_by_integer': {}},
 'insert_string_empty': {'source': 'a=[]\n'
                                   'a.insert(0,"b")\n'
                                   'a.insert(-1,"a")\n'
                                   'a.insert(100,"c")\n'
                                   'print(a,len(a),a.count("b"))\n',
                         'expected_by_integer': {}},
 'insert_tuple': {'source': 'a=[(1,"a"),(3,"c")]\na.insert(1,(2,"b"))\nprint(a,a.index((2,"b")))\n',
                  'expected_by_integer': {}},
 'remove_first_bool': {'source': 'a=[0,False,1,True,1,2]\n'
                                 'print(a.remove(False),a)\n'
                                 'print(a.remove(True),a)\n'
                                 'print(a.remove(1),a)\n',
                       'expected_by_integer': {}},
 'remove_strings_bytes': {'source': 'a=["red","blue","red"]\n'
                                    'b=[b"x",b"y",b"x"]\n'
                                    'print(a.remove("red"),a,b.remove(b"x"),b)\n',
                          'expected_by_integer': {}},
 'remove_tuples': {'source': 'a=[(1,"x"),(2,"y"),(1,"x")]\nprint(a.remove((1,"x")),a)\n',
                   'expected_by_integer': {}},
 'remove_cross_scalar': {'source': 'a=[None,True,2,"x",b"y"]\n'
                                   'print(a.remove(1),a)\n'
                                   'print(a.remove(None),a)\n'
                                   'print(a.remove(b"y"),a)\n',
                         'expected_by_integer': {}},
 'remove_missing': {'source': 'a=[1,2,3]\nprint("before",a)\na.remove(9)\n', 'expected_by_integer': {}},
 'remove_empty': {'source': 'a=[]\nprint("before",a)\na.remove("x")\n', 'expected_by_integer': {}},
 'insert_float_index': {'source': 'a=[1]\na.insert(1.5,2)\n', 'expected_by_integer': {}},
 'frame_insert_none_index': {'source': 'class Scope:\n pass\na=[]\na.insert(None,2)\n',
                             'expected_by_integer': {}},
 'insert_ssize_bounds': {'source': 'a=[2]\n'
                                   'a.insert(9223372036854775807,3)\n'
                                   'a.insert(-9223372036854775808,1)\n'
                                   'print(a)\n',
                         'expected_by_integer': {}},
 'insert_positive_overflow': {'source': 'a=[1,2]\na.insert(1<<63,3)\nprint(a)\n',
                              'expected_by_integer': {'i64': ('[3, 1, 2]\n', '', 0)}},
 'insert_negative_overflow': {'source': 'a=[1,2]\na.insert(-(1<<63)-1,3)\nprint(a)\n',
                              'expected_by_integer': {'i64': ('[1, 2, 3]\n', '', 0)}},
 'insert_huge_shift': {'source': 'a=[1,2]\na.insert(1<<2000,3)\nprint(a)\n',
                       'expected_by_integer': {'i64': ('[3, 1, 2]\n', '', 0),
                                               'i128': ('[3, 1, 2]\n', '', 0)}},
 'insert_no_args': {'source': 'a=[]\na.insert()\n', 'expected_by_integer': {}},
 'insert_extra_args': {'source': 'a=[]\na.insert(print("one"),print("two"),print("three"))\n',
                       'expected_by_integer': {}},
 'insert_keywords': {'source': 'a=[]\na.insert(index=print("index"),object=print("object"))\n',
                     'expected_by_integer': {}},
 'remove_no_args': {'source': 'a=[]\na.remove()\n', 'expected_by_integer': {}},
 'remove_extra_args': {'source': 'a=[1]\na.remove(print("one"),print("two"))\n', 'expected_by_integer': {}},
 'remove_keywords': {'source': 'a=[]\na.remove(value=print("value"))\n', 'expected_by_integer': {}},
 'insert_alias_nested': {'source': 'class Box:\n'
                                   ' def __init__(self):\n'
                                   '  self.values=[[1],[3]]\n'
                                   'b=Box()\n'
                                   'alias=b.values\n'
                                   'item=[2]\n'
                                   'print(b.values.insert(1,item),alias)\n'
                                   'item.append(7)\n'
                                   'print(b.values,alias)\n',
                         'expected_by_integer': {}},
 'remove_nested_alias': {'source': 'class Box:\n'
                                   ' def __init__(self):\n'
                                   '  self.values=[[1],[2],[1]]\n'
                                   'b=Box()\n'
                                   'alias=b.values\n'
                                   'print(b.values.remove([1]),alias)\n'
                                   'alias[1].append(8)\n'
                                   'print(b.values)\n',
                         'expected_by_integer': {}},
 'insert_rebind_receiver': {'source': 'class Box:\n'
                                      ' def __init__(self):\n'
                                      '  self.values=[1,3]\n'
                                      ' def index(self):\n'
                                      '  print("index")\n'
                                      '  self.values=[99]\n'
                                      '  return 1\n'
                                      ' def value(self):\n'
                                      '  print("value")\n'
                                      '  self.values.append(100)\n'
                                      '  return 2\n'
                                      'b=Box()\n'
                                      'old=b.values\n'
                                      'print(b.values.insert(b.index(),b.value()),old,b.values)\n',
                            'expected_by_integer': {}},
 'remove_rebind_receiver': {'source': 'class Box:\n'
                                      ' def __init__(self):\n'
                                      '  self.values=[1,2,3]\n'
                                      ' def value(self):\n'
                                      '  print("value")\n'
                                      '  self.values=[99]\n'
                                      '  return 2\n'
                                      'b=Box()\n'
                                      'old=b.values\n'
                                      'print(b.values.remove(b.value()),old,b.values)\n',
                            'expected_by_integer': {}},
 'insert_argument_mutation': {'source': 'class Box:\n'
                                        ' def __init__(self):\n'
                                        '  self.values=[1,2,3]\n'
                                        ' def index(self):\n'
                                        '  print("index",self.values.pop())\n'
                                        '  return -1\n'
                                        ' def value(self):\n'
                                        '  print("value",self.values.pop())\n'
                                        '  return 9\n'
                                        'b=Box()\n'
                                        'print(b.values.insert(b.index(),b.value()),b.values)\n',
                              'expected_by_integer': {}},
 'remove_argument_mutation': {'source': 'class Box:\n'
                                        ' def __init__(self):\n'
                                        '  self.values=[1,2,1]\n'
                                        'b=Box()\n'
                                        'print(b.values.remove(b.values.pop()),b.values)\n',
                              'expected_by_integer': {}},
 'remove_object_identity': {'source': 'class Item:\n'
                                      ' def __init__(self,n):\n'
                                      '  self.n=n\n'
                                      'a=Item(1)\n'
                                      'b=Item(2)\n'
                                      'values=[a,b,a]\n'
                                      'print(values.remove(a),len(values),values[0] is b,values[1] is a)\n',
                            'expected_by_integer': {}},
 'insert_then_remove_result': {'source': 'a=[1,3]\n'
                                         'x=a.insert(1,2)\n'
                                         'y=a.remove(1)\n'
                                         'print(x is None,y is None,a)\n',
                               'expected_by_integer': {}},
 'insert_then_break': {'source': 'a=[1,2,3]\nfor x in a:\n a.insert(0,9)\n print(x,a)\n break\nprint(a)\n',
                       'expected_by_integer': {}},
 'remove_current': {'source': 'a=[1,2,3,4,5]\nfor x in a:\n print(x,end="|")\n a.remove(x)\nprint(a)\n',
                    'expected_by_integer': {}},
 'ordinary_insert_pop': {'source': 'a=[1,2,3]\nprint(a.insert(a.pop(),a.pop()),a)\n',
                         'expected_by_integer': {}},
 'ordinary_remove_pop': {'source': 'a=[1,2,1]\nprint(a.remove(a.pop()),a)\n', 'expected_by_integer': {}},
 'ordinary_row_methods': {'source': 'a=[[1,3],[5]]\na[0].insert(1,2)\na[1].remove(5)\nprint(a)\n',
                          'expected_by_integer': {}},
 'empty_float_literal': {'source': 'a=[]\na.remove(1.5)\n', 'expected_by_integer': {}},
 'frame_union_index': {'source': 'class Box:\n'
                                 ' def __init__(self):self.values=[1,2]\n'
                                 ' def run(self,index):\n'
                                 '  print(self.values.insert(index,9),self.values)\n'
                                 'b=Box()\n'
                                 'for index in [False,True,-1,1.5]:b.run(index)\n',
                       'expected_by_integer': {}},
 'dict_index_type_error': {'source': 'class Box:\n'
                                     ' def run(self,index):\n'
                                     '  a=[1]\n'
                                     '  a.insert(index,2)\n'
                                     'Box().run({"x":1})\n',
                           'expected_by_integer': {}},
 'argument_failure_before_binding': {'source': 'a=[]\na.insert(print("first"),1//0,print("unreached"))\n',
                                     'expected_by_integer': {}},
 'mixed_insert_remove': {'source': 'a=[]\n'
                                   'a.insert(0,1)\n'
                                   'a.insert(1,"x")\n'
                                   'a.insert(2,None)\n'
                                   'print(a.remove(1),a)\n',
                         'expected_by_integer': {}}}
UNSUPPORTED = {'custom_index': 'class Index:\n def __index__(self):\n  return 0\na=[1]\na.insert(Index(),2)\nprint(a)\n',
 'custom_equality_mutates': 'class Item:\n'
                            ' def __init__(self,owner):\n'
                            '  self.owner=owner\n'
                            ' def __eq__(self,other):\n'
                            '  self.owner.clear()\n'
                            '  return True\n'
                            'a=[]\n'
                            'a.append(Item(a))\n'
                            'print(a.remove(7),a)\n',
 'nan_identity': 'nan=float("nan")\na=[nan]\nprint(a.remove(nan),a)\n',
 'cycle_insert': 'a=[]\na.insert(0,a)\nprint(a[0] is a)\n'}
CALLBACKS = [{'source': 'class Item:\n'
            ' def __init__(self,owner):self.owner=owner\n'
            ' def __eq__(self,other):\n'
            '  print("compare")\n'
            '  self.owner.clear(); return True\n'
            'a=[]\n'
            'item=Item(a)\n'
            'a.append(item)\n'
            '\n'
            'print(a.remove(9),[1 if isinstance(value,Item) else value for value in a])\n',
  'stdout': 'compare\nNone []\n'},
 {'source': 'class Item:\n'
            ' def __init__(self,owner):self.owner=owner\n'
            ' def __eq__(self,other):\n'
            '  print("compare")\n'
            '  self.owner.insert(0,7); return True\n'
            'a=[]\n'
            'item=Item(a)\n'
            'a.append(item)\n'
            '\n'
            'print(a.remove(9),[1 if isinstance(value,Item) else value for value in a])\n',
  'stdout': 'compare\nNone [1]\n'},
 {'source': 'class Item:\n'
            ' def __init__(self,owner):self.owner=owner\n'
            ' def __eq__(self,other):\n'
            '  print("compare")\n'
            '  self.owner.append(9); return False\n'
            'a=[]\n'
            'item=Item(a)\n'
            'a.append(item)\n'
            '\n'
            'print(a.remove(9),[1 if isinstance(value,Item) else value for value in a])\n',
  'stdout': 'compare\nNone [1]\n'},
 {'source': 'class Item:\n'
            ' def __init__(self,owner):self.owner=owner\n'
            ' def __eq__(self,other):\n'
            '  print("compare")\n'
            '  self.owner.pop(); return True\n'
            'a=[]\n'
            'item=Item(a)\n'
            'a.append(item)\n'
            'a.append(2)\n'
            'print(a.remove(9),[1 if isinstance(value,Item) else value for value in a])\n',
  'stdout': 'compare\nNone []\n'},
 {'source': 'class Item:\n'
            ' def __init__(self,owner):self.owner=owner\n'
            ' def __eq__(self,other):\n'
            '  print("compare")\n'
            '  self.owner.pop(0); return False\n'
            'a=[]\n'
            'item=Item(a)\n'
            'a.append(item)\n'
            'a.extend([9,9])\n'
            'print(a.remove(9),[1 if isinstance(value,Item) else value for value in a])\n',
  'stdout': 'compare\nNone [9]\n'}]


class ListMethodCapabilityTests(unittest.TestCase):
    def test_canonical_list_signatures_share_positional_binding(self):
        from py2fastrust.native_sequence_plans import sequence_method
        from py2fastrust.native_types import ListType,SharedListType
        from py2fastrust.call_semantics import normalize_call
        for kind in ('list_int',ListType('str'),SharedListType('str')):
            for method,source,names in [('insert','a.insert(index(),value())',('index','value')),('remove','a.remove(value())',('value',))]:
                plan=sequence_method(kind,method)
                call=plan.signature.plan(normalize_call(ast.parse(source).body[0].value),implicit_count=1)
                self.assertEqual(call.argument_parameters,names)
                self.assertTrue(plan.mutates)
                self.assertEqual(plan.result,'none')
        self.assertIsNone(sequence_method('str','insert'))

    def test_original_ast_nodes_are_retained(self):
        from py2fastrust.native_classes import try_generate_classes
        source=CASES['insert_rebind_receiver']['source']
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(try_generate_classes(source,'main.py','i64',unit=unit))
        self.assertEqual(before,ast.dump(unit.tree,include_attributes=True))
        self.assertEqual(nodes,tuple(ast.walk(unit.tree)))

    def test_ordinary_owned_calls_keep_the_static_path(self):
        from py2fastrust.native_frame_selection import select_frames
        for name in ('insert_positions','remove_first_bool','remove_strings_bytes'):
            self.assertFalse(select_frames(build_program(CASES[name]['source'],'main.py').main).required)

    def test_custom_protocols_and_cycles_stay_explicit(self):
        for name,source in UNSUPPORTED.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertTrue(result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ListMethodExecutionTests(unittest.TestCase):
    exercise=support.SplitExecutionTests.exercise


def _execution(case):
    def test(self):
        self.exercise(case['source'],expected_by_integer=case['expected_by_integer'])
    return test


for _name,_case in CASES.items():
    setattr(ListMethodExecutionTests,'test_'+_name,_execution(_case))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class RemovalBorrowScopeTests(unittest.TestCase):
    def test_callback_can_clear_insert_append_or_remove_without_a_live_list_borrow(self):
        # Exercise the generic equality callback contract in isolation. Python
        # class __eq__ lowering itself remains an explicit diagnostic above.
        from py2fastrust.native import _Expression
        from py2fastrust.native_sequence_methods import lower
        from py2fastrust.native_sequence_plans import sequence_method
        from py2fastrust.native_sequence_storage import SequenceStorage
        from py2fastrust.native_types import ListType
        class Generator:
            bits=64
            count=0
            def temporary(self):
                self.count+=1
                return 'local_'+str(self.count)
            def at(self,code,node):return '('+code+')?'
            def sequence_equal(self,left,right,node):
                return 'equal(&owner,&'+left.code+',&'+right.code+',mode)'
        generator=Generator()
        storage=SequenceStorage((), '&(owner.borrow())[..]','&mut *owner.borrow_mut()',ListType('int'),shared=True)
        generated=lower(generator,storage,sequence_method(storage.kind,'remove'),{'value':_Expression('needle','int')},None,{})
        rust=r"""
use std::rc::Rc;
use std::cell::RefCell;
fn equal(owner:&Rc<RefCell<Vec<i64>>>,left:&i64,right:&i64,mode:usize)->bool {
    if *left!=1 {return left==right;}
    println!("compare");
    match mode {
        0=>{owner.borrow_mut().clear();true},
        1=>{owner.borrow_mut().insert(0,7);true},
        2=>{owner.borrow_mut().push(9);false},
        3=>{owner.borrow_mut().pop();true},
        _=>{owner.borrow_mut().remove(0);false},
    }
}
fn run(mode:usize)->Result<(),String>{
    let owner=Rc::new(RefCell::new(if mode==4 {vec![1_i64,9,9]}else if mode==3{vec![1_i64,2]}else{vec![1_i64]}));
    let needle=9_i64;
    let result=GENERATED;
    let _=result;
    println!("None {:?}",owner.borrow());Ok(())
}
fn main(){run(std::env::args().nth(1).unwrap().parse().unwrap()).unwrap();}
""".replace('GENERATED',generated.code)
        with tempfile.TemporaryDirectory(prefix='pytors-remove-borrow-')as directory:
            root=Path(directory);source=root/'main.rs';source.write_text(rust)
            for optimized in (False,True):
                binary=root/('release'if optimized else'debug')
                build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True)
                self.assertEqual(build.returncode,0,build.stderr)
                for mode,case in enumerate(CALLBACKS):
                    cp=subprocess.run([sys.executable,'-c',case['source']],capture_output=True,text=True)
                    self.assertEqual((cp.stdout,cp.stderr,cp.returncode),(case['stdout'],'',0))
                    actual=subprocess.run([str(binary),str(mode)],capture_output=True,text=True)
                    self.assertEqual((actual.stdout,actual.stderr,actual.returncode),(cp.stdout,'',0))
