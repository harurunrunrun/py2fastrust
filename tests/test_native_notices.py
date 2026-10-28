"""Third-party notices follow retained native code and data, not source AST use."""
from importlib.resources import files
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_notices import retain_native_notices


PSF = "// PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2"
UNICODE = "// UNICODE LICENSE V3"


class NativeNoticeTests(unittest.TestCase):
    def test_tokens_in_comments_and_literals_do_not_retain_licenses(self):
        source = '''// fn native_float_divmod() {} const ZEROES: &[u32] = &[];
fn main() { let text="const TEXT_PRINTABLE fn native_float_divmod"; }
'''
        result = retain_native_notices(source)
        self.assertNotIn(PSF, result)
        self.assertNotIn(UNICODE, result)
        self.assertNotIn("Copyright (c) 2026 py2fastrust contributors", result)
        self.assertNotIn("Dictionary copy and merge paths", result)

    def test_each_retained_component_keeps_its_license(self):
        for definition, psf, unicode in (
            ("fn native_float_divmod() {}", True, False),
            ("const TEXT_PRINTABLE: &[(u32,u32)] = &[];", False, True),
            ("const NATIVE_TUPLE_PRINTABLE: &[(u32,u32)] = &[];", False, True),
            ("impl Int { fn decimal_digit() { const ZEROES:&[u32]=&[]; } }", False, True),
            ("impl Int { fn format_digit() { const RANGES:&[(u32,u32)]=&[]; } }", False, True),
        ):
            with self.subTest(definition=definition):
                result = retain_native_notices(definition)
                self.assertEqual(PSF in result, psf)
                self.assertEqual(UNICODE in result, unicode)

    def test_assembly_bundles_are_replaced_without_duplicate_notices(self):
        root = files("py2fastrust")
        notice = root.joinpath("runtime", "NOTICE.txt").read_text()
        blocks = ["/*\n" + notice + "\n*/\n"]
        for name in ("PYTHON_LICENSE.txt", "UNICODE_LICENSE.txt"):
            text = root.joinpath("stdlib", name).read_text()
            blocks.append("\n".join("// " + line for line in text.splitlines()) + "\n")
        result = retain_native_notices("\n".join(blocks) + "\nfn main() {}\n")
        self.assertNotIn(PSF, result)
        self.assertNotIn(UNICODE, result)
        self.assertNotIn("Copyright (c) 2026 py2fastrust contributors", result)

    def test_public_pruned_output_and_no_optimize_keep_required_notices(self):
        cases = (
            ("print(3)\n", True, False, False),
            ('s=input()\nprint(s[0],len(s))\n', True, False, False),
            ("print(3.5//2.0)\n", True, True, False),
            ('print(int("٤٢"))\n', True, False, True),
            ('s=input()\nprint(s[0],len(s))\n', False, True, True),
        )
        for source, optimize, psf, unicode in cases:
            with self.subTest(source=source, optimize=optimize):
                result = transpile(source, TranspileOptions(optimize=optimize, string_mode="unicode"))
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(PSF in result.rust_source, psf)
                self.assertEqual(UNICODE in result.rust_source, unicode)


if __name__ == "__main__":
    unittest.main()
