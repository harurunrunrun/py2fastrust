"""Immediate typed next() consumers; iterator state remains ordinary Rust."""

import ast

from .native import _Expression, _Unsupported
from .native_types import TupleType, immutable, join_types, rust_type, tuple_code


def try_expression(g,node,environment):
    if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id == "next"):
        return None
    if not 1 <= len(node.args) <= 2 or node.keywords or any(isinstance(argument,ast.Starred) for argument in node.args):
        raise _Unsupported
    from .native_iterators import Planner, TraceContext, _owned, stream_item
    source = Planner(g).stream(node.args[0],environment)
    if not source.eager:
        # Containers and range are iterable but have no next method. Their
        # explicit iter(...) adapters are supported separately by the planner.
        raise _Unsupported
    output = stream_item(g,source)
    kind = output.kind
    if not immutable(kind):
        raise _Unsupported
    lines = [source.construct()]
    default = None
    if len(node.args) == 2:
        depth = len(g.iterating_lists)
        g.iterating_lists.extend(source.owners)
        try:
            default = g.expression(node.args[1],environment)
        finally:
            del g.iterating_lists[depth:]
        kind = default.kind if source.length == 0 else join_types(kind,default.kind)
        if kind is None or not immutable(kind):
            raise _Unsupported
        name = g.temporary()
        lines.append(f"let {name}={g.coerce(default,kind)};")
        default = name
    g.register_type(kind)
    action = ("unreachable!(\"proved empty iterator yielded\");" if source.length == 0 else
              f"return Ok(Some({_owned(g,output,kind)}));")
    body = source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
    result = g.temporary()
    lines.append(f"let {result}=(|| -> Result<Option<{rust_type(kind)}>,NativeError>{{\n{body}\nOk(None)\n}})()?;")
    if default is not None:
        final = f"{result}.unwrap_or({default})"
    else:
        final = g.at(f'{result}.ok_or_else(||String::from("StopIteration"))',node)
    return _Expression("{\n" + "\n".join(lines) + "\n" + final + "\n}",kind)
