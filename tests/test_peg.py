"""Official-grammar PEG execution, independently of AST lowering and tokenizing."""

import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import token
import tokenize
from io import StringIO
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
fn main() {
    use std::io::{self, BufRead};
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut fields = line.split('\t');
        let mode = fields.next().unwrap();
        let tokens: Vec<PegToken> = fields.map(|field| {
            let parts: Vec<&str> = field.split(',').collect();
            let raw: Vec<u8> = parts[1].as_bytes().chunks(2).map(|pair|
                u8::from_str_radix(std::str::from_utf8(pair).unwrap(),16).unwrap()).collect();
            PegToken { kind: parts[0].into(), text: String::from_utf8(raw).unwrap(),
                line: parts[2].parse().unwrap(), column: parts[3].parse().unwrap() }
        }).collect();
        match PegParser::new(&tokens).parse(mode) {
            Ok(tree) => {
                let root = &tree.nodes[tree.root];
                let name = match root.kind { PegNodeKind::Rule(index) => PEG_RULES[index].name, _ => panic!("root must be a rule") };
                // Validate every arena edge, including memoized left-recursion
                // results and speculative nodes, rather than only the root.
                for node in &tree.nodes {
                    assert!(node.start <= node.end && node.end <= tokens.len());
                    for child in &node.children { assert!(*child < tree.nodes.len()); }
                    if let PegNodeKind::Token(index) = node.kind { assert!(index < tokens.len()); }
                }
                let bindings = tree.nodes.iter().filter(|node|matches!(node.kind,PegNodeKind::Binding(_))).count();
                println!("OK {} {} {} {}",name,root.start,root.end,bindings);
            },
            Err(error) => println!("ERR {} {} {}",error.line,error.column,error.expected.join("/")),
        }
    }
}
'''


def python_tokens(source, mode="exec"):
    tokens = []
    for entry in tokenize.generate_tokens(StringIO(source).readline):
        if entry.type in (token.COMMENT, token.NL, token.ENCODING):
            continue
        kind = token.tok_name[entry.exact_type]
        tokens.append((kind, entry.string, *entry.start))
    # CPython's single-input tokenizer supplies the newline after an implicit
    # EOF dedent. tokenize.generate_tokens has no single-input mode switch.
    if mode == "single" and len(tokens) > 1 and tokens[-2][0] == "DEDENT":
        tokens.insert(-1, ("NEWLINE", "", *tokens[-1][2:]))
    return tokens


def command(source, mode="exec"):
    return mode + "\t" + "\t".join(f"{kind},{text.encode().hex()},{line},{column}"
                                    for kind, text, line, column in python_tokens(source, mode))


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class PegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "tools/generate_peg.py", "--check"], cwd=ROOT, check=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="py2fastrust-peg-")
        source = Path(cls.temporary.name) / "peg.rs"
        source.write_text((ROOT / "py2fastrust/runtime/peg.rs").read_text()
                          + (ROOT / "py2fastrust/runtime/peg_tables.rs").read_text() + HARNESS)
        cls.binary = source.with_suffix("")
        result = subprocess.run(["rustc", "--edition=2021", "-A", "dead_code", "-O",
                                 str(source), "-o", str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def recognize(self, sources, mode="exec"):
        inputs = "\n".join(command(source, mode) for source in sources) + "\n"
        result = subprocess.run([str(self.binary)], input=inputs, text=True,
                                capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), len(sources), result.stderr)
        return lines

    def assert_accepts(self, sources, mode="exec"):
        for source in sources:
            ast.parse(source, mode=mode)
        for source, actual in zip(sources, self.recognize(sources, mode)):
            self.assertTrue(actual.startswith("OK "), (source, actual))

    def test_new_python314_constructs_and_all_grammar_entrypoints(self):
        self.assert_accepts([
            "type Alias[T: (int, str) = int, *Ts = *tuple[int], **P = [int, str]] = tuple[T, *Ts]\n",
            "def generic[T, *Ts, **P](x: T, *args: *Ts, **kwargs: P.kwargs) -> T:\n return x\n",
            "class Generic[T = int](Base[T]):\n pass\n",
            "try:\n call()\nexcept* (ValueError, TypeError) as errors:\n handle(errors)\n",
            "async def work(items):\n async with context() as value:\n  return [await f(x) async for x in items if x]\n",
            "message = t'hello {name!r:>{width}}' t' tail'\n",
            'message = f"{mapping["key"] = !r:>{width}}"\n',
            "match value:\n case {'name': (first, *rest), **extra} if first:\n  pass\n case Point(x=x, y=y) | Point(x=y, y=x):\n  pass\n",
            "def f(a, /, b=1, *items, key=None, **options):\n yield from items\n",
            "a, *b = [1, *values]\nx = {**d, 'x': 1}\nf(1, *args, a=2, **kw)\n",
        ])
        self.assert_accepts(["lambda x=1, /, *a, k=2, **kw: (x, a, k, kw)",
                             "[f(x) for x in values if x > 0]", "a.b.c[1:2, ::-1]"], "eval")
        self.assert_accepts(["(int, *tuple[str], **dict[str, int]) -> tuple[int, str]"], "func_type")
        self.assert_accepts(["value = 1\n", "if flag:\n value = 2\n"], "single")

    def test_left_recursion_precedence_bindings_and_long_chains(self):
        sources = ["a.b.c.d[0](1, 2).field + x * y ** -z << 2 & mask | extra\n",
                   "import a.b.c.d.e as module\n",
                   "value = " + "+".join("x" for _ in range(5000)) + "\n",
                   "value = " + "(" * 150 + "x" + ")" * 150 + "\n"]
        results = self.recognize(sources)
        for source, actual in zip(sources, results):
            self.assertTrue(actual.startswith("OK file 0 "), (source[:100], actual))
            self.assertGreater(int(actual.split()[-1]), 0)

    def test_structural_syntax_errors_cuts_and_lookahead(self):
        sources = ["x =\n", "if x print(x)\n", "x = a + * b\n", "x = [1,,2]\n",
                   "def f(a,,b): pass\n", "try: pass\n", "class A(,): pass\n",
                   "x := 1\n", "import x as\n", "from x import a,\n",
                   "x = lambda a,:\n", "for x in : pass\n", "with value as : pass\n",
                   "type T[] = int\n", "match x:\n case x | : pass\n"]
        for source in sources:
            with self.assertRaises(SyntaxError):
                ast.parse(source)
        for source, actual in zip(sources, self.recognize(sources)):
            self.assertTrue(actual.startswith("ERR "), (source, actual))
            self.assertGreaterEqual(int(actual.split()[1]), 1)

    def test_repository_execution_fixtures(self):
        sources = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            if path.name == "test_peg.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"run_source", "compare_static_and_dynamic", "compare"} and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    source = textwrap.dedent(node.args[0].value)
                    try:
                        ast.parse(source)
                    except SyntaxError:
                        continue
                    sources.append(source)
        self.assertGreater(len(sources), 50)
        self.assert_accepts(sources)

    def test_complete_standard_library_modules(self):
        import ast as ast_module
        import bisect
        import collections
        import functools
        import heapq
        import symtable
        import __future__
        modules = [__future__, ast_module, bisect, collections, functools, heapq, symtable, tokenize]
        self.assert_accepts([Path(module.__file__).read_text() for module in modules])


if __name__ == "__main__":
    unittest.main()
