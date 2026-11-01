"""Reserved dynamic module prebundling never silently becomes static import."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


class IncludedModuleBoundaryTests(unittest.TestCase):
    def check(self,source,options):
        with patch('py2fastrust.api.try_generate_native',side_effect=AssertionError('ordinary code generation entered')), \
             patch('py2fastrust.native_module_linking.generate_linked',side_effect=AssertionError('static linking ignored the dynamic bundle request')), \
             patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy code generation entered')):
            result=transpile(source,options)
        self.assertFalse(result.success)
        self.assertIsNone(result.rust_source)
        self.assertEqual(len(result.diagnostics),1)
        diagnostic=result.diagnostics[0]
        self.assertEqual((diagnostic.filename,diagnostic.line,diagnostic.column,diagnostic.code),(options.filename,1,1,'E006'))
        self.assertIn('--include-module',diagnostic.message)
        self.assertIn('compile/eval/exec',diagnostic.message)
        self.assertIn('without this option',diagnostic.message)
        return diagnostic

    def test_builtin_only_bundles_keep_the_explicit_boundary(self):
        for mode in ('i64','i128','bigint'):
            for optimize in (False,True):
                with self.subTest(integer=mode,optimize=optimize):
                    self.check('print(1)\n',TranspileOptions(filename='bundle.py',integer=mode,optimize=optimize,include_modules=('math',)))

    def test_user_module_defaults_and_import_side_effects_are_never_executed(self):
        with tempfile.TemporaryDirectory(prefix='pytors-include-boundary-')as directory:
            root=Path(directory)
            (root/'helper.py').write_text('raise RuntimeError("must not execute during conversion")\ndef value(items=[]):return items\n')
            for mode in ('i64','i128','bigint'):
                for optimize in (False,True):
                    with self.subTest(integer=mode,optimize=optimize):
                        self.check('print(1)\n',TranspileOptions(filename=str(root/'main.py'),integer=mode,optimize=optimize,include_modules=('helper',)))

    def test_static_source_import_does_not_hide_the_dynamic_bundle_request(self):
        with tempfile.TemporaryDirectory(prefix='pytors-include-existing-import-')as directory:
            root=Path(directory);(root/'helper.py').write_text('value=7\n')
            self.check('import helper\nprint(helper.value)\n',TranspileOptions(filename=str(root/'main.py'),include_modules=('helper',)))

    def test_source_directive_overrides_cli_bundle_names(self):
        with tempfile.TemporaryDirectory(prefix='pytors-include-directive-')as directory:
            root=Path(directory);(root/'helper.py').write_text('value=7\n')
            diagnostic=self.check('# pytors: --include-module helper\nprint(1)\n',TranspileOptions(filename=str(root/'main.py'),include_modules=('missing',)))
            self.assertIn('helper',diagnostic.message)
            self.assertNotIn('missing',diagnostic.message)


if __name__=='__main__':unittest.main()
