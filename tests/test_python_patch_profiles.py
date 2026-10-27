"""Preserve the converter host's Python 3.14 patch-level metadata behavior."""
import ast
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust import codegen, python_profile


class PythonPatchProfileTests(unittest.TestCase):
    def test_official_ast_probe_and_emitted_profile(self):
        expected = ast.parse('t"{ x }"', mode="eval").body.values[0].str == " x "
        self.assertEqual(python_profile.TSTRING_PRESERVES_TRAILING_WHITESPACE, expected)
        result = transpile('print([])\n', TranspileOptions(optimize=False))
        self.assertTrue(result.success, result.diagnostics)
        for name in ("TSTRING_PRESERVES_TRAILING_WHITESPACE", "ANN_QUALNAME_USES_OWNER",
                     "EG_REPR_USES_EXCEPTIONS_TUPLE"):
            self.assertIn(f"const {name}: bool = {str(getattr(python_profile, name)).lower()};",
                          result.rust_source)

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required")
    def test_both_template_whitespace_profiles_and_future_stringizing(self):
        source = '\n'.join([
            'from __future__ import annotations',
            'x=7',
            'values=[t"{ x }",t"{ x = }",t"{ x !r:>3}",t"{(x + 1) }"]',
            'print([v.interpolations[0].expression for v in values])',
            'value=t"{x # comment must not appear',
            '}"',
            'print(repr(value.interpolations[0].expression))',
            'def f(value: t"hello { x }"): pass',
            'print(f.__annotations__["value"])',
        ]) + '\n'
        wrapper = 'import sys\nexec(sys.stdin.read())\n'
        with tempfile.TemporaryDirectory(prefix="pytors-patch-profiles-") as directory:
            root = Path(directory)
            for preserve in (False, True):
                with self.subTest(preserve=preserve):
                    with patch.object(codegen, "TSTRING_PRESERVES_TRAILING_WHITESPACE", preserve):
                        result = transpile(wrapper, TranspileOptions(optimize=False))
                    self.assertTrue(result.success, result.diagnostics)
                    rust, binary = root / 'main.rs', root / 'main'
                    rust.write_text(result.rust_source)
                    compiled = subprocess.run(['rustc', '--edition=2021', str(rust), '-o', str(binary)],
                                              capture_output=True, text=True, timeout=120)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    executed = subprocess.run([str(binary)], input=source, capture_output=True,
                                              text=True, timeout=30, env={'PATH': '/nonexistent'})
                    self.assertEqual(executed.returncode, 0, executed.stderr)
                    expressions = [' x ', ' x ', ' x ', '(x + 1) '] if preserve else [' x', ' x', ' x', '(x + 1)']
                    comment = 'x \n' if preserve else 'x'
                    annotation = "t'hello { x }'" if preserve else "t'hello { x}'"
                    self.assertEqual(executed.stdout,
                                     repr(expressions) + '\n' + repr(comment) + '\n' + annotation + '\n')


if __name__ == '__main__':
    unittest.main()
