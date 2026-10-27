"""Patch-level annotation helper names match both observed Python profiles."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import codegen, python_profile
from py2fastrust.compiler import Compiler
import test_runtime


SOURCE = textwrap.dedent('''
    module_value: int
    def top(value: (lambda: 0)): pass
    def outer():
        def nested(value: (lambda: 0)): pass
        def generic[T](value: T): pass
        class Inner:
            field: int
            def method(self, value: int): pass
            def __private(self, value: int): pass
        return nested, generic, Inner
    nested, generic, Inner = outer()
    functions = [top, nested, generic, Inner.method, Inner._Inner__private]
    for function in functions:
        annotate = function.__annotate__
        print(function.__qualname__, annotate.__name__, annotate.__qualname__, annotate.__code__.co_qualname)
    print(__annotate__.__qualname__, Inner.__annotate__.__qualname__)
    print(top.__annotations__['value'].__qualname__, nested.__annotations__['value'].__qualname__)
    original = nested.__annotate__.__qualname__
    nested.__qualname__ = 'changed owner'
    print(nested.__annotate__.__qualname__ == original)
''')


class AnnotationQualnameProfileTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_aot_metadata_profiles_keep_expression_lexical_scopes(self):
        for enabled in (False, True):
            with self.subTest(profile=enabled), patch.object(python_profile, 'ANN_QUALNAME_USES_OWNER', enabled):
                program = Compiler('qualname_profile.py').compile(SOURCE)
                helpers = [code.qualname for code in program.codes
                           if code.filename == 'qualname_profile.py' and code.name == '__annotate__']
                if enabled:
                    expected = ['top.__annotate__', 'outer.<locals>.nested.__annotate__',
                                'outer.<locals>.generic.__annotate__',
                                'outer.<locals>.Inner.method.__annotate__',
                                'outer.<locals>.Inner.__private.__annotate__',
                                'outer.<locals>.Inner.__annotate__', '__annotate__']
                else:
                    expected = ['__annotate__', 'outer.<locals>.__annotate__',
                                'outer.<locals>.__annotate__',
                                'outer.<locals>.Inner.__annotate__',
                                'outer.<locals>.Inner.__annotate__',
                                'outer.<locals>.Inner.__annotate__', '__annotate__']
                self.assertCountEqual(helpers, expected)
                expressions = [code.qualname for code in program.codes
                               if code.filename == 'qualname_profile.py' and code.name == '<lambda>']
                self.assertEqual(expressions, ['<lambda>', 'outer.<locals>.<lambda>'])

    @unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
    def test_aot_and_dynamic_helpers_follow_host_profile(self):
        self.run_source(SOURCE + '\nexec(' + repr(SOURCE) + ', {})\n')

    @unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
    def test_both_runtime_profiles_and_future_annotations(self):
        owners = ['top', 'outer.<locals>.nested', 'outer.<locals>.generic',
                  'outer.<locals>.Inner.method', 'outer.<locals>.Inner.__private']
        legacy = ['__annotate__', 'outer.<locals>.__annotate__',
                  'outer.<locals>.__annotate__', 'outer.<locals>.Inner.__annotate__',
                  'outer.<locals>.Inner.__annotate__']
        for enabled in (False, True):
            for future in (False, True):
                with self.subTest(profile=enabled, future=future):
                    source = SOURCE
                    if future:
                        source = 'from __future__ import annotations\n' + source
                        source = source.replace("print(top.__annotations__['value'].__qualname__, nested.__annotations__['value'].__qualname__)",
                                                "print(top.__annotations__['value'], nested.__annotations__['value'])")
                    expected = []
                    for owner, old in zip(owners, legacy):
                        qualname = owner + '.__annotate__' if enabled else old
                        expected.append(f'{owner} __annotate__ {qualname} {qualname}')
                    # Future scope annotations are dictionaries, without helper
                    # functions, so inspect only ordinary function annotations.
                    if future:
                        source = source.replace("print(__annotate__.__qualname__, Inner.__annotate__.__qualname__)", "print('scope strings')")
                        expected.append('scope strings')
                        expected.append('lambda: 0 lambda: 0')
                    else:
                        expected.append('__annotate__ outer.<locals>.Inner.__annotate__')
                        expected.append('<lambda> outer.<locals>.<lambda>')
                    expected.append('True')
                    expected = '\n'.join(expected) + '\n'
                    source += '\nexec(' + repr(source) + ', {})\n'
                    with patch.object(python_profile, 'ANN_QUALNAME_USES_OWNER', enabled), \
                         patch.object(codegen, 'ANN_QUALNAME_USES_OWNER', enabled):
                        result = transpile(source, TranspileOptions(filename='qualname_profile.py', optimize=False))
                    self.assertTrue(result.success, result.diagnostics)
                    with tempfile.TemporaryDirectory(prefix='annotation-profile-') as directory:
                        path = Path(directory); target = path/'main.rs'; target.write_text(result.rust_source)
                        built = subprocess.run(['rustc', '--edition=2021', str(target), '-o', str(path/'main')],
                                               capture_output=True, text=True, timeout=180)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        actual = subprocess.run([str(path/'main')], capture_output=True, text=True, timeout=20)
                        self.assertEqual(actual.returncode, 0, actual.stderr)
                        self.assertEqual(actual.stdout, expected * 2)


if __name__ == '__main__':
    unittest.main()
