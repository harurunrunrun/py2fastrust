"""Shared builtin list nodes participate in the actual class GC graph."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from py2fastrust.frontend import build_program
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_classes import Model
from py2fastrust.native_class_gc import RUNTIME,layout,_list_layouts
import test_native_module_linking as support

CASES={
 'self_edge_through_list':'''class Node:
 def __init__(self,n):self.n=n;self.children=[]
node=Node(3)
node.children.append(node)
print(node.children[0] is node,node.children[0].n)
''',
 'external_shared_list_keeps_nodes':'''import gc
class Node:
 def __init__(self,n):self.n=n;self.children=[]
a=Node(3)
b=Node(7)
shared=[a,b,a]
a.children=shared
b.children=shared
del a
del b
gc.collect()
print([node.n for node in shared],shared[0].children is shared,shared[1].children is shared)
''',
 'nested_shared_lists_keep_physical_aliases':'''import gc
class Node:
 def __init__(self,n):self.n=n;self.groups=[]
node=Node(3)
row=[node,node]
node.groups=[row,row]
keep=node.groups
del row
del node
gc.collect()
print(keep[0] is keep[1],keep[0][0].n,keep[0][0].groups is keep)
keep[1].append(keep[0][0])
print(len(keep[0]))
''',
 'fixed_tuple_list_empty_payload_beside_cycle':'''class Node:
 def __init__(self):self.payload=([],);self.link=None
a=Node()
a.link=a
print(a.link is a)
''',
 'scalar_lists_preserve_external_aliases':'''import gc
class Node:
 def __init__(self):self.values=[2,3];self.link=None
node=Node()
node.link=node
keep=node.values
del node
gc.collect()
keep.append(5)
print(keep)
''',
 'list_roots_in_captured_tuple':'''import gc
class Node:
 def __init__(self,n):self.n=n;self.children=[]
def make():
 node=Node(11)
 node.children.append(node)
 keep=(node.children,)
 def read():return keep[0][0].n
 return read
read=make()
for i in range(160):
 node=Node(i)
 node.children.append(node)
gc.collect()
print(read(),read())
''',
 'shared_default_list_and_mutation':'''import gc
class Node:
 def __init__(self,n,children=[]):self.n=n;self.children=children
a=Node(3)
b=Node(7)
a.children.append(a)
b.children.append(b)
print(a.children is b.children)
keep=a.children
del a
del b
gc.collect()
print([node.n for node in keep])
''',
 'finite_list_or_none_field':'''import gc
class Node:
 def __init__(self,n):self.n=n;self.children=None
node=Node(3)
node.children=[node]
keep=node.children
node.children=None
gc.collect()
print(keep[0] is node,keep[0].n,node.children)
''',
 'physical_duplicate_list_fields':'''import gc
class Node:
 def __init__(self,n):self.n=n;self.links=([],[])
a=Node(3)
b=Node(7)
shared=[a,b,a]
a.links=(shared,shared)
b.links=(shared,shared)
del a
del b
gc.collect()
print([node.n for node in shared],shared[0].links[0] is shared[1].links[1])
''',
}

# The initial explicit gc.collect probes are retained below as import
# boundaries. These independent programs exercise automatic collection.
AUTOMATIC_CASES={
 'mutual_classes_through_different_list_layouts':'''class Left:
 def __init__(self):self.rights=[]
class Right:
 def __init__(self):self.lefts=[]
a=Left()
b=Right()
a.rights=[b]
b.lefts=[a]
keep=(a.rights,b.lefts)
del a
del b
for i in range(160):
 x=Left()
 y=Right()
 x.rights=[y]
 y.lefts=[x]
print(keep[0][0].lefts is keep[1],keep[1][0].rights is keep[0])
''',
 'list_of_fixed_tuples_counts_duplicate_class_edges':'''class Node:
 def __init__(self,n):self.n=n;self.children=[]
node=Node(3)
node.children=[(node,node)]
keep=node.children
del node
for i in range(160):
 garbage=Node(i)
 garbage.children=[(garbage,garbage)]
print(keep[0][0] is keep[0][1],keep[0][0].n,keep[0][0].children is keep)
''',
 'named_tuple_and_list_class_edges':'''from typing import NamedTuple
class Pair(NamedTuple):
 left:int
 right:int
class Node:
 def __init__(self,n):self.n=n;self.children=[]
node=Node(3)
node.children=[Pair(node,node)]
keep=node.children
del node
for i in range(160):
 garbage=Node(i)
 garbage.children=[Pair(garbage,garbage)]
print(keep[0].left is keep[0].right,keep[0].left.n,keep[0].left.children is keep)
''',
 'finite_class_scalar_list_elements':'''class Node:
 def __init__(self,n):self.n=n;self.children=[]
node=Node(3)
node.children=[node,'tail']
keep=node.children
del node
for i in range(160):
 garbage=Node(i)
 garbage.children=[garbage,'tail']
print(keep[0].n,keep[1],keep[0].children is keep)
''',
 'external_shared_list_during_allocation_pressure':'''class Node:
 def __init__(self,n):self.n=n;self.children=[]
a=Node(3)
b=Node(7)
shared=[a,b,a]
a.children=shared
b.children=shared
del a
del b
def churn():
 for i in range(160):
  garbage=Node(i)
  garbage.children.append(garbage)
churn()
print([node.n for node in shared],shared[0].children is shared,shared[1].children is shared)
''',
 'nested_lists_during_allocation_pressure':'''class Node:
 def __init__(self,n):self.n=n;self.groups=[]
node=Node(3)
row=[node,node]
node.groups=[row,row]
keep=node.groups
del row
del node
def churn():
 for i in range(160):
  garbage=Node(i)
  garbage.groups=[[garbage]]
churn()
print(keep[0] is keep[1],keep[0][0].n,keep[0][0].groups is keep)
keep[1].append(keep[0][0])
print(len(keep[0]))
''',
 'scalar_list_root_during_allocation_pressure':'''class Node:
 def __init__(self):self.values=[2,3];self.link=None
node=Node()
node.link=node
keep=node.values
del node
def churn():
 for i in range(160):
  garbage=Node()
  garbage.link=garbage
churn()
keep.append(5)
print(keep)
''',
 'captured_tuple_list_root_during_allocation_pressure':'''class Node:
 def __init__(self,n):self.n=n;self.children=[]
def make():
 node=Node(11)
 node.children.append(node)
 keep=(node.children,)
 def read():return keep[0][0].n
 return read
read=make()
def churn():
 for i in range(160):
  garbage=Node(i)
  garbage.children.append(garbage)
churn()
print(read(),read())
''',
 'shared_default_list_during_allocation_pressure':'''class Node:
 def __init__(self,n,children=[]):self.n=n;self.children=children
a=Node(3)
b=Node(7)
a.children.append(a)
b.children.append(b)
print(a.children is b.children)
keep=a.children
del a
del b
def churn():
 for i in range(160):
  garbage=Node(i,[])
  garbage.children.append(garbage)
churn()
print([node.n for node in keep])
''',
 'nullable_list_field_during_allocation_pressure':'''class Node:
 def __init__(self,n):self.n=n;self.children=None
node=Node(3)
node.children=[node]
keep=node.children
node.children=None
def churn():
 for i in range(160):
  garbage=Node(i)
  garbage.children=[garbage]
churn()
print(keep[0] is node,keep[0].n,node.children)
''',
 'duplicate_fields_during_allocation_pressure':'''class Node:
 def __init__(self,n):self.n=n;self.links=([],[])
a=Node(3)
b=Node(7)
shared=[a,b,a]
a.links=(shared,shared)
b.links=(shared,shared)
del a
del b
def churn():
 for i in range(160):
  garbage=Node(i)
  garbage.links=([garbage],[garbage])
churn()
print([node.n for node in shared],shared[0].links[0] is shared[1].links[1])
''',
}

class ClassListGcExecutionTests(unittest.TestCase):
 exercise=support.NativeLinkedModuleTests.exercise

for _name,_source in {**{name:source for name,source in CASES.items()if not source.startswith('import gc')},**AUTOMATIC_CASES}.items():
 def _test(self,source=_source):self.exercise({'main.py':source})
 setattr(ClassListGcExecutionTests,'test_'+_name,_test)

class ClassListGcImportBoundaryTests(unittest.TestCase):
 def test_explicit_gc_module_still_has_a_positioned_import_boundary(self):
  for name,source in CASES.items():
   if not source.startswith('import gc'):continue
   for integer in ('i64','i128','bigint'):
    result=transpile(source,TranspileOptions(integer=integer,license='none',filename='explicit_gc_import.py'))
    self.assertFalse(result.success,(name,integer))
    self.assertTrue(any(item.code=='E006'and item.line==1 and "import 'gc'"in item.message for item in result.diagnostics),result.diagnostics)

 def test_direct_cycles_do_not_emit_unused_list_discovery(self):
  source='class Node:\n def __init__(self,n):self.n=n;self.link=None\na=Node(3)\na.link=a\nprint(a.link.n)\n'
  for integer in ('i64','i128','bigint'):
   result=transpile(source,TranspileOptions(integer=integer,license='none'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertIn('NativeClassGc',result.rust_source)
   self.assertNotIn('fn discover(',result.rust_source)
   self.assertNotIn('.discover(',result.rust_source)

 def test_scalar_elements_emit_no_empty_walk_or_unused_discover_override(self):
  source='class Node:\n def __init__(self):self.n=3;self.values=[3,5];self.link=None\na=Node()\na.link=a\nprint(a.values)\n'
  unit=build_program(source,'gc_scalar_leaf.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  adapter=_list_layouts(model)
  self.assertNotIn('fn discover',adapter)
  self.assertNotIn('for value',adapter)
  self.assertIn('fn trace(&self,_visit:&mut dyn FnMut(usize))->bool{true}',adapter)
  owner=model.classes['Node']
  index=next(index for index,field in enumerate(owner.fields.values())if field.name=='n')
  self.assertNotIn('&data.field_'+str(index),layout(model,owner))

 def test_class_elements_emit_trace_without_empty_discovery_walk(self):
  source='class Node:\n def __init__(self):self.children=[]\na=Node()\na.children.append(a)\n'
  unit=build_program(source,'gc_class_leaf.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  adapter=_list_layouts(model)
  self.assertNotIn('fn discover',adapter)
  self.assertEqual(adapter.count('for value'),1)
  self.assertIn('visit(Rc::as_ptr',adapter)

class ClassListGcKernelTests(unittest.TestCase):
 def test_actual_generated_adapters_count_shared_allocations_once(self):
  source='class Node:\n def __init__(self):self.links=([],[])\na=Node()\na.links[0].append(a)\na.links[1].append(a)\n'
  unit=build_program(source,'gc_list_kernel.py').main
  model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
  owner=model.classes['Node']
  fixture=Path(__file__).with_name('native_class_gc_list_kernel.rs').read_text()
  rust=RUNTIME+'\n'+fixture+'\n'+layout(model,owner)+'\n'+_list_layouts(model)
  with tempfile.TemporaryDirectory(prefix='pytors-class-list-gc-')as directory:
   path=Path(directory)/'kernel.rs';path.write_text(rust)
   for optimized in (False,True):
    binary=Path(directory)/('release'if optimized else'debug')
    built=subprocess.run(['rustc','--edition=2021','--test',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
    self.assertEqual(built.returncode,0,built.stderr)
    ran=subprocess.run([str(binary),'--test-threads=1'],capture_output=True,text=True,timeout=30)
    self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
    self.assertIn('6 passed; 0 failed',ran.stdout)

if __name__=='__main__':unittest.main()
