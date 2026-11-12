"""Immediate integer consumers keep input lines live without copying text."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests
from pathlib import Path
import os
import subprocess
import tempfile
from py2fastrust import transpile,TranspileOptions
from test_streaming_io import PipeSession

CASES={
 'repeated_lines': '''n, q = map(int, input().split())
values = list(map(int, input().split()))
for _ in range(q):
    left, right = map(int, input().split())
    print(sum(values[left:right]))
''',
 'invalid_extra': 'a,b=map(int,input().split())\nprint(a,b)\n',
 'too_many_before_later_invalid': 'a,b=map(int,input().split())\nprint(a,b)\n',
 'empty_unpack': 'a,b=map(int,input().split())\nprint(a,b)\n',
 'unicode_words': 'a,b=map(int,input().split())\nprint(a,b)\n',
 'stored_snapshot': 'values=map(int,input().split())\nother=input()\nprint(list(values),other)\n',
 'argument_reads_next_line': '''def separator():
    print(input())
    return None
a,b=map(int,input().split(separator()))
print(a,b)
''',
 'callback_reads_next_line': '''def convert(value):
    return int(value)+int(input())
a,b=map(convert,input().split())
print(a,b)
''',
 'shadowed_input': 'def input():return "3 4"\na,b=map(int,input().split())\nprint(a,b)\n',
 'second_empty_line': 'values=list(map(int,input().split()))\nother=list(map(int,input().split()))\nprint(values,other)\n',
 'input_alias': 'input=input\na,b=map(int,input().split())\nprint(a,b)\n',
 'unbound_local_input': 'def read():\n a,b=map(int,input().split())\n input=None\n return a+b\nprint(read())\n',
}
INPUTS={
 'repeated_lines':'4 3\n5 -2 7 9\n0 4\n1 3\n2 2\n',
 'invalid_extra':'1 2 invalid\n',
 'too_many_before_later_invalid':'1 2 3 invalid\n',
 'empty_unpack':'\n',
 'unicode_words':'１２\u2003-３\n',
 'stored_snapshot':'1 2 3\nretained\n',
 'argument_reads_next_line':'3 4\nseparator called\n',
 'callback_reads_next_line':'3 4\n10\n20\n',
 'second_empty_line':'1 2\n\n',
 'input_alias':'3 4\n',
 'unbound_local_input':'3 4\n',
}

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class InputIntegerBorrowTests(unittest.TestCase):
    cases=CASES
    inputs=INPUTS
    check=iterator_tests.IteratorExecutionTests.check
    def test_repeated_lines(self):self.check('repeated_lines')
    def test_invalid_extra(self):self.check('invalid_extra')
    def test_too_many_before_later_invalid(self):self.check('too_many_before_later_invalid')
    def test_empty_unpack(self):self.check('empty_unpack')
    def test_unicode_words(self):self.check('unicode_words')
    def test_stored_snapshot(self):self.check('stored_snapshot')
    def test_argument_reads_next_line(self):self.check('argument_reads_next_line')
    def test_callback_reads_next_line(self):self.check('callback_reads_next_line')
    def test_shadowed_input(self):self.check('shadowed_input')
    def test_second_empty_line(self):self.check('second_empty_line')
    def test_input_alias(self):self.check('input_alias')
    def test_unbound_local_input(self):
        # This unresolved callable is currently diagnosed before generation.
        # Once it gains native support, require the actual Python exception.
        result=transpile(CASES['unbound_local_input'],TranspileOptions(license='none'))
        if result.success:
            self.check('unbound_local_input')
        else:
            self.assertTrue(result.diagnostics)
            self.assertTrue(all(item.code=='E006'for item in result.diagnostics))
    def test_pipe_input_preserves_implicit_flush(self):
        source='for _ in range(2):\n print("next",end="|")\n a,b=map(int,input().split())\n print(a+b)\n'
        result=transpile(source,TranspileOptions(integer='i64',license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'native')
        with tempfile.TemporaryDirectory(prefix='pytors-borrow-input-pipe-')as directory:
            rust=Path(directory)/'main.rs';rust.write_text(result.rust_source)
            binary=Path(directory)/'native'
            built=subprocess.run(['rustc','--edition=2021','-O',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            child=PipeSession([str(binary)],{**os.environ,'PATH':'/no-python-runtime'})
            try:
                child.expect(b'next|')
                child.send(b'1 2\n')
                child.expect(b'3\nnext|')
                child.send(b'3 4\n')
                observed,error=child.finish()
                self.assertEqual(observed,b'next|3\nnext|7\n')
                self.assertEqual(error,b'')
            finally:child.close()
