"""Configured ASCII byte indices and opt-in Python Unicode character indices."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_text_policy import apply_text_policy


class TextPolicyTests(unittest.TestCase):
    def test_default_and_source_precedence_and_invalid_api_options(self):
        self.assertEqual(TranspileOptions().string_mode, "ascii")
        self.assertIn("// String mode: ascii.", transpile("print(1)\n").rust_source)
        for mode, opposite in (("ascii", "unicode"), ("unicode", "ascii")):
            result = transpile(f'# pytors: --string-mode {mode}\ns=input()\nprint(s[0])\n',
                               TranspileOptions(string_mode=opposite))
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn(f"// String mode: {mode}.", result.rust_source)
        for invalid in ("invalid", None, 3, []):
            result = transpile("print(1)\n", TranspileOptions(string_mode=invalid))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code, "E004")
        result = transpile('# ordinary\n# pytors: --string-mode invalid\nprint(1)\n')
        self.assertEqual((result.diagnostics[0].code, result.diagnostics[0].line), ("E004", 2))

    def test_cli_uses_source_string_mode_before_command_line_setting(self):
        with tempfile.TemporaryDirectory(prefix="pytors-text-cli-") as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text('# pytors: --string-mode unicode\ns=input()\nprint(s[0])\n')
            target = root / "main.rs"
            result = subprocess.run([sys.executable, "-m", "py2fastrust", str(source),
                                     "--string-mode", "ascii", "-o", str(target)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("// String mode: unicode.", target.read_text())

    def test_selection_does_not_rewrite_literals_or_provenance(self):
        source = '''// fn native_string_item(value: &str) { provenance }
const SOURCE: &str = r#"fn native_string_item() { literal }"#;
fn native_string_item(value:&str,index:NativeInt)->Result<String,String> {
    if value.is_ascii() { Ok(value.to_owned()) } else { unreachable!() }
}
fn main() { println!("{}", SOURCE); }
'''
        ascii_source = apply_text_policy(source)
        self.assertIn('// fn native_string_item(value: &str) { provenance }', ascii_source)
        self.assertIn('r#"fn native_string_item() { literal }"#', ascii_source)
        self.assertNotIn("value.is_ascii()", ascii_source)
        self.assertIn("value.as_bytes().get(index)", ascii_source)
        self.assertEqual(apply_text_policy(source, "unicode"), source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeStringModeTests(unittest.TestCase):
    def compare(self, source, data, string_mode, class_backend=False):
        expected = subprocess.run([sys.executable, "-c", source], input=data,
                                  text=True, capture_output=True, timeout=5)
        with tempfile.TemporaryDirectory(prefix="pytors-text-mode-") as directory:
            root = Path(directory)
            for integer in ("i64", "i128", "bigint"):
                with self.subTest(integer=integer, string_mode=string_mode):
                    options = TranspileOptions(integer=integer, string_mode=string_mode)
                    result = transpile(source, options)
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, "native")
                    rust = root / "main.rs"
                    rust.write_text(result.rust_source)
                    binary = root / "main"
                    build = subprocess.run(["rustc", "--edition=2021", "-O", str(rust),
                                            "-o", str(binary)], text=True,
                                           capture_output=True, timeout=90)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    actual = subprocess.run([str(binary)], input=data, text=True,
                                            capture_output=True, timeout=5,
                                            env={"PATH": "/unavailable"})
                    self.assertEqual((actual.returncode, actual.stdout),
                                     (expected.returncode, expected.stdout), actual.stderr)
                    if string_mode == "ascii":
                        helper = ("class_string_get" if class_backend else
                                  "native_big_text_item" if integer == "bigint" else
                                  "native_string_item")
                        from py2fastrust.native_text_policy import _ASCII_HELPERS, _BORROW_HELPERS
                        candidates = [_ASCII_HELPERS[helper].strip()]
                        if not class_backend:
                            candidates.append(_BORROW_HELPERS[helper+"_ref"].strip())
                            # A nonescaping character may use its scalar value
                            # directly, without building a one-character str.
                            codepoint = ("native_big_ascii_codepoint" if integer == "bigint"
                                         else "native_ascii_codepoint")
                            candidates.append(_BORROW_HELPERS[codepoint].strip())
                        self.assertTrue(any(body in result.rust_source for body in candidates))
                    if expected.returncode:
                        self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                         expected.stderr.splitlines()[-1].split(":")[0])

    def test_ascii_index_slice_count_and_specialized_calls(self):
        self.compare('''s=input().strip()
def item(s,i):
    return s[i]
print(len(s),s[0],s[-1],s[1:-1],s[::-2],s.count("",1,-1),s.count("1"))
print(item(s,2))
''', "101001110\n", "ascii")

    def test_unicode_opt_in_keeps_codepoint_semantics(self):
        self.compare('''s=input()
def item(s,i):
    return s[i]
print(len(s),s[0],s[-1],s[1:-1],s[::-2],s.count("",1,-1),s.count("猫"))
print(item(s,2))
''', "猫🐈é海\n", "unicode")

    def test_ascii_negative_out_of_bounds(self):
        self.compare('s=input()\nprint(s[-4])\n', "abc\n", "ascii")

    def test_borrowed_reads_and_owned_results_preserve_string_snapshots(self):
        self.compare('''s=input()
head=s[0]
alias=s
s=input()
print(head,alias[0],s[0],(input()+"x")[-1])
size=len
print(size(alias),len(s))
''', "abc\ndefgh\nlast\n", "ascii")

    def test_read_only_index_loop_does_not_allocate_or_scan_the_owner(self):
        source='''s=input()
answer=0
for i in range(len(s)):
    if s[i]=="x":
        answer+=1
print(answer)
'''
        self.compare(source, "xxoxxoxox\n", "ascii")
        for integer in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            start=re.search(r"\bfn main\s*\(\s*\)\s*\{",result.rust_source).end()
            main=result.rust_source[start:].split("std::io::stdout()",1)[0]
            if integer!="bigint":
                self.assertNotIn(".clone()",main)
            for owner in re.findall(r"let mut (native_var_\d+): String;",main):
                self.assertNotIn(f"{owner}.clone()",main)
                self.assertNotIn(f"({owner}).clone()",main)
            self.assertNotIn(".chars()",main)
            self.assertNotIn(".is_ascii()",main)
            getter = ("native_big_ascii_codepoint" if integer == "bigint"
                      else "native_ascii_codepoint")
            self.assertIn(getter + "(", main)
            self.assertRegex(result.rust_source,
                             rf"fn {getter}\([^{{]+Result<u32,String>")
            if integer != "bigint":
                self.assertIn("native_region_guard_", main)
                self.assertIn(".iter()).enumerate()", main)

    def test_class_string_index_and_length_use_the_selected_mode(self):
        source = '''class Text:
    def __init__(self,value):
        self.value=value
    def at(self,index):
        return self.value[index]
    def size(self):
        return len(self.value)
t=Text(input())
print(t.at(0),t.at(-1),t.size())
'''
        for mode, data in (("ascii", "abc\n"), ("unicode", "猫🐈海\n")):
            self.compare(source, data, mode, class_backend=True)


if __name__ == "__main__":
    unittest.main()
