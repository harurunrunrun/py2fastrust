"""Conservative proofs for runtime components that a submission cannot reach."""

import ast
import builtins
from types import BuiltinFunctionType

from .ir import Program
from .ir_flow import LEAF_BUILTINS, analyze_program


# These built-ins cannot call an argument as a Python function. Higher-order
# operations, reflection, imports and user-defined classes stay on the full path.
_LEAF_CALLS = LEAF_BUILTINS

_SIMPLE_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.While,
    ast.Break, ast.Continue, ast.Pass, ast.Delete, ast.Constant, ast.Name,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.BinOp, ast.UnaryOp, ast.BoolOp,
    ast.Compare, ast.IfExp, ast.Subscript, ast.Slice, ast.Call, ast.keyword,
    ast.Starred, ast.NamedExpr, ast.JoinedStr, ast.FormattedValue,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)

# A closed collection of static functions cannot acquire an evaluator through
# an external caller: it starts at the generated module and has no imports,
# attribute access or reflective namespace operations. Keep this separate from
# the leaf-value proof; arguments of user functions need not have known types.
_FUNCTION_NODES = _SIMPLE_NODES + (
    ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Lambda,
    ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
)
_CAPABILITIES = frozenset({
    "eval", "exec", "compile", "__builtins__", "__import__", "__loader__",
    "__spec__", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "dir", "help", "breakpoint",
})
# A static function name may be rebound. Deny non-leaf builtin values as well
# as direct calls, so rebinding cannot expand the closed-call capability set.
_UNSAFE_NAMES = _CAPABILITIES | frozenset(
    name for name, value in vars(builtins).items()
    if isinstance(value, (type, BuiltinFunctionType)) and name not in _LEAF_CALLS
) | {"copyright", "credits", "license", "quit", "exit"}
_CLOSED_OPERATIONS = frozenset({
    "Const", "Load", "Store", "Delete", "LoadCell", "StoreCell", "Pop", "Nop",
    "Dup", "Swap", "Binary", "Inplace", "Unary", "Compare", "Jump",
    "JumpTrue", "JumpFalse", "BuildList", "BuildTuple", "BuildSet",
    "BuildDict", "ListAppend", "ListExtend", "SetAdd", "SetUpdate",
    "DictAdd", "DictUpdate", "DictMerge", "GetItem", "SetItem", "DelItem",
    "BuildSlice", "Unpack", "UnpackEx", "GetIter", "ForIter", "Break",
    "Continue", "MakeFunction", "Call", "CallEx", "Return", "Yield", "GetYieldFromIter",
    "YieldFrom", "BeginComprehension", "EndComprehension", "SetupFinally",
    "PopHandler", "EndFinally", "FormatValue", "BuildString", "GetAttr", "SetAttr", "Raise",
})


def _closed_static_functions(tree, program):
    """Prove that static callbacks have no route to runtime compilation."""
    nodes = list(ast.walk(tree))
    functions = {node.name for node in nodes if isinstance(node, ast.FunctionDef)}
    functions.update(target.id for node in nodes if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Lambda)
                     for target in node.targets if isinstance(target, ast.Name))
    if not functions and not any(isinstance(node, (ast.ListComp, ast.SetComp,
                                                   ast.DictComp, ast.GeneratorExp))
                                 for node in nodes):
        return False
    for node in nodes:
        if not isinstance(node, _FUNCTION_NODES):
            return False
        if isinstance(node, ast.Name):
            if node.id in _UNSAFE_NAMES:
                return False
            if node.id in _LEAF_CALLS and not isinstance(node.ctx, ast.Load):
                return False
        if isinstance(node, ast.FunctionDef) and node.name in _CAPABILITIES | _LEAF_CALLS:
            return False
        if isinstance(node, ast.arg) and node.arg in _CAPABILITIES | _LEAF_CALLS:
            return False
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _LEAF_CALLS | functions:
                return False
    # Independently check the lowered bodies. Inlined comprehensions introduce
    # append/add lookups, but arbitrary attribute recovery is never permitted.
    pending, seen = [0], set()
    while pending:
        code_id = pending.pop()
        if code_id in seen:
            continue
        if not 0 <= code_id < len(program.codes):
            return False
        seen.add(code_id)
        code = program.codes[code_id]
        if code.kind not in {"Module", "Function", "Comprehension", "Annotation"}:
            return False
        for instruction in code.ops:
            if instruction.op not in _CLOSED_OPERATIONS:
                return False
            if instruction.op in {"Load", "LoadCell"} and instruction.args[0] in _UNSAFE_NAMES:
                # The official annotation lowering raises this builtin for
                # an unsupported annotation format. It is a fixed compiler
                # helper, rather than a capability obtained from input values.
                if not (code.kind == "Annotation" and instruction.args[0] == "NotImplementedError"):
                    return False
            if instruction.op == "GetAttr" and instruction.args[0] not in {"append", "add"}:
                return False
            if instruction.op == "SetAttr" and instruction.args[0] != "__annotate__":
                return False
            if instruction.op in {"MakeFunction", "BeginComprehension"}:
                pending.append(instruction.args[0])
    return True


def dynamic_compilation_unreachable(source: str, program: Program) -> bool:
    """Prove a closed source cannot invoke compile, eval or exec.

    Values can be literals, input, built-in values and their containers. There
    are no user functions, classes, imported code, attribute operations or
    higher-order external calls. Simple scopes use the leaf-value proof;
    static functions and comprehensions can also be closed when all their
    callbacks and value sources are confined to this module. Reflection,
    imports, attribute access and unknown syntax retain the full runtime.
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
    if _closed_static_functions(tree, program):
        return True
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
    # The AST remains necessary. Independently check the actual lowered calls:
    # compiler helpers or future changes must not introduce opaque targets,
    # rebinding or arbitrary effects behind a source-level leaf-call proof.
    return analyze_program(program).codes[0].proves_leaf_calls
