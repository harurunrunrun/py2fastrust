import unittest

from py2fastrust.compiler import Compiler
from py2fastrust.diagnostics import CompilationError


class FrontendTests(unittest.TestCase):
    def test_rebinding_and_source_locations(self):
        program = Compiler("example.py").compile('x = 1\nx = "hello"\nprint(x)\n')
        self.assertEqual(program.codes[0].bindings["x"], 2)
        stores = [op for op in program.codes[0].ops if op.op == "Store"]
        self.assertEqual([op.line for op in stores], [1, 2])

    def test_official_scope_information(self):
        program = Compiler().compile("x=1\ndef f():\n print(x)\n x=2\n")
        function = program.codes[1]
        self.assertIn("x", function.locals)
        self.assertNotIn("x", function.globals)
        self.assertIn("print", function.globals)

    def test_comprehension_has_isolated_bindings(self):
        program = Compiler().compile("def f(n):\n return [x+n for x in range(n)]\n")
        code = next(c for c in program.codes if c.name == "listcomp")
        self.assertIn("x", code.locals)
        self.assertNotIn("n", code.globals)
        self.assertEqual(code.params.positional, [".0"])

    def test_invalid_context_is_rejected_by_cpython(self):
        for source in ("return 1", "break", "nonlocal x", "yield 1", "continue"):
            with self.subTest(source=source), self.assertRaises(CompilationError):
                Compiler().compile(source)

    def test_unsupported_syntax_is_positioned(self):
        with self.assertRaises(CompilationError) as caught:
            Compiler("case.py").compile("async def f():\n pass\n")
        self.assertEqual(caught.exception.diagnostic.filename, "case.py")
        self.assertEqual(caught.exception.diagnostic.line, 1)
        self.assertEqual(caught.exception.diagnostic.code, "E002")


if __name__ == "__main__":
    unittest.main()
