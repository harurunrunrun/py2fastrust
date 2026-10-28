"""Module-owned typed bindings retain current values, aliases and default capture."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile,TranspileOptions
import test_native_lambda_callbacks as helpers


CASES={
    'constant':('class Box:\n def read(self):return GLOBAL+2\nGLOBAL=3\nprint(Box().read())\n', ('',)),
    'late':('class Box:\n def read(self):return GLOBAL\nGLOBAL=3\nbox=Box()\nprint(box.read())\nGLOBAL=8\nprint(box.read())\n', ('',)),
    'unbound':('class Box:\n def read(self):return GLOBAL\nprint("before")\nprint(Box().read())\nGLOBAL=3\n', ('',)),
    'counter':('class Box:\n def tick(self,n):\n  global COUNT\n  COUNT+=1\n  if n:return self.tick(n-1)\n  return COUNT\nCOUNT=0\nprint(Box().tick(int(input())),COUNT)\n', ('0\n', '8\n')),
    'alias':('class Box:\n def update(self):\n  global VALUES\n  VALUES.append(2)\n  VALUES=[7]\n  VALUES.append(9)\nVALUES=[1]\nsaved=VALUES\nBox().update()\nprint(VALUES,saved,VALUES is saved)\n', ('',)),
    'change_type':('class Box:\n def read(self):return GLOBAL\nGLOBAL=3\nbox=Box()\nprint(box.read())\nGLOBAL="text"\nprint(box.read())\nGLOBAL=None\nprint(box.read())\n', ('',)),
    'list_to_int':('class Box:\n def read(self):return GLOBAL\nGLOBAL=[1]\nsaved=GLOBAL\nbox=Box()\nprint(box.read())\nGLOBAL=5\nprint(box.read(),saved)\n', ('',)),
    'local_shadow':('GLOBAL=10\nclass Box:\n def read(self,GLOBAL):\n  GLOBAL+=3\n  return GLOBAL\n def local(self):\n  print(GLOBAL)\n  GLOBAL=2\nprint(Box().read(4),GLOBAL)\nBox().local()\n', ('',)),
    'comps':('GLOBAL=4\nclass Box:\n def values(self):return [GLOBAL+local for local in range(3)]\n def shadow(self):return [GLOBAL for GLOBAL in range(3)]\nprint(Box().values(),Box().shadow(),GLOBAL)\n', ('',)),
    'global_default':('GLOBAL=3\nclass Box:\n def read(self,value=GLOBAL):return value\nGLOBAL="later"\nprint(Box().read(),GLOBAL)\n', ('',)),
    'ordinary_default':('GLOBAL=3\ndef read(value=GLOBAL):return value\nclass Scope:pass\nGLOBAL=8\nprint(read(),read(9),GLOBAL)\n', ('',)),
    'mutable_default':('VALUES=[1]\nclass Box:\n def take(self,value=VALUES):\n  value.append(2)\n  return value\nbox=Box()\nprint(box.take())\nVALUES=[7]\nprint(box.take(),VALUES)\n', ('',)),
    'effects_defaults':('def mark(value):\n print("default",value)\n return [value]\nclass Box:\n def take(self,value=mark(3)):\n  value.append(4)\n  return value\nprint("defined")\nprint(Box().take(),Box().take())\n', ('',)),
    'unused_default':('class Box:\n def unused(self,value=int(input())):return value\nprint("done")\n', ('4\n', 'bad\n')),
    'unbound_default':('class Box:\n def unused(self,value=MISSING):return value\nprint("never")\n', ('',)),
    'delete_none':('GLOBAL=None\nclass Box:\n def read(self):return GLOBAL\n def erase(self):\n  global GLOBAL\n  del GLOBAL\nbox=Box()\nprint(box.read())\nbox.erase()\nprint(box.read())\n', ('',)),
    'delete_restore':('GLOBAL=[1]\nclass Box:\n def update(self):\n  global GLOBAL\n  del GLOBAL\n  GLOBAL=[3]\n def read(self):return GLOBAL\nalias=GLOBAL\nBox().update()\nprint(Box().read(),alias)\n', ('',)),
    'walrus_comprehensions':('COUNT=0\nclass Box:\n def collect(self,n):\n  global COUNT\n  return [(COUNT:=COUNT+1)for unused in range(n)]\nbox=Box()\nprint(box.collect(3),COUNT)\nprint(box.collect(2),COUNT)\nvalues=[(COUNT:=COUNT+2)for unused in range(2)]\nprint(values,COUNT)\n', ('',)),
    'readonly_namespace':('class Box:\n def read(self,value=__name__):return (__name__,value)\nprint(Box().read())\n', ('',)),
    'read_order':('VALUE=[1]\nclass Box:\n def change(self):\n  global VALUE\n  VALUE.append(2)\n  VALUE=[9]\n  return 5\nbox=Box()\nprint(VALUE,box.change(),VALUE)\n', ('',)),
    'ordinary_recursive_global':('class ClassScope:pass\nCOUNT=0\ndef visit(n):\n global COUNT\n COUNT+=1\n if n:return visit(n-1)+1\n return COUNT\nprint(visit(int(input())),COUNT)\n', ('0\n', '12\n')),
    'branch_type_rebinding':('VALUE=3\nclass Box:\n def read(self):return VALUE\n def change(self,selected):\n  global VALUE\n  if selected:VALUE="changed"\n  else:VALUE=None\nbox=Box()\nprint(box.read())\nbox.change(int(input()))\nprint(box.read(),VALUE)\n', ('0\n', '1\n')),
    'cross_global_aliases':('FIRST=[1]\nSECOND=FIRST\nclass Box:\n def change(self):\n  global FIRST,SECOND\n  FIRST=SECOND\n  SECOND=[7]\n  FIRST.append(3)\n def read(self):return (FIRST,SECOND)\nbox=Box()\nbox.change()\nprint(box.read(),FIRST,SECOND,FIRST is SECOND)\n', ('',)),
    'tuple_mutable_alternatives':('VALUE=([1],3)\nclass Box:\n def read(self):return VALUE\nbox=Box()\nsaved=VALUE\nprint(box.read())\nVALUE=(5,[2])\nprint(box.read(),saved)\n', ('',)),
    'empty_global_and_default':('VALUES=[]\nclass Box:\n def append(self,value,items=VALUES):\n  items.append(value)\n  VALUES.append(value+1)\n  return items\nbox=Box()\nprint(box.append(2),VALUES)\nprint(box.append(5),VALUES)\n', ('',)),
    'class_body_recursive_default':('import sys\ndef descend(n):\n if n:return descend(n-1)\n return 3\nsys.setrecursionlimit(int(input()))\nclass Box:\n def read(self,value=descend(4)):return value\nprint(Box().read())\n', ('30\n', '5\n')),
    'class_body_limit_builtin':('import sys\nLIMIT=int(input())\nclass Box:\n def read(self,value=sys.setrecursionlimit(LIMIT)):return value\nprint(Box().read())\n', ('10\n', '2\n')),
    'ordinary_function_default_error':('class Scope:pass\ndef unused(value=int(input())):return value\nprint("done")\n', ('3\n', 'bad\n')),
}
CASES.update({
    'local_union_must_not_widen_global':('VALUE=3\nclass Box:\n def local(self,selected):\n  item=VALUE\n  if selected:item="local"\n  return item\n def read(self):return VALUE+1\nbox=Box()\nprint(box.local(int(input())),box.read(),VALUE)\n', ('0\n', '1\n')),
    'local_mutable_union_keeps_global':('VALUE=[1]\nclass Box:\n def local(self,selected):\n  item=VALUE\n  if selected:item=3\n  return item\n def read(self):return VALUE\nbox=Box()\nprint(box.local(int(input())),box.read(),VALUE)\n', ('0\n', '1\n')),
    'local_list_type_change':('VALUE=[1]\nclass Box:\n def run(self):\n  item=VALUE\n  print(item)\n  item=["local"]\n  print(item)\n  return VALUE[0]+1\nprint(Box().run(),VALUE)\n', ('',)),
    'local_tuple_type_change':('VALUE=(3,)\nclass Box:\n def run(self):\n  item=VALUE\n  print(item)\n  item=("local",)\n  print(item)\nprint(Box().run(),VALUE)\n', ('',)),
    'local_bool_int_point_types':('VALUE=True\nclass Box:\n def run(self):\n  item=VALUE\n  print(item)\n  item=3\n  print(item)\nprint(Box().run(),VALUE)\n', ('',)),
    'local_none_int_point_types':('VALUE=None\nclass Box:\n def run(self):\n  item=VALUE\n  print(item)\n  item=3\n  print(item)\nprint(Box().run(),VALUE)\n', ('',)),
    'value_boolop_effects':('VALUE="start"\nclass Box:\n def run(self,flag):\n  item=VALUE\n  ignored=flag and(item:=3)\n  print(item,ignored)\n  ignored=flag or(item:=[2])\n  print(item,ignored)\nBox().run(int(input()))\n', ('0\n', '1\n')),
    'value_ifexp_effects':('VALUE="start"\nclass Box:\n def run(self,flag):\n  item=VALUE\n  ignored=(item:=3)if flag else(item:=[2])\n  print(item,ignored)\nBox().run(int(input()))\n', ('0\n', '1\n')),
    'compare_effects':('VALUE="start"\nclass Box:\n def run(self,flag):\n  item=VALUE\n  ignored=0==flag==(item:=3)\n  print(item,ignored)\nBox().run(int(input()))\n', ('0\n', '1\n')),
    'parameter_rebinding_from_global':('VALUE="start"\nclass Box:\n def run(self,item,flag):\n  print(item)\n  if flag:item=3\n  return item\nprint(Box().run(VALUE,int(input())),VALUE)\n', ('0\n', '1\n')),
    'for_loop_capture_backedge':('VALUE="start"\nclass Box:\n def run(self,count):\n  item=VALUE\n  for index in range(count):\n   print(item)\n   item=index\n  return item\nprint(Box().run(int(input())),VALUE)\n', ('0\n', '1\n', '3\n')),
    'continue_capture_backedge':('VALUE="start"\nclass Box:\n def run(self,count):\n  item=VALUE\n  for index in range(count):\n   print(item)\n   item=index\n   if index%2==0:continue\n   item=str(index)\n  return item\nprint(Box().run(int(input())),VALUE)\n', ('0\n', '4\n')),
    'while_capture_backedge':('VALUE="start"\nclass Box:\n def run(self,count):\n  item=VALUE\n  index=0\n  while index<count:\n   print(item)\n   item=index\n   index+=1\n  return item\nprint(Box().run(int(input())),VALUE)\n', ('0\n', '3\n')),
    'comprehension_outer_capture_effect':('VALUE="start"\nclass Box:\n def run(self,count):\n  item=VALUE\n  values=[(item:=index)for index in range(count)]\n  print(item,values)\nBox().run(int(input()))\n', ('0\n', '3\n')),
    'comprehension_unbound_capture':('VALUE=[1]\nclass Box:\n def run(self,count):\n  values=[(item:=VALUE)for unused in range(count)]\n  return item\nprint(Box().run(int(input())))\n', ('0\n', '1\n')),
})
CASES.update({'default_argument_then_global_write': ('COUNT=0\nVALUE=3\nclass Box:\n def tick(self,value=VALUE):\n  global COUNT\n  COUNT+=value\n  return COUNT\nbox=Box()\nprint(box.tick(),box.tick(),COUNT)\n', ('',)), 'default_argument_then_global_rebind': ('VALUE=[1]\nclass Box:\n def replace(self,items=VALUE):\n  global VALUE\n  VALUE=[7]\n  items.append(3)\n  return items\nbox=Box()\nprint(box.replace(),VALUE)\nprint(box.replace(),VALUE)\n', ('',))})


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeClassGlobalTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)

    @staticmethod
    def frames(stderr):
        result=[]
        for line in stderr.splitlines():
            match=re.search(r'File ".*?", line (\d+), in ([^\n]+)',line)
            if match:result.append((int(match[1]),match[2]))
            repeated=re.search(r'\[Previous line repeated (\d+) more times\]',line)
            if repeated and result:result.extend([result[-1]]*int(repeated[1]))
        return result

    def exercise(self,source,inputs=("",),*,prune=True):
        expected=[subprocess.run([sys.executable,"-I","-S","-c",source],input=data,
                  text=True,capture_output=True,timeout=15)for data in inputs]
        for mode in ("i64","i128","bigint"):
            converted=transpile(source,TranspileOptions(integer=mode,optimize=prune,filename="namespace.py"))
            self.assertTrue(converted.success,converted.diagnostics)
            self.assertEqual(converted.backend,"native")
            for optimized in (False,True):
                key=(source,mode,optimized,prune)
                if key not in self.cache:
                    stem=hashlib.sha256(repr(key).encode()).hexdigest()
                    path=Path(self.directory.name)/(stem+".rs")
                    path.write_text(converted.rust_source)
                    binary=path.with_suffix("")
                    compiled=subprocess.run(["rustc","--edition=2021","--crate-name","namespace",
                        *(["-O"]if optimized else[]),str(path),"-o",str(binary)],
                        capture_output=True,text=True,timeout=180)
                    self.assertEqual(compiled.returncode,0,compiled.stderr)
                    self.cache[key]=binary
                for data,reference in zip(inputs,expected):
                    with self.subTest(integer=mode,optimized=optimized,input=data,pruned=prune):
                        actual=subprocess.run([str(self.cache[key])],input=data,text=True,capture_output=True,
                            timeout=15,env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.stdout,reference.stdout)
                        self.assertEqual(actual.returncode,reference.returncode,actual.stderr)
                        self.assertEqual(self.frames(actual.stderr),self.frames(reference.stderr))
                        last=lambda text:text.rstrip().splitlines()[-1]if text.strip()else""
                        self.assertEqual(last(actual.stderr),last(reference.stderr))

    def test_constant(self):
        self.exercise(*CASES['constant'])

    def test_late(self):
        self.exercise(*CASES['late'])

    def test_unbound(self):
        self.exercise(*CASES['unbound'])

    def test_counter(self):
        self.exercise(*CASES['counter'])

    def test_alias(self):
        self.exercise(*CASES['alias'])

    def test_change_type(self):
        self.exercise(*CASES['change_type'])

    def test_list_to_int(self):
        self.exercise(*CASES['list_to_int'])

    def test_local_shadow(self):
        self.exercise(*CASES['local_shadow'])

    def test_comps(self):
        self.exercise(*CASES['comps'])

    def test_global_default(self):
        self.exercise(*CASES['global_default'])

    def test_ordinary_default(self):
        self.exercise(*CASES['ordinary_default'])

    def test_mutable_default(self):
        self.exercise(*CASES['mutable_default'])

    def test_effects_defaults(self):
        self.exercise(*CASES['effects_defaults'])

    def test_unused_default(self):
        self.exercise(*CASES['unused_default'])

    def test_unbound_default(self):
        self.exercise(*CASES['unbound_default'])

    def test_delete_none(self):
        self.exercise(*CASES['delete_none'])

    def test_delete_restore(self):
        self.exercise(*CASES['delete_restore'])

    def test_walrus_comprehensions(self):
        self.exercise(*CASES['walrus_comprehensions'])

    def test_readonly_namespace(self):
        self.exercise(*CASES['readonly_namespace'])

    def test_read_order(self):
        self.exercise(*CASES['read_order'])

    def test_ordinary_recursive_global(self):
        self.exercise(*CASES['ordinary_recursive_global'])

    def test_branch_type_rebinding(self):
        self.exercise(*CASES['branch_type_rebinding'])

    def test_cross_global_aliases(self):
        self.exercise(*CASES['cross_global_aliases'])

    def test_tuple_mutable_alternatives(self):
        self.exercise(*CASES['tuple_mutable_alternatives'])

    def test_empty_global_and_default(self):
        self.exercise(*CASES['empty_global_and_default'])

    def test_class_body_recursive_default(self):
        self.exercise(*CASES['class_body_recursive_default'])

    def test_class_body_limit_builtin(self):
        self.exercise(*CASES['class_body_limit_builtin'])

    def test_ordinary_function_default_error(self):
        self.exercise(*CASES['ordinary_function_default_error'])

    def test_local_union_must_not_widen_global(self):
        self.exercise(*CASES['local_union_must_not_widen_global'])

    def test_local_mutable_union_keeps_global(self):
        self.exercise(*CASES['local_mutable_union_keeps_global'])

    def test_local_list_type_change(self):
        self.exercise(*CASES['local_list_type_change'])

    def test_local_tuple_type_change(self):
        self.exercise(*CASES['local_tuple_type_change'])

    def test_local_bool_int_point_types(self):
        self.exercise(*CASES['local_bool_int_point_types'])

    def test_local_none_int_point_types(self):
        self.exercise(*CASES['local_none_int_point_types'])

    def test_value_boolop_effects(self):
        self.exercise(*CASES['value_boolop_effects'])

    def test_value_ifexp_effects(self):
        self.exercise(*CASES['value_ifexp_effects'])

    def test_compare_effects(self):
        self.exercise(*CASES['compare_effects'])

    def test_parameter_rebinding_from_global(self):
        self.exercise(*CASES['parameter_rebinding_from_global'])

    def test_for_loop_capture_backedge(self):
        self.exercise(*CASES['for_loop_capture_backedge'])

    def test_continue_capture_backedge(self):
        self.exercise(*CASES['continue_capture_backedge'])

    def test_while_capture_backedge(self):
        self.exercise(*CASES['while_capture_backedge'])

    def test_comprehension_outer_capture_effect(self):
        self.exercise(*CASES['comprehension_outer_capture_effect'])

    def test_comprehension_unbound_capture(self):
        self.exercise(*CASES['comprehension_unbound_capture'])

    def test_default_argument_then_global_write(self):
        self.exercise(*CASES['default_argument_then_global_write'])

    def test_default_argument_then_global_rebind(self):
        self.exercise(*CASES['default_argument_then_global_rebind'])

    def test_runtime_pruning_is_independent_of_frame_semantics(self):
        self.exercise(*CASES["counter"],prune=False)

    def test_unused_namespace_keeps_class_scope_without_extra_handle(self):
        source="class Box:\n def __init__(self,value=3):self.value=value\n def read(self):return self.value\nprint(Box().read())\n"
        for mode in ("i64","i128","bigint"):
            for prune in (False,True):
                result=transpile(source,TranspileOptions(integer=mode,optimize=prune))
                self.assertTrue(result.success,result.diagnostics)
                self.assertNotIn("ClassGlobals",result.rust_source)

    def test_rebound_builtin_call_has_a_concrete_boundary(self):
        source="len=3\nclass Box:\n def read(self):return len([1])\nprint(Box().read())\n"
        result=transpile(source)
        self.assertFalse(result.success)
        self.assertIn("module-owned writes",result.diagnostics[0].message)
        self.assertIn("callable identity",result.diagnostics[0].message)

    def test_finite_arithmetic_alternatives_name_the_missing_proof(self):
        source="VALUE=3\nclass Box:\n def read(self):return VALUE+1\nVALUE='text'\nprint(Box().read())\n"
        result=transpile(source)
        self.assertFalse(result.success)
        self.assertIn("per-alternative",result.diagnostics[0].message)
        self.assertIn("int",result.diagnostics[0].message)
        self.assertIn("str",result.diagnostics[0].message)

    def test_implicit_namespace_values_never_become_phantom_name_errors(self):
        result=transpile("class Box:\n def read(self):return __file__\nprint(Box().read())\n")
        self.assertFalse(result.success)
        self.assertIn("implicit module",result.diagnostics[0].message)

    def test_default_class_namespace_write_remains_explicit(self):
        result=transpile("class Box:\n def read(self,value=(MEMBER:=3)):return value\nprint(Box().read())\n")
        self.assertFalse(result.success)
        self.assertIn("class namespace",result.diagnostics[0].message)


if __name__=="__main__":unittest.main()
