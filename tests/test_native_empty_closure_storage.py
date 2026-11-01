"""Empty captured allocations retain identity while element facts refine."""
import shutil
import subprocess
import sys
import unittest
import test_native_integer_methods as _integer

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class EmptyCapturedStorageTests(unittest.TestCase):
    setUpClass=classmethod(_integer.NativeIntegerMethodTests.setUpClass.__func__)
    tearDownClass=classmethod(_integer.NativeIntegerMethodTests.tearDownClass.__func__)
    compile=_integer.NativeIntegerMethodTests.compile

    def compare(self,binary,source,integer):
        # These finite fixtures never overflow; use CP itself so class syntax
        # is not restricted by the separate wrapping-arithmetic reference.
        expected=subprocess.run([sys.executable,'-S','-c',source],text=True,capture_output=True,timeout=15)
        actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=15)
        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(expected.returncode,expected.stdout,expected.stderr))

    def exercise(self,source):
        for mode in ('i64','i128','bigint'):
            for optimized in (False,True):
                with self.subTest(integer=mode,optimized=optimized):
                    binary,_=self.compile(source,mode,optimized)
                    self.compare(binary,source,mode)

    def test_escaped_empty_list(self):
        self.exercise('def make():\n    values=[]\n    def add(value):\n        values.append(value)\n        return values\n    return add\nadd=make()\nprint(add(2),add(3))\n')

    def test_class_method_empty_list(self):
        self.exercise('class Group:\n    def run(self):\n        seen=[]\n        def visit(value):\n            seen.append(value)\n            return len(seen)\n        for value in [4,2,7]:\n            visit(value)\n        return seen\nprint(Group().run())\n')

    def test_captured_caller_empty_list(self):
        self.exercise('def make(values):\n    def add(value):\n        values.append(value)\n    return add\nvalues=[]\nadd=make(values)\nadd(3)\nadd(7)\nprint(values)\n')

    def test_captured_empty_tuple_rows(self):
        self.exercise('def make():\n    rows=([],[])\n    def add(value):\n        rows[0].append(value)\n        rows[1].append(value+1)\n        return rows\n    return add\nadd=make()\nprint(add(2),add(5))\n')

    def test_empty_captures_infer_text_and_boolean_payloads(self):
        self.exercise('def make():\n values=[]\n def add(value):\n  values.append(value)\n  return values\n return add\nadd=make()\nprint(add("first"),add("next"))\n')
        self.exercise('def make(values):\n def add(value):\n  values.append(value)\n return add\nvalues=[]\nadd=make(values)\nadd(True)\nadd(False)\nprint(values)\n')

if __name__=='__main__':unittest.main()
