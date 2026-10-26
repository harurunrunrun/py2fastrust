"""Independent whole-program oracle for the selected integer policy.

The official AST is instrumented, then CPython executes ordinary control flow,
functions/closures, generators and built-in containers. Exact ``int`` results
(never bool) are signed-normalized after each literal, arithmetic operation,
in-place operation and supported call. ``sum``, ``pow``, ``divmod``, ``map``,
``filter`` and ``enumerate`` need explicit handling because their work otherwise
happens inside an uninstrumented CPython builtin.

This is a deliberately bounded reference language, not another Python runtime.
Imports, classes, annotations, async, with, match, t-strings, reflective/dynamic
code access, process exits/interrupts, arbitrary external callables and
non-integer sum are rejected.
Only source-defined functions and the listed builtins/container methods may be
called. Unsupported execution sets an out-of-band failure flag, so user except
clauses cannot silently turn an unsupported case into a successful oracle run.
"""

import ast
import builtins
from contextlib import redirect_stdout
from dataclasses import dataclass
import io
import operator
import sys
import types


class UnsupportedReference(Exception):
    """The source or a runtime operation is outside the stated oracle scope."""


@dataclass(frozen=True)
class ReferenceResult:
    stdout: str
    exception_type: str | None = None
    exception_message: str | None = None

    @property
    def returncode(self):
        return int(self.exception_type is not None)


def normalize(value, integer):
    """Normalize an exact integer; preserve bool and every non-integer object."""
    if integer not in {"i64", "i128", "bigint"}:
        raise ValueError("integer must be i64, i128 or bigint")
    if type(value) is not int or integer == "bigint":
        return value
    bits = 64 if integer == "i64" else 128
    residue = value % (1 << bits)
    return residue if residue < 1 << (bits - 1) else residue - (1 << bits)


_BINARY = {"Add": operator.add, "Sub": operator.sub, "Mult": operator.mul,
           "Div": operator.truediv, "FloorDiv": operator.floordiv, "Mod": operator.mod,
           "LShift": operator.lshift, "RShift": operator.rshift, "BitOr": operator.or_,
           "BitXor": operator.xor, "BitAnd": operator.and_}
_INPLACE = {name: getattr(operator, "i" + function.__name__.rstrip("_"))
            for name, function in _BINARY.items()}
_INPLACE["Pow"] = operator.ipow
_UNARY = {"UAdd": operator.pos, "USub": operator.neg, "Invert": operator.invert,
          "Not": operator.not_}
_SAFE_NAMES = {
    "abs", "all", "any", "bin", "bool", "bytes", "callable", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "hex", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next", "oct", "ord",
    "pow", "print", "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "type", "zip",
}
_FORBIDDEN_NAMES = {
    "__builtins__", "__import__", "__name__", "__package__", "__spec__", "__file__",
    "__loader__", "__cached__", "__doc__", "breakpoint", "compile", "delattr", "dir", "eval",
    "exec", "getattr", "globals", "hasattr", "help", "id", "locals", "memoryview",
    "open", "setattr", "super", "vars", "SystemExit", "KeyboardInterrupt",
}
_METHOD_TYPES = (list, tuple, dict, set, str, bytes, int, bool, float, range)
_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Delete, ast.If, ast.While,
    ast.For, ast.Break, ast.Continue, ast.Pass, ast.FunctionDef, ast.Return,
    ast.Global, ast.Nonlocal, ast.Try, ast.ExceptHandler, ast.Raise, ast.Assert,
    ast.Name, ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Starred, ast.NamedExpr, ast.Lambda,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.Yield, ast.YieldFrom, ast.JoinedStr, ast.FormattedValue, ast.arguments,
    ast.arg, ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)


class _Validate(ast.NodeVisitor):
    def generic_visit(self, node):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsupportedReference(f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.MatMult):
            raise UnsupportedReference("matrix multiplication is outside the oracle scope")
        if isinstance(node, ast.Constant) and isinstance(node.value, complex):
            raise UnsupportedReference("complex values are outside the oracle scope")
        if isinstance(node, ast.comprehension) and node.is_async:
            raise UnsupportedReference("async comprehensions are outside the oracle scope")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise UnsupportedReference(f"reflective/dynamic name is unsupported: {node.id}")
        if isinstance(node, ast.Name) and node.id in vars(builtins) and node.id not in _SAFE_NAMES:
            value = vars(builtins)[node.id]
            if not (isinstance(value, type) and issubclass(value, BaseException)):
                raise UnsupportedReference(f"builtin is outside the oracle scope: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise UnsupportedReference(f"dunder access is unsupported: {node.attr}")
        if isinstance(node, ast.FunctionDef) and (node.type_params or node.returns is not None):
            raise UnsupportedReference("type parameters and annotations are unsupported")
        if isinstance(node, ast.arg) and node.annotation is not None:
            raise UnsupportedReference("annotations are unsupported")
        super().generic_visit(node)


class _Instrument(ast.NodeTransformer):
    def __init__(self, helper_name):
        self.helper_name = helper_name
        self.next_temp = 0

    def helper(self, method, arguments, node):
        call = ast.Call(ast.Attribute(ast.Name(self.helper_name, ast.Load()), method, ast.Load()),
                        arguments, [])
        return ast.copy_location(call, node)

    def temporary(self):
        self.next_temp += 1
        return f"{self.helper_name}_temp_{self.next_temp}"

    def visit_Constant(self, node):
        if type(node.value) is int:
            return self.helper("normal", [node], node)
        return node

    def visit_BinOp(self, node):
        return self.helper("binary", [ast.Constant(type(node.op).__name__),
                                      self.visit(node.left), self.visit(node.right)], node)

    def visit_UnaryOp(self, node):
        return self.helper("unary", [ast.Constant(type(node.op).__name__), self.visit(node.operand)], node)

    def visit_Call(self, node):
        call = self.helper("call", [self.visit(node.func), *[self.visit(arg) for arg in node.args]], node)
        call.keywords = [ast.keyword(keyword.arg, self.visit(keyword.value)) for keyword in node.keywords]
        return call

    def visit_AugAssign(self, node):
        operation = ast.Constant(type(node.op).__name__)
        if isinstance(node.target, ast.Name):
            value = self.helper("inplace", [operation, ast.Name(node.target.id, ast.Load()),
                                            self.visit(node.value)], node)
            return ast.copy_location(ast.Assign([node.target], value), node)
        names = []
        statements = []

        def save(value):
            name = self.temporary()
            names.append(name)
            statements.append(ast.Assign([ast.Name(name, ast.Store())], value))
            return ast.Name(name, ast.Load())

        target = node.target
        receiver = save(self.visit(target.value))
        if isinstance(target, ast.Subscript):
            # Slices are evaluated once too; ast.Slice is not an expression.
            def slice_expression(part):
                if isinstance(part, ast.Slice):
                    return self.helper("slicing", [self.visit(item) if item is not None else ast.Constant(None)
                                                   for item in (part.lower, part.upper, part.step)], part)
                if isinstance(part, ast.Tuple):
                    return ast.Tuple([slice_expression(item) for item in part.elts], ast.Load())
                return self.visit(part)
            key = save(slice_expression(target.slice))
            load = ast.Subscript(receiver, key, ast.Load())
            store = ast.Subscript(receiver, key, ast.Store())
        else:
            load = ast.Attribute(receiver, target.attr, ast.Load())
            store = ast.Attribute(receiver, target.attr, ast.Store())
        old = save(load)
        value = self.helper("inplace", [operation, old, self.visit(node.value)], node)
        statements += [ast.Assign([store], value),
                       ast.Delete([ast.Name(name, ast.Del()) for name in names])]
        return [ast.copy_location(statement, node) for statement in statements]


class _Operations:
    def __init__(self, integer):
        self.integer = integer
        self.bits = {"i64": 64, "i128": 128, "bigint": 0}[integer]
        self.namespace = None
        self.unsupported = None

    def fail(self, message):
        self.unsupported = message
        raise UnsupportedReference(message)

    def normal(self, value):
        if isinstance(value, complex):
            self.fail("complex values are outside the oracle scope")
        return normalize(value, self.integer)

    @staticmethod
    def slicing(start, stop, step):
        return slice(start, stop, step)

    def binary(self, operation, left, right):
        if operation == "Pow":
            return self.power(left, right)
        if operation == "LShift" and self.bits and isinstance(left, int) and isinstance(right, int):
            if right < 0:
                raise ValueError("negative shift count")
            if right >= self.bits:
                return 0
        return self.normal(_BINARY[operation](left, right))

    def unary(self, operation, value):
        return self.normal(_UNARY[operation](value))

    def inplace(self, operation, left, right):
        if operation in {"Pow", "LShift"} and isinstance(left, int):
            return self.binary(operation, left, right)
        return self.normal(_INPLACE[operation](left, right))

    def power(self, base, exp, mod=None):
        if mod is not None:
            return self.normal(pow(base, exp, mod))
        if self.bits and isinstance(base, int) and isinstance(exp, int) and exp >= 0:
            return self.normal(pow(base, exp, 1 << self.bits))
        return self.normal(pow(base, exp))

    def total(self, iterable, /, start=0):
        if not isinstance(start, int):
            self.fail("sum oracle accepts integer/bool values and start only")
        total = start
        for value in iterable:
            if not isinstance(value, int):
                self.fail("sum oracle accepts integer/bool values and start only")
            total = self.binary("Add", total, value)
        return total

    def call(self, function, /, *arguments, **keywords):
        if function is sum:
            return self.total(*arguments, **keywords)
        if function is pow:
            return self.power(*arguments, **keywords)
        if function is divmod:
            return tuple(self.normal(value) for value in divmod(*arguments, **keywords))
        if function is map:
            if not arguments:
                return map(*arguments, **keywords)
            callback, *iterables = arguments
            return map(lambda *items: self.call(callback, *items), *iterables, **keywords)
        if function is filter:
            if len(arguments) != 2 or keywords:
                return filter(*arguments, **keywords)
            callback, iterable = arguments
            return filter(None if callback is None else lambda item: self.call(callback, item), iterable)
        if function is enumerate:
            values = enumerate(*arguments, **keywords)
            return ((self.normal(index), value) for index, value in values)
        if function is iter and len(arguments) == 2 and not keywords:
            callback, sentinel = arguments
            return iter(lambda: self.call(callback), sentinel)
        if function is type and (len(arguments) != 1 or keywords):
            self.fail("dynamic type construction is outside the oracle scope")
        if function in (sorted, min, max, list.sort) or (getattr(function, "__name__", None) == "sort"
                                             and type(getattr(function, "__self__", None)) is list):
            callback = keywords.get("key")
            if callback is not None:
                keywords = dict(keywords)
                keywords["key"] = lambda value: self.call(callback, value)
        allowed = any(function is getattr(builtins, name) for name in _SAFE_NAMES)
        allowed |= isinstance(function, types.FunctionType) and function.__globals__ is self.namespace
        allowed |= (isinstance(function, type) and issubclass(function, BaseException)
                    and function.__module__ == "builtins")
        receiver = getattr(function, "__self__", None)
        owner = getattr(function, "__objclass__", None)
        allowed |= (isinstance(function, (types.BuiltinFunctionType, types.MethodDescriptorType,
                                         types.WrapperDescriptorType))
                    and (type(receiver) in _METHOD_TYPES or any(receiver is kind or owner is kind
                                                               for kind in _METHOD_TYPES)))
        if not allowed and callable(function):
            self.fail(f"external callable is outside the oracle scope: {type(function).__name__}")
        result = function(*arguments, **keywords)
        if function in (int.as_integer_ratio, float.as_integer_ratio) or (
                getattr(function, "__name__", None) == "as_integer_ratio" and type(receiver) in (int, float)):
            return tuple(self.normal(value) for value in result)
        return self.normal(result)


def execute(source, integer="i64", stdin="", *, filename="<wrapping-reference>"):
    """Run one supported program, returning stdout and its uncaught error type."""
    normalize(0, integer)  # Validate the mode before executing any source.
    tree = ast.parse(source, filename=filename)
    compile(source, filename, "exec", dont_inherit=True)
    _Validate().visit(tree)
    # The official parser NFKC-normalizes identifiers. Inspect every identifier
    # field, including bindings which need not have a corresponding Name node.
    identifiers = set()
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            if field in {"id", "arg", "name", "attr", "asname"} and isinstance(value, str):
                identifiers.add(value)
            elif field == "names" and isinstance(node, (ast.Global, ast.Nonlocal)):
                identifiers.update(value)
    counter = 0
    helper_name = "_wrapping_reference_0"
    while helper_name in source or any(name.startswith(helper_name) for name in identifiers):
        counter += 1
        helper_name = f"_wrapping_reference_{counter}"
    operations = _Operations(integer)
    tree = ast.fix_missing_locations(_Instrument(helper_name).visit(tree))
    code = compile(tree, filename, "exec", dont_inherit=True)
    safe_builtins = {name: getattr(builtins, name) for name in _SAFE_NAMES}
    safe_builtins.update({name: value for name, value in vars(builtins).items()
                          if isinstance(value, type) and issubclass(value, BaseException)})
    environment = {"__builtins__": safe_builtins, "__name__": "__wrapping_program__",
                   helper_name: operations}
    operations.namespace = environment
    output = io.StringIO()
    previous_stdin = sys.stdin
    exception_type = exception_message = None
    try:
        sys.stdin = io.StringIO(stdin)
        with redirect_stdout(output):
            try:
                exec(code, environment)
            except UnsupportedReference:
                raise
            except BaseException as error:
                exception_type = type(error).__name__
                exception_message = str(error)
    finally:
        sys.stdin = previous_stdin
    if operations.unsupported is not None:
        raise UnsupportedReference(operations.unsupported)
    return ReferenceResult(output.getvalue(), exception_type, exception_message)
