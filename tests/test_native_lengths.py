"""Builtin length lowers its argument exactly once before observing its size."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_lengths import try_expression
from py2fastrust.references import UnknownReference


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeLengthTests(unittest.TestCase):
    def compare(self,source,inputs=("",),*,modes=("i64","i128","bigint"),string_mode="ascii"):
        expected=[subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=10)for data in inputs]
        with tempfile.TemporaryDirectory(prefix="pytors-native-length-")as directory:
            for mode in modes:
                result=transpile(source,TranspileOptions(integer=mode,string_mode=string_mode,filename="length.py"))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,"native")
                path=Path(directory)/(mode+".rs");path.write_text(result.rust_source)
                for release in (False,True):
                    binary=path.with_name(mode+("_release"if release else"_debug"))
                    built=subprocess.run(["rustc","--edition=2021",*(["-O"]if release else[]),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(integer=mode,release=release,data=data):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,
                                                  env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                            self.assertEqual(actual.stdout,reference.stdout)
                            self.assertEqual(actual.returncode,reference.returncode,actual.stderr+reference.stderr)
                            if actual.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],reference.stderr.splitlines()[-1].split(":")[0])
                            else:self.assertEqual(actual.stderr,"")

    def test_sorted_lambda_defaults_mutate_the_source_once(self):
        self.compare('''values=[5,2,9,1]
count=len(sorted(values,key=lambda x,discard=values.pop():x))
print(count)
print(values)
other=[4,2,3]
print(len(sorted(other,key=lambda x,discard=other.pop():x)))
print(other)
''')

    def test_effectful_dictionary_and_view_owners_are_evaluated_once(self):
        self.compare('''def make():
 print("made")
 return {1:2,3:4}
print(len(make()))
print(len(make().keys()))
print(len(make().values()))
print(len(make().items()))
''')

    def test_fixed_and_dynamic_tuple_length_preserve_input_and_callback_effects(self):
        self.compare('''print(len((int(input()),int(input()))))
print(input())
print(len(tuple(map(lambda value:value+1,[1,2,3]))))
''',inputs=("1\n2\ntail\n","bad\n2\ntail\n"))

    def test_typed_builtin_collections_and_builtin_aliases(self):
        matrix_source='''measure=len
print(measure([[1],[2]]))
print(len(b"abc"))
print(len({1,2,3}))
print(len({1:2,3:4}))
print(len((1,"text",None)))
'''
        self.compare(matrix_source)
        self.compare('''measure=len
print(measure([1,2,3]))
print(len(b"abc"))
print(len({1,2,3}))
print(len({1:2,3:4}))
print(len((1,"text",None)))
''')
        self.compare('''from collections import deque
values=deque([1,2,3])
print(len(values))
print(values.pop())
print(len(values))
''',modes=("i64","i128"))

    def test_unicode_and_ascii_text_lengths_preserve_projection_errors(self):
        source='''text=input()
print(len(text))
print(len(str(text)))
print(len(text[int(input())]))
'''
        self.compare(source,inputs=("猫🐈é\n1\n","猫🐈é\n8\n","\n0\n"),string_mode="unicode")
        self.compare(source,inputs=("abcd\n2\n","abcd\n8\n"))

    def test_invalid_scalar_lengths_and_finite_alternatives_emit_python_errors(self):
        self.compare('''value="abc" if int(input()) else None
print(len(value))
''',inputs=("1\n","0\n"))
        self.compare('''print(len(int(input())))
''',inputs=("3\n","bad\n"))


class NativeLengthBindingTests(unittest.TestCase):
    def test_shadowed_or_unrelated_calls_are_not_argument_probes(self):
        generator=SimpleNamespace(expression=Mock(side_effect=AssertionError("argument lowered")))
        with patch("py2fastrust.native_lengths.callable_reference",return_value=UnknownReference("len","shadowed")):
            self.assertIsNone(try_expression(generator,ast.parse("len(effect())").body[0].value,{}))
        self.assertIsNone(try_expression(generator,ast.Constant(value=1),{}))
        generator.expression.assert_not_called()
        result=transpile("len=3\nprint(len([1,2]))\n")
        self.assertFalse(result.success)
        self.assertIsNone(result.rust_source)

    def test_invalid_bindings_and_unproved_view_protocols_are_explicit(self):
        for source in ("print(len())\n","print(len([1],[2]))\n","print(len(obj=[1]))\n","print(len([1].keys()))\n"):
            with self.subTest(source=source):
                result=transpile(source,TranspileOptions(filename="bad-length.py"))
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code,"E006")
                self.assertIn("len",result.diagnostics[0].message)


if __name__=="__main__":unittest.main()
