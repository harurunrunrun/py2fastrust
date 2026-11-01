"""Compile-time builtin captures keep ordinary typed consumers available."""
import re
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_frame_selection import select_frames
import test_native_iterator_reductions as execution


SOURCES=(
'''convert=int
saved=convert
convert=7
print(saved("12"),saved(b"-3"))
print(sum(saved(c)for c in "123"))
print(sum(map(saved,"1 2".split())))
print(sum(map(saved,b"3 4".split())))
''',
'''def total(text):
 convert=int
 saved=convert
 convert=9
 return sum(saved(c)for c in text)
print(total("123"))
''',
'''convert=abs
saved=convert
convert=3
print(sum(map(saved,[-3,2,-5])))
print([saved(value)for value in [-2,1]])
''',
'''convert=int
saved=convert
convert=7
print("before")
print(sum(saved(c)for c in "1x2"))
''',
)


class StaticBuiltinCapabilityTests(unittest.TestCase):
    def test_proved_capture_lifetimes_keep_the_ordinary_route(self):
        for source in SOURCES:
            with self.subTest(source=source):
                self.assertFalse(select_frames(parse_source(source)).required)

    def test_dynamic_or_escaping_bindings_keep_runtime_callable_cells(self):
        sources=(
            'convert=int if int(input())else str\nprint(convert("12"))\n',
            'convert=int\nvalues=[convert]\nconvert=7\nprint(values[0]("12"))\n',
            'convert=int\nsaved=convert\ndel convert\nprint(saved("12"))\n',
            'convert=int\ndef change():\n global convert\n convert=str\nchange()\nprint(convert("12"))\n',
            'def outer():\n convert=int\n def change():\n  nonlocal convert\n  convert=str\n change()\n return convert("12")\nprint(outer())\n',
            'convert=int\ng=(convert(c)for c in "12")\nconvert=7\nprint(list(g))\n',
            'convert=int\nsaved=convert\nint=str\nprint(saved("12"),int(3))\n',
            'convert=int\nprint(sum((convert(c)for c in "12"),(convert:=3)))\n',
            'convert=int\nprint(sum((convert(c)for c in "12"),len([convert:=str])))\n',
            'saved=int\nprint(next((saved(c)for c in "12"),(saved:=str)))\n',
            'convert=str\nsaved=convert\nconvert=7\nprint(saved(None))\n',
            'convert=abs\nsaved=convert\nconvert=7\nprint(saved(1.5))\n',
            'convert=int\nsaved=convert\nconvert=7\nprint(saved(None))\n',
            'convert=range\nsaved=convert\nconvert=7\nvalue=saved(3)\nprint(list(value))\n',
            'convert=enumerate\nsaved=convert\nconvert=7\nvalue=saved([1,2])\nprint(list(value))\n',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(select_frames(parse_source(source)).required)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class StaticBuiltinExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=execution.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def test_other_scalar_shapes_keep_the_existing_frame_semantics(self):
        for identity,argument in (("str","None"),("abs","1.5"),("int","None")):
            source=f'convert={identity}\nsaved=convert\nconvert=7\nprint("before")\nprint(saved({argument}))\n'
            expected=subprocess.run([sys.executable,"-I","-c",source],capture_output=True,text=True,timeout=10)
            for mode in ("i64","i128","bigint"):
                for optimize in (False,True):
                    with self.subTest(identity=identity,mode=mode,optimize=optimize):
                        compiled=self.harness.compile(source,mode,release=optimize,prune=optimize)
                        actual=subprocess.run([str(compiled[1])],capture_output=True,text=True,timeout=10)
                        self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                        self.assertIn("ClassFunctionRef",compiled[2])
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1],expected.stderr.splitlines()[-1])

    def test_all_widths_profiles_and_text_modes(self):
        for source in SOURCES:
            # Establish the CPython result before any converter invocation.
            expected=subprocess.run([sys.executable,"-I","-c",source],capture_output=True,text=True,timeout=10)
            for mode in ("i64","i128","bigint"):
                for string_mode in ("ascii","unicode"):
                    for optimize in (False,True):
                        with self.subTest(source=source,mode=mode,string_mode=string_mode,optimize=optimize):
                            compiled=self.harness.compile(source,mode,release=optimize,prune=optimize,string_mode=string_mode)
                            actual=subprocess.run([str(compiled[1])],capture_output=True,text=True,timeout=10)
                            self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                            self.assertNotIn("ClassFunctionRef",compiled[2])
                            self.assertNotIn("ClassScope",compiled[2])
                            if expected.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1].split(":",1)[0],expected.stderr.splitlines()[-1].split(":",1)[0])
                                pattern=r'File "[^"]+", line (\d+), in ([^\n]+)'
                                self.assertEqual(re.findall(pattern,actual.stderr),re.findall(pattern,expected.stderr))


if __name__=="__main__":unittest.main()
