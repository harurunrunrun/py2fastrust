"""Lexical qualnames remain independent of mutable function metadata."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile

DRIVER = 'import sys\nexec(sys.stdin.read())\n'


class FrontendQualifiedNameTests(unittest.TestCase):
    def test_scope_metadata_matches_official_code_objects(self):
        import types
        from collections import Counter
        from py2fastrust.compiler import Compiler
        source = textwrap.dedent('''
            def outer():
                class C[T]:
                    def __method[U](self, value: (lambda:0)):
                        return lambda:0
                def generic[T: (lambda:0) = (lambda:0)]():pass
                def annotated(x: (lambda:0)):pass
                type Alias[T] = (lambda:0)
                return [lambda:0 for i in range(1)], ((lambda:0) for i in range(1))
            def publishing():
                global published, Published
                def published():pass
                class Published:pass
        ''')
        expected = Counter()
        def visit(code):
            if code.co_name != '<module>':
                expected[code.co_name, code.co_qualname] += 1
            for child in code.co_consts:
                if isinstance(child, types.CodeType):
                    visit(child)
        visit(compile(source, '<qualified-source>', 'exec'))
        program = Compiler(filename='<qualified-source>').compile(source)
        actual = Counter((code.name, code.qualname) for code in program.codes
                         if code.filename == '<qualified-source>'
                         and code.kind != 'Module'
                         and not (code.kind == 'Comprehension' and not code.is_generator))
        self.assertEqual(actual, expected)
