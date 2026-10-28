"""Concrete class layouts, shared typed storage, and compiled call futures."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeClassTests(unittest.TestCase):
    def compile(self, source, mode="i64", optimize=True):
        with patch("py2fastrust.codegen.generate", side_effect=AssertionError("general codegen entered")):
            result = transpile(source, TranspileOptions(integer=mode, filename="classes.py", optimize=optimize))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, "native")
        for marker in ("enum Value", "enum Op", "struct Runtime", "fn step(", "struct PegParser"):
            self.assertNotIn(marker, result.rust_source)
        self.assertLess(len(result.rust_source.encode()), 512 * 1024)
        directory = tempfile.TemporaryDirectory(prefix="pytors-typed-class-")
        self.addCleanup(directory.cleanup)
        path = Path(directory.name, "program.rs")
        path.write_text(result.rust_source)
        binary = path.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", "-O", str(path), "-o", str(binary)],
                               capture_output=True, text=True, timeout=90)
        self.assertEqual(built.returncode, 0, built.stderr)
        return binary, result.rust_source

    def compare(self, source, modes=("i64", "i128", "bigint"), data=""):
        expected = subprocess.run([sys.executable, "-c", source], input=data, text=True,
                                  capture_output=True, timeout=10)
        for mode in modes:
            with self.subTest(mode=mode):
                binary, _ = self.compile(source, mode)
                actual = subprocess.run([str(binary)], input=data, text=True, capture_output=True, timeout=10)
                self.assertEqual(actual.stdout, expected.stdout)
                self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
                if actual.returncode:
                    self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                     expected.stderr.splitlines()[-1].split(":")[0])
        return expected

    def test_instances_fields_and_returned_lists_preserve_shared_aliases(self):
        self.compare('''class Box:
 def __init__(self, values):
  self.values=values
  self.number=1
 def expose(self):
  return self.values
 def write(self, value):
  self.values[0]=value
  self.number=value
xs=[2]
a=Box(xs)
b=a
ys=a.expose()
b.write(7)
print(xs,ys,a.values,a.number,b.number,a is b, xs is ys)
a.values=[9]
print(xs,ys,b.values,xs is b.values)
''')

    def test_targets_capture_receivers_and_indices_in_python_order(self):
        self.compare('''class Box:
 def __init__(self):
  self.values=[10]
 def replace(self):
  self.values=[99]
  return 7
 def index(self):
  self.values=[77]
  return 0
x=Box()
old=x.values
x.values[0]+=x.replace()
print(old,x.values)
x=Box()
old=x.values
x.values[0]=x.replace()
print(old,x.values)
x=Box()
print(x.values[x.index()],x.values[0])
''')

    def test_keyword_evaluation_defaults_and_scalar_field_union(self):
        self.compare('''def mark(value):
 print(value)
 return value
class Box:
 def __init__(self, first, second=3):
  self.value=first+second
  self.flags=[False,True]
 def read(self, value=5, *, enabled=True):
  if enabled:
   self.flags[0]=value
  return self.value,self.flags
box=Box(second=mark(2),first=mark(1))
print(box.read(enabled=mark(False),value=mark(9)))
print(box.read())
x=10
x="changed"
print(x)
''')

    def test_recursive_pair_void_and_mutually_recursive_calls(self):
        self.compare('''class Tree:
 def __init__(self):
  self.count=0
 def collect(self,n):
  if n==0:
   return self.count,0
  a,b=self.collect(n-1)
  self.bump(n)
  return a+n,b+1
 def bump(self,n):
  if n==0:
   return
  self.count+=1
  self.bump(n-1)
 def even(self,n):
  if n==0:
   return self.count
  self.count+=1
  return self.odd(n-1)
 def odd(self,n):
  self.count+=10
  if n==0:
   return self.count
  return self.even(n-1)
tree=Tree()
a,b=tree.collect(4)
print(a,b,tree.count,tree.even(5))
''')

    def test_zero_trip_field_and_constructor_early_read_raise_with_frames(self):
        for early in (False, True):
            source = ('''class Box:
 def __init__(self,n):
  ''' + ("self.read()" if early else "for i in range(n):self.value=i") + '''
 def read(self):
  return self.value
box=Box(0)
print(box.read())
''')
            self.compare(source)
            binary, _ = self.compile(source)
            actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertIn('File "classes.py", line 5, in read', actual.stderr)
            self.assertIn("AttributeError: 'Box' object has no attribute 'value'", actual.stderr)
            if early:
                self.assertIn('line 3, in __init__', actual.stderr)

    def test_shared_list_iteration_observes_mutation_and_reductions(self):
        self.compare('''class Bag:
 def __init__(self):
  self.values=[1,2]
 def total(self):
  original=self.values
  for value in original:
   if value==1:
    original.append(3)
   self.values=[8]
   print(value)
  original+=original
  print(original,sum(original),min(original),max(original))
  print(min(3,2,2),max(3,2,2))
bag=Bag()
bag.total()
print(bag.values)
''')

    def test_depth_and_error_unwind_do_not_use_rust_call_stack(self):
        try:
            import resource
        except ImportError:
            self.skipTest("resource limits unavailable")
        def small_stack():
            resource.setrlimit(resource.RLIMIT_STACK, (256 * 1024, 256 * 1024))
        base='''import sys
sys.setrecursionlimit(50000)
class Chain:
 def descend(self,n):
  if n==0:
   return BOTTOM
  return self.descend(n-1)+1
print(Chain().descend(20000))
'''
        for mode in ("i64", "i128", "bigint"):
            for bottom in ("0", "1//0"):
                with self.subTest(mode=mode,bottom=bottom):
                    binary, _ = self.compile(base.replace("BOTTOM", bottom), mode)
                    actual = subprocess.run([str(binary)], capture_output=True, text=True,
                                            timeout=15, preexec_fn=small_stack)
                    if bottom == "0":
                        self.assertEqual((actual.returncode,actual.stdout), (0,"20000\n"), actual.stderr)
                    else:
                        self.assertEqual(actual.returncode, 1, actual.stderr[-500:])
                        self.assertIn("ZeroDivisionError:", actual.stderr)
                        self.assertEqual(actual.stderr.count("in descend"), 20001)

    def test_recursion_limit_checked_before_callee_body(self):
        source='''import sys
sys.setrecursionlimit(70)
class Chain:
 def descend(self,n):
  if n==0:return 1
  return self.descend(n-1)
print("ready")
print(Chain().descend(10000))
'''
        self.compare(source)

    def test_stdin_aliases_newlines_bytes_and_lazy_unpack_errors(self):
        base='''import sys
class Reader:
 def numbers(self):
  read=sys.stdin.buffer.readline
  first,second=map(int,read().split())
  print(first,second)
  print(read())
  print(read())
Reader().numbers()
'''
        for data in ("1 2\nhello\n\n", "1 2 3 invalid\n", "1\n", "\x1c1 2\n"):
            self.compare(base, data=data)

    def test_string_repetition_structural_overflow_is_checked(self):
        self.compare("class Text:\n def repeat(self,n):return 'abc'*n\nprint(Text().repeat(2**62))\n")

    def test_missing_local_and_shallow_exception_frames(self):
        self.compare('''class Box:
 def read(self,n):
  if n:
   result=3
  return result
print(Box().read(0))
''')
        source='''class Box:
 def descend(self,n):
  print(n)
  if n:return self.descend(n-1)
  return 1//0
print(Box().descend(3))
'''
        binary,_=self.compile(source)
        actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
        self.assertEqual(actual.stdout,"3\n2\n1\n0\n")
        frames=re.findall(r'line (\d+), in (\S+)',actual.stderr)
        self.assertEqual(frames,[("6","<module>"),("4","descend"),("4","descend"),("4","descend"),("5","descend")])


class NativeClassProofTests(unittest.TestCase):
    def test_unproved_dynamic_object_features_are_positioned_errors(self):
        sources=(
            "class Child(object):pass\n",
            "class Item(metaclass=type):pass\n",
            "class Item:\n @property\n def value(self):return 1\n",
            "class Item:\n def __getattr__(self,name):return 1\n",
            "class Item:\n def __new__(cls):return 1\nprint(Item())\n",
            "class Item:\n def __init__(self):return 3\nprint(Item())\n",
            "class Item:\n def read(self):return 1\nitem=Item()\nmethod=item.read\nprint(method())\n",
            "class Item:\n def read(self):return 1\n def __init__(self):self.read=2\nprint(Item().read)\n",
            "class Item:\n def __init__(self):self.child=self\nprint(Item())\n",
            "class Item:\n def __init__(self):self.values=[self]\nprint(Item())\n",
        )
        with patch("py2fastrust.codegen.generate",side_effect=AssertionError("general codegen entered")):
            for mode in ("i64","i128","bigint"):
                for source in sources:
                    with self.subTest(mode=mode,source=source):
                        result=transpile(source,TranspileOptions(integer=mode,filename="proof.py"))
                        self.assertFalse(result.success)
                        self.assertIsNone(result.rust_source)
                        self.assertEqual(result.diagnostics[0].code,"E006")
                        self.assertEqual(result.diagnostics[0].filename,"proof.py")
                        self.assertGreaterEqual(result.diagnostics[0].line,1)

    def test_unresolved_local_callable_and_import_shadowing_are_rejected(self):
        for source in (
            "import sys\nclass Item:\n def read(self):\n  print(sys.getrecursionlimit())\n  sys=1\nItem().read()\n",
            "class Item:pass\na,b=map(int,'12')\nprint(a,b)\n",
        ):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")

    def test_definition_visibility_is_proved_transitively(self):
        for source in (
            "print(Box())\nclass Box:pass\n",
            "def run():return Box()\nprint(run())\nclass Box:pass\n",
        ):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")
        result=transpile("class Box:\n def value(self):return later()\ndef later():return 7\nprint(Box().value())\n")
        self.assertTrue(result.success,result.diagnostics)


if __name__ == "__main__":
    unittest.main()
