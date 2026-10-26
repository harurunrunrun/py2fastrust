"""Conservative proofs for runtime components that a submission cannot reach."""

import ast

from .ir import Program


# These built-ins cannot call an argument as a Python function. Higher-order
# operations, reflection, imports and user-defined classes stay on the full path.
_LEAF_CALLS = frozenset({
    "abs", "ascii", "bin", "bool", "bytes", "chr", "complex", "dict", "divmod",
    "float", "format", "frozenset", "hash", "hex", "id", "input", "int",
    "isinstance", "issubclass", "len", "list", "oct", "ord", "pow", "print",
    "range", "repr", "reversed", "round", "set", "slice", "str", "sum", "tuple",
})

_SIMPLE_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.While,
    ast.Break, ast.Continue, ast.Pass, ast.Delete, ast.Constant, ast.Name,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.BinOp, ast.UnaryOp, ast.BoolOp,
    ast.Compare, ast.IfExp, ast.Subscript, ast.Slice, ast.Call, ast.keyword,
    ast.Starred, ast.NamedExpr, ast.JoinedStr, ast.FormattedValue,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)


def dynamic_compilation_unreachable(source: str, program: Program) -> bool:
    """Prove a single simple scope cannot invoke compile, eval or exec.

    Values can be literals, input, built-in values and their containers. There
    are no user functions, classes, imported code, attribute operations or
    higher-order calls. Every call has a known, unmodified leaf built-in as its
    target. In particular, rebinding int to eval and indirect calls invalidate
    the proof. Unknown syntax and analysis limits retain the full runtime.
    """
    # The compiler always bundles __future__ for possible future statements in
    # exec strings. It remains dormant here: the proof below permits no import,
    # reflection or call that can execute any bundled code.
    if not program.codes or program.codes[0].kind != "Module":
        return False
    if any(name != "__future__" for name, _ in program.modules):
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, _SIMPLE_NODES):
            return False
        if isinstance(node, ast.Name):
            if node.id == "__builtins__":
                return False
            if node.id in _LEAF_CALLS and not isinstance(node.ctx, ast.Load):
                return False
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _LEAF_CALLS:
                return False
    return True
