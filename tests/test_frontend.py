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
        self.assertNotIn("print", function.globals)
        self.assertIn("print", [op.args[0] for op in function.ops if op.op == "Load"])

    def test_free_names_and_local_cell_order_are_explicit(self):
        program = Compiler().compile("def outer():\n z=1\n a=2\n ordinary=3\n def inner():\n  return z+a\n return locals()\n")
        outer = next(code for code in program.codes if code.name == "outer")
        inner = next(code for code in program.codes if code.name == "inner")
        self.assertEqual(outer.locals, ["ordinary", "inner", "a", "z"])
        self.assertEqual(set(inner.frees), {"a", "z"})
        self.assertEqual(inner.nonlocals, [])

    def test_comprehension_has_isolated_bindings(self):
        program = Compiler().compile("def f(n):\n return [x+n for x in range(n)]\n")
        code = next(c for c in program.codes if c.name == "listcomp")
        owner = next(c for c in program.codes if c.name == "f")
        code_id = program.codes.index(code)
        self.assertIn("x", code.locals)
        self.assertNotIn("n", code.globals)
        self.assertEqual(code.params.positional, [])
        self.assertIn(("BeginComprehension", (code_id,)), [(op.op, op.args) for op in owner.ops])
        self.assertIn("EndComprehension", [op.op for op in owner.ops])
        self.assertFalse(any(op.op == "MakeFunction" and op.args[0] == code_id for op in owner.ops))
        self.assertFalse(any(op.op == "Load" and op.args[0] == ".0" for op in owner.ops))

    def test_generator_comprehension_retains_its_own_frame(self):
        program = Compiler().compile("def f(n):\n return (x+n for x in range(n))\n")
        code = next(c for c in program.codes if c.name == "genexpr")
        owner = next(c for c in program.codes if c.name == "f")
        code_id = program.codes.index(code)
        self.assertEqual(code.params.positional, [".0"])
        self.assertTrue(code.is_generator)
        self.assertTrue(any(op.op == "MakeFunction" and op.args[0] == code_id for op in owner.ops))
        self.assertNotIn("BeginComprehension", [op.op for op in owner.ops])

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

    def test_unknown_standard_submodule_is_a_static_diagnostic(self):
        with self.assertRaises(CompilationError) as caught:
            Compiler("imports.py").compile("import math.missing\n")
        self.assertEqual(caught.exception.diagnostic.code, "E003")
        self.assertEqual(caught.exception.diagnostic.filename, "imports.py")
        self.assertEqual(caught.exception.diagnostic.line, 1)

    def test_private_names_follow_class_scope_into_functions(self):
        program = Compiler().compile("class _C:\n def __f(self, __x=1, *, __k=2):\n  self.__value=__x+__k\n  return self.__value\n")
        body = next(code for code in program.codes if code.name == "_C")
        function = next(code for code in program.codes if code.name == "__f")
        self.assertIn("_C__f", body.locals)
        self.assertEqual(function.params.positional, ["self", "_C__x"])
        self.assertEqual(function.params.kwonly, ["_C__k"])
        self.assertIn("_C__x", function.locals)
        self.assertIn("_C__value", [op.args[0] for op in function.ops if op.op == "SetAttr"])
        self.assertIn(["_C__k"], [op.args[2] for op in body.ops if op.op == "MakeFunction"])


if __name__ == "__main__":
    unittest.main()
