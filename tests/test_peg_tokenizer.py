"""Rust tokenization and PEG parsing against CPython's Unicode 16 tokenizer."""

import ast
from io import StringIO
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import token
import tokenize
import unittest

import test_peg


ROOT = test_peg.ROOT
HARNESS = r'''
fn main() {
    use std::io::{self,BufRead};
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();let (mode,hex)=line.split_once('\t').unwrap();
        let raw:Vec<u8>=hex.as_bytes().chunks(2).map(|p|u8::from_str_radix(std::str::from_utf8(p).unwrap(),16).unwrap()).collect();
        let source=String::from_utf8(raw).unwrap();
        match PegLexer::new(&source).lex(mode) {
            Ok(tokens)=>{
                let parsed=PegParser::new(&tokens).parse(mode).is_ok();
                print!("OK {}",parsed);
                for token in tokens {
                    let hex:String=token.text.as_bytes().iter().map(|byte|format!("{:02x}",byte)).collect();
                    print!("\t{},{},{},{}",token.kind,hex,token.line,token.column);
                }
                println!();
            },
            Err(error)=>println!("ERR {} {} {} {}",error.kind,error.line,error.column,error.message),
        }
    }
}
'''


def canonical(tokens):
    result = []
    for kind, text, line, column in tokens:
        if kind in ("FSTRING_MIDDLE", "TSTRING_MIDDLE"):
            if not text:
                continue
            if result and result[-1][0] == kind:
                previous = result[-1]
                result[-1] = (kind, previous[1] + text, previous[2], previous[3])
                continue
        result.append((kind, text, line, column))
    return result


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class PegTokenizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="py2fastrust-peg-tokenizer-")
        source = Path(cls.temporary.name) / "lexer.rs"
        text_runtime = (ROOT / "py2fastrust/runtime/text.rs").read_text()
        tables = text_runtime[text_runtime.index("// BEGIN GENERATED UNICODE TABLES"):
                              text_runtime.index("// END GENERATED UNICODE TABLES")]
        property_fn = text_runtime[text_runtime.index("fn text_property("):text_runtime.index("fn text_space(")]
        source.write_text(tables + property_fn
                          + (ROOT / "py2fastrust/runtime/peg.rs").read_text()
                          + (ROOT / "py2fastrust/runtime/peg_tables.rs").read_text()
                          + (ROOT / "py2fastrust/runtime/peg_tokenizer.rs").read_text() + HARNESS)
        cls.binary = source.with_suffix("")
        result = subprocess.run(["rustc", "--edition=2021", "-O", "-A", "dead_code",
                                 str(source), "-o", str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_sources(self, sources, mode="exec"):
        inputs = "\n".join(mode + "\t" + source.encode().hex() for source in sources) + "\n"
        result = subprocess.run([str(self.binary)], input=inputs, capture_output=True,
                                text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = result.stdout.splitlines()
        self.assertEqual(len(outputs), len(sources))
        return outputs

    def check_valid(self, sources, mode="exec"):
        for source, actual in zip(sources, self.run_sources(sources, mode)):
            ast.parse(source, mode=mode)
            self.assertTrue(actual.startswith("OK true"), (source[:500], actual[:500]))
            got = []
            for field in actual.split("\t")[1:]:
                kind, raw, line, column = field.split(",")
                got.append((kind, bytes.fromhex(raw).decode(), int(line), int(column)))
            expected = test_peg.python_tokens(source, mode)
            self.assertEqual(canonical(got), canonical(expected), source[:500])

    def test_whitespace_indentation_continuations_and_comments(self):
        self.check_valid(["", "\n", "#end", "   ", "pass\n  ", "x=1 #end",
                          "if flag:\n\tpass\nelse:\n\tpass\n#end",
                          "if flag:\n\tif other:\n\t\tpass\n",
                          "x = (1 #comment\n     + 2)\ny = 1 + \\\n+ 2\n",
                          "x = [\n #comment\n 1, 2,\n]\n",
                          "if flag:\n \f    pass\n"])
        self.check_valid(["if x:\n pass\n", "x=1\n"], "single")

    def test_numeric_literals_operators_and_unicode_identifiers(self):
        rng = random.Random(369452)
        numbers = ["0", "00", "0_0", "123_456", "0x_ff", "0B_10_01", "0o_777",
                   ".5", "1.", "1.e2", "1.2e-30", "0_0.1_2e+3_4", "1j", "00J", ".1j"]
        numbers += [f"{rng.randrange(100000)}_{rng.randrange(10000):04}.{rng.randrange(10000):04}e{rng.randrange(-300,300)}"
                    for _ in range(300)]
        self.check_valid(["value = " + number + "\n" for number in numbers])
        self.check_valid(["变量 = 1\n結果 = 变量+2\n", "a\u0301 = K = 1\n",
                          "𐐀 = 1\nvalue = 𐐀\n", "a = (x := 1) if x != 2 else ...\n",
                          "a @= b\na //= 2\na **= 3\na >>= 1\n"])

    def test_raw_triple_fstrings_tstrings_and_reused_quotes(self):
        sources = ["s = 'a\\n\\x41' b'\\x00'\n", "s = r'a\\b'\n",
                   "s = '''one\ntwo'''\n", "s = br'''one\\\ntwo'''\n",
                   's = f"{mapping["key"]!r:>{width}}"\n',
                   "s = t'hello {x=} {y!r}'\n", "s = f'{{}} {{ literal }} {value}'\n",
                   "s = f'{ {1: 2} }'\n", "s = f'{value:{{}}}'\n",
                   "s = f'{value:{width}.{precision}f}'\n", 's = f"{x # comment\n}"\n',
                   's = f"{f"{value}"}"\n', "s = f'\\N{SNOWMAN}{value}'\n",
                   "s = rf'\\N{value}'\n", "s = f'\\\\{value}'\n",
                   "s = t'''prefix\n{value!s:>{width}} tail'''\n"]
        # Bytes/nonbytes concatenation is a lowering error, so keep each valid
        # literal in its own expression for end-to-end syntax comparison.
        sources[0] = "a = 'a\\n\\x41'\nb = b'\\x00'\n"
        self.check_valid(sources)

    def test_new_python_grammar_and_complete_standard_modules(self):
        self.check_valid(["type Alias[T = int, *Ts = *tuple[str], **P = [int]] = tuple[T, *Ts]\n",
                          "try:\n f()\nexcept* ValueError as errors:\n handle(errors)\n",
                          "async def f(items):\n return [await g(x) async for x in items]\n"])
        import ast as ast_module
        import collections
        import functools
        import heapq
        import symtable
        self.check_valid([Path(module.__file__).read_text() for module in
                          [ast_module, collections, functools, heapq, symtable, tokenize]])

    def test_lexical_errors_and_depth_limits(self):
        sources = ["x=(1]\n", "x=1\\ x\n", "x=1\\\n", "x='unterminated\n",
                   "x=0b2\n", "x=0x_\n", "x=1__2\n", "x=1e+\n", "x=01\n",
                   "x=f'{x'\n", "x=f'}'\n", "x=\x00\n", "x=\u0301\n",
                   "if x:\n\tpass\n        pass\n",
                   "if x:\n pass\n  pass\n pass\n  pass\n   pass\n pass\n pass\n", # grammar-level unexpected indent
                   "x=" + "(" * 201 + "1" + ")" * 201]
        # Separate lexical errors from structurally invalid token streams.
        for source, actual in zip(sources, self.run_sources(sources)):
            with self.assertRaises((SyntaxError, IndentationError)):
                ast.parse(source)
            self.assertFalse(actual.startswith("OK true"), (source, actual))


if __name__ == "__main__":
    unittest.main()
