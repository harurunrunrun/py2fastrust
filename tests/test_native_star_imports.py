"""Original star-import sites preserve namespace lookup and binding versions."""
import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from py2fastrust import transpile,TranspileOptions

CATCH='''class Suppress:
 def __enter__(self):return self
 def __exit__(self,t,v,b):return True
'''
PROJECTS={
'heapq':({},'''from heapq import *
h=[4,2,7]
heapify(h)
heappush(h,1)
print(heappop(h),heappop(h),len(h))
print('merge' in globals(),'heappush_max' in globals())
''',('',)),
'bisect':({},'''from bisect import *
a=[1,3,3,8]
insort(a,4)
print(bisect(a,3),bisect_left(a,3),a)
''',('',)),
'plain':({'library.py':'''value=3
_private=8
def add(x):return x+value
'''},'''from library import *
print(value,add(5),'_private' in globals(),'*' in globals())
''',('',)),
'explicit_private':({'library.py':'''__all__=['_value','add','_value']
_value=4
extra=9
def add(x):return x+_value
'''},'''from library import *
print(_value,add(5),'extra' in globals())
''',('',)),
'conditional_export':({'library.py':'''flag=int(input())
if flag:value=7
other=2
'''},'''value='old'
from library import *
print(value,other)
''',('0\n','1\n')),
'conditional_import':({'library.py':'value=7\n'},'''flag=int(input())
value='old'
if flag:
 from library import *
print(value)
''',('0\n','1\n')),
'conditional_builtin':({'library.py':'def len(value):return 90\n'},'''flag=int(input())
if flag:
 from library import *
print(len([1,2,3]))
''',('0\n','1\n')),
'builtin_restoration':({'library.py':'def len(value):return 90\n'},'''print(len([1,2]))
from library import *
print(len([1,2]))
del len
print(len([1,2]))
''',('',)),
'deleted_export':({'library.py':'value=7\ndel value\nother=2\n'},'''value='before'
from library import *
print(value,other)
''',('',)),
'snapshot_and_sharing':({'library.py':'''value=3
items=[1]
def update():
 global value
 value=9
 items.append(4)
'''},'''import library
from library import *
library.update()
print(value,library.value,items,library.items)
''',('',)),
'transitive':({'library.py':'from dependency import *\nvalue=4\n','dependency.py':'other=5\ndef add(x):return x+1\n'},'''from library import *
print(value,other,add(6))
''',('',)),
'cyclic_partial':({'library.py':'value=4\nfrom dependency import *\n','dependency.py':'from library import *\nother=value+2\n'},'''from library import *
print(value,other)
''',('',)),
'string_exports':({'library.py':"__all__='xy'\nx=3\ny=4\nz=8\n"},'''from library import *
print(x,y,'z' in globals())
''',('',)),
'missing_explicit':({'library.py':"print('initialize')\n__all__=['value','missing','after']\nvalue=3\nafter=9\n"},CATCH+'''with Suppress():
 from library import *
print(value,'missing' in globals(),'after' in globals())
''',('',)),
'bad_item_prefix':({'library.py':"__all__=['value',3,'after']\nvalue=3\nafter=9\n"},CATCH+'''with Suppress():
 from library import *
print(value,'after' in globals())
''',('',)),
'bad_item_unbound':({'library.py':"__all__=['value',3,'after']\nvalue=3\nafter=9\n"},CATCH+'''with Suppress():
 from library import *
print(value)
print(after)
''',('',)),
'none_exports':({'library.py':'__all__=None\nvalue=8\n'},'''print('before')
from library import *
print('after')
''',('',)),
'bytes_exports':({'library.py':"__all__=b'xy'\nx=3\ny=4\n"},'''from library import *
''',('',)),
'conditional_function_read':({'library.py':'value=9\n'},'''def read():return value
flag=int(input())
if flag:
 from library import *
print(read())
''',('0\n','1\n')),
}


PROJECTS.update({
'package_children':({'package/__init__.py':"__all__=['left','right']\n",'package/left.py':"print('left')\nvalue=3\n",'package/right.py':"print('right')\nvalue=7\n"},"from package import *\nprint(left.value,right.value)\n",('',)),
'package_preload_before_binding':({'shared.py':'observe=None\n','package/__init__.py':"__all__=['first','child']\nfirst=3\n",'package/child.py':"import shared\nprint(shared.observe())\nvalue=7\n"},"import shared\ndef observe():return 'first' in globals()\nshared.observe=observe\nfrom package import *\nprint('first' in globals(),child.value)\n",('',)),
'package_existing_attribute':({'package/__init__.py':"__all__=['child']\nchild=3\n",'package/child.py':"print('unexpected load')\nvalue=7\n"},"from package import *\nprint(isinstance(child,int))\n",('',)),
'package_bad_item_no_bindings':({'package/__init__.py':"__all__=['first',3]\nfirst=4\n"},CATCH+"with Suppress():\n from package import *\nprint('first' in globals())\n",('',)),
'package_child_error_before_binding':({'package/__init__.py':"__all__=['first','child']\nfirst=3\n",'package/child.py':"print('child')\nraise ValueError('stop')\n"},CATCH+"with Suppress():\n from package import *\nprint('first' in globals(),'child' in globals())\n",('',)),
'package_none_exports':({'package/__init__.py':"__all__=None\n"},"from package import *\n",('',)),
})

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class StarImportExecution(unittest.TestCase):
 def test_original_star_imports(self):
  for name,(modules,source,inputs)in PROJECTS.items():
   with self.subTest(name=name),tempfile.TemporaryDirectory(prefix='pytors-star-import-')as tmp:
    folder=Path(tmp)
    for module,body in modules.items():
     path=folder/module;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
    entry=folder/'main.py';entry.write_text(source)
    expected=[subprocess.run([sys.executable,'-B',str(entry)],input=data.encode(),capture_output=True,timeout=10)for data in inputs]
    for mode in ('i64','i128','bigint'):
     result=transpile(source,TranspileOptions(integer=mode,filename=str(entry),module_paths=(folder,),license='none'))
     self.assertTrue(result.success,(name,mode,result.diagnostics));self.assertEqual(result.backend,'native')
     self.assertLess(len(result.rust_source.encode()),512*1024)
     rust=folder/(mode+'.rs');rust.write_text(result.rust_source)
     for optimized in (False,True):
      binary=folder/(mode+str(optimized));build=subprocess.run(['rustc','--edition=2021','--crate-name','star_import_test',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,timeout=120)
      self.assertEqual(build.returncode,0,(name,build.stderr.decode()[-6000:]))
      for data,cp in zip(inputs,expected):
       got=subprocess.run([str(binary)],input=data.encode(),capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
       self.assertEqual((got.returncode,got.stdout),(cp.returncode,cp.stdout),(name,mode,got.stderr,cp.stderr))
       if cp.returncode:
        self.assertEqual(got.stderr.splitlines()[-1].split(b':',1)[0],cp.stderr.splitlines()[-1].split(b':',1)[0],(name,got.stderr,cp.stderr))
       else:self.assertEqual(got.stderr,b'')

class StarImportGuards(unittest.TestCase):
 def test_unproved_export_schemas_are_named(self):
  projects=[({'library.py':"names=['x']\n__all__=names\nx=3\n"},'from library import *\n','__all__'),
            ({'library.py':'x=3\n'},'import library\nlibrary.__all__=["x"]\nfrom library import *\n','__all__'),
            ({'library.py':'x=3\n'},'import library\nlibrary.extra=4\nfrom library import *\n','export'),
            ({'library.py':"__all__={0:'x'}\nx=3\n"},'from library import *\n','__all__')]
  for modules,source,word in projects:
   with self.subTest(source=source),tempfile.TemporaryDirectory()as tmp:
    folder=Path(tmp)
    for name,body in modules.items():(folder/name).write_text(body)
    result=transpile(source,TranspileOptions(filename=str(folder/'main.py'),module_paths=(folder,),license='none'))
    self.assertFalse(result.success)
    self.assertTrue(any(word in d.message for d in result.diagnostics),result.diagnostics)


class OriginalStarMetadata(unittest.TestCase):
 def test_original_nodes_and_official_scope_owners_are_retained(self):
  import ast
  from py2fastrust.frontend import build_program
  from py2fastrust.native_module_linking import LinkedProgram
  with tempfile.TemporaryDirectory()as tmp:
   folder=Path(tmp);(folder/'library.py').write_text('value=3\ndef len(x):return 90\n')
   program=build_program('from library import *\nprint(value,len([]))\n',str(folder/'main.py'),(folder,))
   before=tuple((unit.name,ast.dump(unit.tree,include_attributes=True),tuple(id(n)for n in ast.walk(unit.tree)))for unit in program.units)
   linked=LinkedProgram.from_program(program).unit
   after=tuple((unit.name,ast.dump(unit.tree,include_attributes=True),tuple(id(n)for n in ast.walk(unit.tree)))for unit in program.units)
   self.assertEqual(before,after)
   self.assertFalse(any(binding.name=='*'for unit in program.units for binding in unit.bindings))
   node=program.main.tree.body[0]
   imports=linked.import_bindings(node)
   self.assertEqual({item.exported_name for item in imports},{'value','len'})
   self.assertTrue(all(item.node is node.names[0]for item in imports))
   load=next(n for n in ast.walk(program.main.tree)if isinstance(n,ast.Name)and n.id=='len')
   self.assertEqual(linked.binding_for(load).owner,linked.module_roots['__main__'])
   self.assertEqual(linked.name_for(load).module_name,'__main__')
