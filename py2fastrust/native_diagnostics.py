"""Explain a failed native operation using existing source and proof metadata.

Diagnostics never lower an expression again, solve constraints again, execute
submitted Python or instantiate a runtime value.
"""
import ast

from .diagnostics import Diagnostic


_OPERATORS = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.MatMult: "@", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**", ast.LShift: "<<",
    ast.RShift: ">>", ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">",
    ast.GtE: ">=", ast.In: "in", ast.NotIn: "not in", ast.Is: "is",
    ast.IsNot: "is not", ast.And: "and", ast.Or: "or", ast.Not: "not",
    ast.UAdd: "+", ast.USub: "-", ast.Invert: "~",
}


def kind_name(kind, _seen=frozenset(), _depth=0):
    """Render Python-facing kinds without leaking Rust slot/type spellings."""
    if kind is None:
        return "unresolved"
    if _depth >= 5 or id(kind) in _seen:
        return "..."
    if isinstance(kind, str):
        return {"none": "None", "int_bool": "int | bool", "list_int": "list[int]",
                "matrix_int": "list[list[int]]", "dict_int": "dict[int, int]",
                "set_int": "set[int]", "deque_int": "collections.deque[int]"}.get(kind, kind)
    seen = _seen | {id(kind)}
    def nested(value):
        return kind_name(value, seen, _depth + 1)
    def fields(values, separator=", "):
        parts = [nested(value) for value in values[:6]]
        if len(values) > 6:
            parts.append("...")
        return separator.join(parts)
    name = type(kind).__name__
    if name == "ListType":
        return "list[" + nested(kind.element) + "]"
    if name == "TupleType":
        return "tuple[" + fields(kind.fields) + "]"
    if name == "DictType":
        return "dict[" + nested(kind.key) + ", " + nested(kind.value) + "]"
    if name == "SetType":
        return "set[" + nested(kind.key) + "]"
    if name == "NullableType":
        return nested(kind.value) + " | None"
    if name == "MaybeType":
        return nested(kind.value) + " (possibly unbound)"
    if name == "UnionType":
        return fields(kind.alternatives, " | ")
    if name == "EmptyType":
        return "unresolved container element"
    if name == "InstanceType":
        return kind.name
    # The class planner still has readonly Cell views alongside canonical kinds.
    # Follow parent pointers without changing its union-find state.
    if name == "Cell":
        root = kind
        visited = set()
        while getattr(root, "parent", None) is not None and id(root) not in visited:
            visited.add(id(root))
            root = root.parent
        tag = getattr(root, "tag", None)
        args = getattr(root, "args", ())
        if tag == "list":
            return "list[" + nested(args[0]) + "]"
        if tag == "tuple":
            return "tuple[" + fields(args) + "]"
        if tag == "union":
            return fields(args, " | ")
        if tag == "object":
            return getattr(getattr(args[0], "node", None), "name", getattr(args[0], "name", "class instance"))
        return kind_name(tag, seen, _depth + 1)
    return "unresolved " + name


def _code(node):
    try:
        text = ast.unparse(node)
        return text if len(text) <= 100 else text[:97] + "..."
    except (ValueError, TypeError, RecursionError):
        return type(node).__name__


def _literal_shape(node):
    """Describe literal structure only; do not infer/evaluate unknown operands."""
    if isinstance(node,ast.Constant):
        return "None"if node.value is None else type(node.value).__name__
    if isinstance(node,(ast.List,ast.Set)):
        label="list"if isinstance(node,ast.List)else"set"
        if not node.elts:return label+"[unresolved element]"
        elements=sorted({_literal_shape(value)for value in node.elts[:8]})
        return label+"["+" | ".join(elements)+"]"
    if isinstance(node,ast.Tuple):
        parts=[_literal_shape(value)for value in node.elts[:6]]
        if len(node.elts)>6:parts.append("...")
        return "tuple["+", ".join(parts)+"]"
    return "unresolved"


def comprehension_context(node):
    if isinstance(node,ast.DictComp):
        key=_literal_shape(node.key);value=_literal_shape(node.value)
        return (("result",f"dict[{key}, {value}]"),("key",key),("value",value))
    element=_literal_shape(node.elt)
    label="list"if isinstance(node,ast.ListComp)else"set"if isinstance(node,ast.SetComp)else"iterator"
    return (("result",f"{label}[{element}]"),("element",element))


def operation_name(node):
    if isinstance(node, ast.Call):
        return "call " + repr(_code(node.func))
    if isinstance(node, ast.Compare):
        return "comparison " + repr(" ".join(_OPERATORS.get(type(op), type(op).__name__) for op in node.ops))
    if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.BoolOp)):
        return "operator " + repr(_OPERATORS.get(type(node.op), type(node.op).__name__))
    if isinstance(node, ast.AugAssign):
        return "augmented assignment " + repr(_OPERATORS.get(type(node.op), type(node.op).__name__) + "=")
    if isinstance(node, ast.Attribute):
        return "attribute " + repr(_code(node))
    if isinstance(node, ast.Subscript):
        return "slice" if isinstance(node.slice, ast.Slice) else "indexed access"
    if isinstance(node, ast.ImportFrom):
        module = "." * node.level + (node.module or "")
        return "import " + repr(module + "." + ", ".join(alias.name for alias in node.names))
    if isinstance(node, ast.Import):
        return "import " + repr(", ".join(alias.name for alias in node.names))
    if isinstance(node, ast.AsyncFunctionDef):
        return "async function definition " + repr(node.name)
    if isinstance(node, ast.FunctionDef):
        return "function definition " + repr(node.name)
    if isinstance(node, ast.ClassDef):
        return "class definition " + repr(node.name)
    if isinstance(node, ast.Name):
        return "name " + repr(node.id)
    if isinstance(node, ast.Constant):
        return type(node.value).__name__ + " literal"
    labels = {
        ast.Assign: "assignment", ast.AnnAssign: "annotated assignment",
        ast.For: "for-loop", ast.While: "while-loop", ast.If: "conditional branch",
        ast.IfExp: "conditional expression", ast.Return: "return", ast.Lambda: "lambda expression",
        ast.Yield: "yield", ast.YieldFrom: "yield from", ast.Try: "exception handler",
        ast.With: "context manager", ast.Global: "global declaration", ast.Nonlocal: "nonlocal declaration",
        ast.Delete: "deletion", ast.Match: "pattern match", ast.Await: "await",
        ast.ListComp: "list comprehension", ast.SetComp: "set comprehension",
        ast.DictComp: "dictionary comprehension", ast.GeneratorExp: "generator expression",
        ast.List: "list allocation", ast.Set: "set allocation", ast.Dict: "dictionary allocation",
        ast.Tuple: "tuple allocation", ast.Raise: "raise", ast.Assert: "assertion",
        ast.NamedExpr: "assignment expression ':='", ast.JoinedStr: "f-string interpolation",
        ast.FormattedValue: "formatted value", ast.Starred: "starred/unpacking expression",
        ast.AsyncFor: "async for-loop", ast.AsyncWith: "async context manager",
        ast.Slice: "slice bounds",
    }
    return next((label for cls, label in labels.items() if isinstance(node, cls)), "program analysis")


def _frames_and_node(error, supplied):
    frames = []
    candidate = supplied
    traceback = getattr(error, "__traceback__", None)
    while traceback is not None:
        local = traceback.tb_frame.f_locals
        frames.append(local)
        value = local.get("node")
        if isinstance(value, ast.AST) and hasattr(value, "lineno"):
            candidate = value
        traceback = traceback.tb_next
    explicit = getattr(error, "node", None)
    if isinstance(explicit, ast.AST) and hasattr(explicit, "lineno"):
        candidate = explicit
    return tuple(reversed(frames)), candidate


def _kind_for(node, frames, unit):
    for frame in frames:
        for key in ("g", "generator", "self"):
            generator = frame.get(key)
            facts = getattr(generator, "constraint_facts", None)
            owner = getattr(generator, "source_unit", None) or unit
            if facts is not None and owner is not None:
                try:
                    site = owner.ordinal(node)
                except KeyError:
                    continue
                kind = facts.expressions.get(site)
                if kind is not None:
                    return kind
                if site in facts.expressions:
                    return None
        if isinstance(node, ast.Name):
            environment = frame.get("environment")
            if isinstance(environment, dict):
                value = environment.get(node.id)
                if value is not None and hasattr(value, "slot"):
                    return getattr(value, "kind", None)
                if type(value).__name__ == "Cell":
                    return value
    if isinstance(node, ast.Constant):
        return "none" if node.value is None else type(node.value).__name__
    return None


def _types(node, frames, unit):
    values = []
    if isinstance(node, ast.Compare):
        values = [("left", node.left)] + [("right" if i == 0 else f"operand {i+2}", item)
                                          for i, item in enumerate(node.comparators)]
    elif isinstance(node, ast.BinOp):
        values = [("left", node.left), ("right", node.right)]
    elif isinstance(node, ast.UnaryOp):
        values = [("operand", node.operand)]
    elif isinstance(node, ast.BoolOp):
        values = [(f"operand {i+1}", item)for i,item in enumerate(node.values)]
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            values.append(("receiver", node.func.value))
        values.extend((f"argument {i+1}", value) for i, value in enumerate(node.args))
    elif isinstance(node, (ast.Attribute, ast.Subscript)):
        values = [("receiver", node.value)]
        if isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice):
            values.append(("index",node.slice))
    elif isinstance(node, ast.Assign):
        values = [("value", node.value)]
    elif isinstance(node, ast.AugAssign):
        values = [("target",node.target),("value",node.value)]
    elif isinstance(node,(ast.If,ast.While,ast.IfExp)):
        values = [("condition",node.test)]
    elif isinstance(node,(ast.For,ast.AsyncFor)):
        values = [("iterable",node.iter)]
    elif isinstance(node,ast.Return)and node.value is not None:
        values = [("value",node.value)]
    if not values:
        return []
    kinds = [(label, _kind_for(value, frames, unit)) for label, value in values[:4]]
    if any(kind is not None for _label, kind in kinds):
        return kinds
    # Some proof failures occur after AST operands have become captured values.
    for frame in frames:
        if frame.get("node") is not node:
            continue
        captured = []
        for label in ("left", "right", "value", "owner", "receiver", "source"):
            value = frame.get(label)
            if not isinstance(value, ast.AST) and hasattr(value, "code") and hasattr(value, "kind"):
                captured.append((label, value.kind))
        if captured:
            return captured[:4]
    return kinds


def _reason(error, node, kinds):
    explicit = getattr(error, "reason", None)
    if explicit:
        return explicit
    from .call_semantics import CallBindingError
    cause = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
    visited=set()
    while cause is not None and id(cause)not in visited and not isinstance(cause,CallBindingError):
        visited.add(id(cause))
        if getattr(cause,"reason",None):return cause.reason
        cause=getattr(cause,"__cause__",None)or getattr(cause,"__context__",None)
    if isinstance(cause, CallBindingError):
        message = str(cause)
        if "expanded" in message or "variadic" in message:
            operation=("positional iterator expansion"if"positional"in message else
                       "keyword mapping expansion"if"keyword"in message else"variadic argument packing")
            return operation + " and binding are not implemented on this native call path; the Python call syntax itself is valid"
        if "default was not captured"in message or"implicit receiver count"in message:
            return "native call-frame capture is incomplete ("+message+"); default/receiver state must be preserved before argument binding"
        return ("the argument binding is invalid (" + message +
                "); emitting the corresponding Python TypeError for this call is not implemented")
    if type(error).__name__ == "ConstraintFailure":
        return str(error)
    if isinstance(error, RecursionError):
        return "static analysis exceeded its recursion budget before a finite native representation was established"
    if isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
        return "native exception-handler routing and unwinding for this block are not implemented"
    if isinstance(node, (ast.Yield, ast.YieldFrom)):
        return "a resumable native generator frame is required; this suspension point is not implemented"
    if isinstance(node, ast.With):
        return "native __enter__/__exit__ protocol dispatch and cleanup routing are not implemented"
    if isinstance(node, ast.Nonlocal):
        return "the enclosing binding needs shared closure-cell storage; this scope transfer is not implemented"
    if isinstance(node, ast.Lambda):
        return "native callable objects and captured lexical cells for this lambda are not implemented"
    if isinstance(node, ast.Match):
        return "native pattern extraction, guard evaluation and binding commits are not implemented for this pattern"
    if isinstance(node,(ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)):
        return "this producer has no compatible native comprehension/stream materialization adapter for its element shape and evaluation context"
    if isinstance(node,ast.NamedExpr):
        return "expression-level binding and evaluation order for ':=' have no native lowering on this path"
    if isinstance(node,(ast.JoinedStr,ast.FormattedValue)):
        return "native formatted-value conversion and format-specifier evaluation are not implemented for this interpolation"
    if isinstance(node,(ast.AsyncFunctionDef,ast.AsyncFor,ast.AsyncWith,ast.Await)):
        return "native coroutine frame/suspension and asynchronous protocol handling are not implemented"
    if isinstance(node,ast.Global):
        return "these declarations require synchronized module-namespace binding state; that global transfer is not implemented on this native function path"
    if isinstance(node,ast.Delete):
        return "native unbinding or container/attribute deletion semantics are not implemented for this target"
    if isinstance(node,ast.Raise):
        return "native Python-exception object construction or re-raising state is not implemented for this raise"
    if isinstance(node,ast.Assert):
        return "native AssertionError construction and conditional exception routing are not implemented for this assertion"
    if isinstance(node, ast.ImportFrom):
        return "the imported names do not have a compatible direct Rust module/member adapter on the selected path"
    if isinstance(node, ast.Import):
        return "the imported module has no compatible direct Rust module adapter on the selected path"
    if isinstance(node, ast.ClassDef):
        if node.bases or node.keywords:
            return "native base-class/metaclass resolution and the resulting instance layout are not implemented for this definition"
        if node.decorator_list:
            return "class-decorator evaluation and native class-object replacement are not implemented"
    if isinstance(node, ast.Name):
        return "the binding's value/type or callable identity cannot be resolved to an available native representation"
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Call):
            return "this invocation calls a value returned by another expression; native callable-object/closure dispatch for that computed callee is not implemented"
        if any(kind is None for _label, kind in kinds):
            return "a compatible callable identity and argument representation could not be proved for this invocation"
        return "the native callable/member adapter has no implementation for this callee with these argument types and binding facts"
    if any(kind is None for _label, kind in kinds):
        return "one or more operand types remain unresolved, so a compatible native operation/storage representation could not be selected"
    return "no direct implementation matches this operation's resolved operand types and required Python protocol/storage semantics"


def direct_diagnostic(source, filename, error=None, node=None, unit=None):
    frames, node = _frames_and_node(error, node)
    if node is None:
        try:
            tree = unit.tree if unit is not None else ast.parse(source, filename=filename)
            node = tree.body[0] if tree.body else None
        except (SyntaxError, ValueError, RecursionError):
            pass
    kinds = getattr(error, "operand_types", ()) or _types(node, frames, unit)
    operation = getattr(error, "operation", None) or operation_name(node)
    reason = _reason(error, node, kinds)
    message = f"Cannot lower {operation}: {reason.rstrip('.')}."
    if kinds:
        message += " Types: " + ", ".join(f"{name}={kind_name(kind)}" for name, kind in kinds) + "."
    proof = getattr(error, "proof", None)
    if proof:
        message += " Required proof: " + proof + "."
    if node is not None:
        segment = ast.get_source_segment(source, node)
        if segment:
            snippet = " ".join(segment.split())
            if len(snippet) > 100:
                snippet = snippet[:97] + "..."
            message += " Source: " + repr(snippet) + "."
    line = getattr(node, "lineno", getattr(error, "lineno", 1) or 1)
    column = (getattr(node, "col_offset", 0) + 1 if node is not None
              else getattr(error, "offset", 1) or 1)
    return Diagnostic(message, filename, line, column, "E006")
