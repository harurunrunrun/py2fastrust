"""Direct source-class cycles preserve live roots without a universal value runtime."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import tempfile
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_class_gc import RUNTIME,runtime
from tests import test_native_module_linking as support

CASES = {'self_cycle': {'main.py': 'class Node:\n'
                           ' def __init__(self,n):self.n=n;self.link=None\n'
                           'a=Node(3)\n'
                           'a.link=a\n'
                           'print(a.n,a.link.n,a.link is a)\n'},
 'two_node_cycle': {'main.py': 'class Node:\n'
                               ' def __init__(self,n):self.n=n;self.link=None\n'
                               'a=Node(3)\n'
                               'b=Node(7)\n'
                               'a.link=b\n'
                               'b.link=a\n'
                               'print(a.link.n,b.link.n,a.link.link is a)\n'},
 'three_node_cycle': {'main.py': 'class Node:\n'
                                 ' def __init__(self,n):self.n=n;self.link=None\n'
                                 'a=Node(3)\n'
                                 'b=Node(7)\n'
                                 'c=Node(9)\n'
                                 'a.link=b\n'
                                 'b.link=c\n'
                                 'c.link=a\n'
                                 'print(a.link.link.n,c.link is a)\n'},
 'alias_survives_name_deletion': {'main.py': 'class Node:\n'
                                             ' def __init__(self,n):self.n=n;self.link=None\n'
                                             'a=Node(3)\n'
                                             'b=Node(7)\n'
                                             'a.link=b\n'
                                             'b.link=a\n'
                                             'keep=a.link\n'
                                             'del a\n'
                                             'del b\n'
                                             'print(keep.n,keep.link.n,keep.link.link is keep)\n'},
 'outer_owner_roots_cycle': {'main.py': 'class Node:\n'
                                        ' def __init__(self,n):self.n=n;self.link=None\n'
                                        'class Owner:\n'
                                        ' def __init__(self,a):self.items=[a]\n'
                                        'a=Node(3)\n'
                                        'b=Node(7)\n'
                                        'a.link=b\n'
                                        'b.link=a\n'
                                        'owner=Owner(a)\n'
                                        'del a\n'
                                        'del b\n'
                                        'print(owner.items[0].link.n,owner.items[0].link.link is '
                                        'owner.items[0])\n'},
 'cycle_link_replaced_by_scalar': {'main.py': 'class Node:\n'
                                              ' def __init__(self,n):self.n=n;self.link=None\n'
                                              'a=Node(3)\n'
                                              'b=Node(7)\n'
                                              'a.link=b\n'
                                              'b.link=a\n'
                                              'keep=b\n'
                                              'a.link=42\n'
                                              'print(a.link,keep.link.n)\n'},
 'cycle_link_cleared': {'main.py': 'class Node:\n'
                                   ' def __init__(self,n):self.n=n;self.link=None\n'
                                   'a=Node(3)\n'
                                   'b=Node(7)\n'
                                   'a.link=b\n'
                                   'b.link=a\n'
                                   'a.link=None\n'
                                   'print(a.link,b.link.n)\n'},
 'many_unreachable_cycles': {'main.py': 'class Node:\n'
                                        ' def __init__(self,n):self.n=n;self.link=None\n'
                                        'def build(n):\n'
                                        ' for i in range(n):\n'
                                        '  a=Node(i)\n'
                                        '  b=Node(i+1)\n'
                                        '  a.link=b\n'
                                        '  b.link=a\n'
                                        ' return Node(n)\n'
                                        'r=build(3000)\n'
                                        'print(r.n,r.link is None)\n'},
 'rooted_cycles_among_garbage': {'main.py': 'class Node:\n'
                                            ' def __init__(self,n):self.n=n;self.link=None\n'
                                            'def build(n):\n'
                                            ' keep=[]\n'
                                            ' for i in range(n):\n'
                                            '  a=Node(i)\n'
                                            '  b=Node(i+1)\n'
                                            '  a.link=b\n'
                                            '  b.link=a\n'
                                            '  if i%300==0:keep.append(a)\n'
                                            ' return keep\n'
                                            'keep=build(3000)\n'
                                            'print([a.n for a in keep],[a.link.n for a in '
                                            'keep])\n'},
 'mutual_class_cycle': {'main.py': 'class Left:\n'
                                   ' def __init__(self):self.right=None\n'
                                   'class Right:\n'
                                   ' def __init__(self):self.left=None\n'
                                   'a=Left()\n'
                                   'b=Right()\n'
                                   'a.right=b\n'
                                   'b.left=a\n'
                                   'print(a.right is b,b.left is a)\n'},
 'cycle_reachable_through_acyclic_field': {'main.py': 'class Node:\n'
                                                      ' def '
                                                      '__init__(self,n):self.n=n;self.link=None\n'
                                                      'class Owner:\n'
                                                      ' def __init__(self,root):self.root=root\n'
                                                      'a=Node(3)\n'
                                                      'b=Node(7)\n'
                                                      'a.link=b\n'
                                                      'b.link=a\n'
                                                      'owner=Owner(a)\n'
                                                      'del a\n'
                                                      'del b\n'
                                                      'print(owner.root.link.n)\n'},
 'duplicate_direct_edges': {'main.py': 'class Node:\n'
                                       ' def '
                                       '__init__(self,n):self.n=n;self.left=None;self.right=None\n'
                                       'a=Node(4)\n'
                                       'a.left=a\n'
                                       'a.right=a\n'
                                       'print(a.left.n,a.right is a)\n'},
 'finite_class_scalar_fields': {'main.py': 'class Node:\n'
                                           ' def __init__(self,n):self.n=n;self.link=None\n'
                                           'a=Node(2)\n'
                                           'b=Node(8)\n'
                                           'a.link=b\n'
                                           'b.link=a\n'
                                           'print(a.link.n)\n'
                                           'a.link=False\n'
                                           'print(a.link,b.link.n)\n'
                                           'a.link="cleared"\n'
                                           'print(a.link)\n'},
 'closure_roots': {'main.py': 'class Node:\n'
                              ' def __init__(self,n):self.n=n;self.link=None\n'
                              'def make():\n'
                              ' a=Node(3)\n'
                              ' b=Node(7)\n'
                              ' a.link=b\n'
                              ' b.link=a\n'
                              ' def read():return a.link.n\n'
                              ' return read\n'
                              'read=make()\n'
                              'print(read(),read())\n'},
 'context_manager': {'main.py': 'class Node:\n'
                                ' def __init__(self,n):self.n=n;self.link=None\n'
                                ' def __enter__(self):return self\n'
                                ' def __exit__(self,t,v,tb):return False\n'
                                'a=Node(5)\n'
                                'a.link=a\n'
                                'with a as owner:\n'
                                ' print(owner.link.n,owner is a)\n'},
 'linked_node': {'nodes.py': 'class Node:\n'
                             ' def __init__(self,n):self.n=n;self.link=None\n'
                             'def make(n):\n'
                             ' a=Node(n)\n'
                             ' a.link=a\n'
                             ' return a\n',
                 'main.py': 'import nodes\n'
                            'a=nodes.make(9)\n'
                            'alias=a\n'
                            'del a\n'
                            'print(alias.n,alias.link is alias)\n'},
 'construction_exception': {'main.py': 'class Node:\n'
                                       ' def __init__(self,n):\n'
                                       '  self.n=n\n'
                                       '  self.link=self\n'
                                       '  print("before")\n'
                                       '  print(1//0)\n'
                                       'Node(3)\n'},
 'collection_during_field_loop': {'main.py': 'class Node:\n'
                                             ' def __init__(self,n):self.n=n;self.link=None\n'
                                             ' def run(self):\n'
                                             '  for i in range(300):\n'
                                             '   a=Node(i)\n'
                                             '   a.link=a\n'
                                             '   if i%100==0:print(self.n,self.link.n)\n'
                                             'a=Node(3)\n'
                                             'a.link=a\n'
                                             'a.run()\n'},
 'recursive_free_function': {'main.py': 'class Node:\n'
                                        ' def __init__(self,n):self.n=n;self.link=None\n'
                                        'def visit(node,count):\n'
                                        ' if count==0:return node.link.n\n'
                                        ' return visit(node,count-1)\n'
                                        'a=Node(5)\n'
                                        'a.link=a\n'
                                        'print(visit(a,120))\n'},
 'recursive_calls': {'main.py': 'class Node:\n'
                    ' def __init__(self,n):self.n=n;self.link=None\n'
                    ' def walk(self,steps):\n'
                    '  if steps==0:return self.n\n'
                    '  return self.link.walk(steps-1)\n'
                    'a=Node(3)\n'
                    'b=Node(7)\n'
                    'a.link=b\n'
                    'b.link=a\n'
                    'print(a.walk(15),b.walk(12))\n'}}

BOUNDARIES = {'container_mediated_cycle': 'class Node:\n'
                             ' def __init__(self):self.children=[]\n'
                             'a=Node()\n'
                             'a.children.append(a)\n'
                             'print(a.children[0] is a)\n',
 'cycle_with_callable_field': 'class Node:\n'
                              ' def __init__(self,n):self.n=n;self.link=None\n'
                              'a=Node(3)\n'
                              'a.link=a\n'
                              'a.fn=lambda:a.n\n'
                              'print(a.fn())\n',
 'source_finalizer': 'class Node:\n'
                     ' def __init__(self):self.link=self\n'
                     ' def __del__(self):print("destroyed")\n'
                     'a=Node()\n'
                     'del a\n',
 'mixed_closure_cycle': 'class Node:\n'
                        ' def __init__(self):self.link=self\n'
                        'def make():\n'
                        ' a=Node()\n'
                        ' a.callback=lambda:a\n'
                        ' return a\n'
                        'a=make()\n'
                        'print(a.callback() is a)\n'}

class DirectClassGcProtocolTests(unittest.TestCase):
    def test_uncollected_protocols_remain_positioned(self):
        for name,source in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn('Source:',str(result.diagnostics[0]))

    def test_no_cycle_does_not_emit_collector(self):
        result=transpile('class Box:\n def __init__(self,n):self.n=n\nprint(Box(3).n)\n')
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('NativeClassGc',result.rust_source)

    def test_control_injection_is_token_aware(self):
        source='struct ClassControl { depth:usize,limit:usize }\nimpl ClassControl { fn limit(&self)->usize{self.limit} }\nfn new()->ClassControl { ClassControl {depth:0,limit:1} }\nconst TEXT:&str="ClassControl {depth:0,limit:1}";\n'
        result=runtime(source,SimpleNamespace(gc_classes={'Node'}))
        self.assertIn('impl ClassControl { fn limit(&self)->usize{self.limit} }',result)
        self.assertIn('const TEXT:&str="ClassControl {depth:0,limit:1}";',result)
        self.assertEqual(result.count('gc:NativeClassGc::new()'),1)
        self.assertEqual(result.count('gc:NativeClassGc}'),1)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DirectClassGcExecutionTests(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise


def execution(files):
    def test(self):self.exercise(files)
    return test

for name,files in CASES.items():
    setattr(DirectClassGcExecutionTests,'test_'+name,execution(files))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DirectClassGcKernelTests(unittest.TestCase):
    def test_native_collector_reclaims_only_unrooted_cycles(self):
        harness=Path(__file__).with_name('native_class_gc_kernel.rs').read_text()
        with tempfile.TemporaryDirectory(prefix='pytors-class-gc-kernel-')as directory:
            root=Path(directory);source=root/'kernel.rs'
            source.write_text('use std::rc::Rc;\n'+RUNTIME+'\n'+harness.replace('use std::rc::{Rc,Weak};',''))
            for optimized in (False,True):
                with self.subTest(optimized=optimized):
                    binary=root/('release'if optimized else'debug')
                    build=subprocess.run(['rustc','--edition=2021','--test',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(build.returncode,0,build.stderr)
                    run=subprocess.run([str(binary),'--test-threads=1'],capture_output=True,text=True,timeout=30)
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                    self.assertIn('7 passed; 0 failed',run.stdout)
