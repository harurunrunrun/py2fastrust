"""Non-escaping typed lambda calls for eager native consumers.

The original lambda body is lowered in its own lexical argument environment.
Defaults are evaluated once at creation; free bindings are read at invocation.
No submitted Python is executed and no source AST is synthesized.
"""
import ast
from dataclasses import dataclass

from .call_semantics import CallBindingError, FunctionSignature, normalize_call
from .native import _Binding, _Expression, _Unsupported
from .native_types import immutable, rust_type


@dataclass(frozen=True)
class InlineLambda:
    node: ast.Lambda
    signature: FunctionSignature
    defaults: tuple[tuple[str, _Expression], ...]


def prepare(g, node, environment):
    if not isinstance(node, ast.Lambda):
        return None
    unit = getattr(g, "source_unit", None)
    signature = (unit.signature_for(node) if unit is not None
                 else FunctionSignature.from_ast(node))
    if signature.variadic_positional or signature.variadic_keyword:
        raise _Unsupported(
            "this lambda signature requires variadic tuple/dictionary packing; "
            "the shared native callback call frame has not implemented that packing",
            node=node, operation="lambda callback signature")
    lines, defaults = [], []
    for slot in signature.defaults:
        value = g.expression(slot.expression, environment)
        if not immutable(value.kind):
            raise _Unsupported(
                f"lambda default {slot.name!r} needs one shared mutable object across "
                "callback invocations; that default-cell storage is not implemented",
                node=slot.expression, types=(("default", value.kind),),
                proof="shared definition-time callback default identity")
        name = g.temporary()
        code = value.code if value.owned else g.coerce(value, value.kind)
        lines.append(f"let {name}:{rust_type(value.kind)}={code};")
        defaults.append((slot.name, _Expression(name, value.kind, owned=False)))
    return tuple(lines), InlineLambda(node, signature, tuple(defaults))


def _observed_owners(g, callback, call_node, forbidden):
    unit = getattr(g, "source_unit", None)
    if unit is not None and isinstance(call_node, ast.Call) and isinstance(call_node.func, ast.Attribute):
        by_node = {binding.node: binding for binding in unit.bindings}
        owners = set()
        for node in ast.walk(call_node.func.value):
            if isinstance(node, ast.Name) and node.id in forbidden:
                binding = by_node.get(unit.ordinal(node))
                if binding is not None:owners.add((binding.name, binding.owner))
        observed = set()
        for node in ast.walk(callback.node.body):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                binding = by_node.get(unit.ordinal(node))
                if binding is not None and (binding.name, binding.owner) in owners:
                    observed.add(binding.name)
        return observed
    reads = {node.id for node in ast.walk(callback.node.body)
             if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    return (reads - set(callback.signature.local_names)) & forbidden


def invoke(g, callback, arguments, environment, call_node, *, forbidden_owners=(), bound=None):
    """Bind captured descriptors once, then emit one ordinary Rust expression."""
    try:
        if bound is None:
            bound = callback.signature.bind(arguments, defaults=dict(callback.defaults))
    except CallBindingError as error:
        raise _Unsupported(
            "binding this callback invocation requires Python TypeError emission "
            f"for its lambda signature ({error}); that invalid-call path is not implemented",
            node=callback.node, operation="lambda callback argument binding") from error
    forbidden = set(forbidden_owners)
    if forbidden:
        observed = _observed_owners(g, callback, call_node, forbidden)
        if observed:
            raise _Unsupported(
                "this key callback observes the list currently being sorted; native "
                "temporary-empty storage and exception-safe restoration for that "
                "callback observation are not implemented",
                node=callback.node.body, operation="list.sort key callback",
                proof="Python sorting-list visibility and restoration")
    lines, inside = [], environment.copy()
    for parameter, value in zip(bound.parameters, bound.values):
        if not immutable(value.kind):
            raise _Unsupported(
                "a mutable callback argument needs shared identity-preserving "
                "argument storage; this inline native callback only accepts "
                "immutable values",
                node=callback.node, types=((parameter, value.kind),),
                proof="callback argument identity")
        name = g.temporary()
        code = value.code if value.owned else g.coerce(value, value.kind)
        lines.append(f"let {name}:{rust_type(value.kind)}={code};")
        inside[parameter] = _Binding(name, value.kind)
    trace = g.temporary()
    scope, line = g.scope_code(), g.line_code(call_node)
    previous_trace = g.expression_trace_id
    previous_globals = getattr(g, "inline_callback_globals", None)
    if previous_globals is None:
        globals_at_call = (environment if g.function is None else g.global_environment)
        names = (set(environment) if g.function is None else g.global_names)
        g.inline_callback_globals = (globals_at_call, names)
    checkpoint = len(g.expression_mutations)
    from .native_iterators import _scope
    try:
        with _scope(g, "<lambda>", trace):
            value = g.expression(callback.node.body, inside)
    finally:
        g.inline_callback_globals = previous_globals
    from .native_expression_flow import _widen
    _widen(g, environment, {binding.slot for binding in g.expression_mutations[checkpoint:]})
    if not value.owned:
        if not immutable(value.kind):
            raise _Unsupported(
                "returning a borrowed mutable object from this lambda requires "
                "an alias-preserving native callback result carrier; that result "
                "storage is not implemented",
                node=callback.node.body, types=(("result", value.kind),),
                proof="escaping callback result identity")
        value = _Expression(g.coerce(value, value.kind), value.kind,
                            constant=value.constant)
    if trace in value.code:
        g.has_callback_frames = True
        propagated = f"{previous_trace}(error)" if previous_trace is not None else "error"
        lines.append(f"let {trace}=|mut error:NativeError|{{error.frames.push(({line},{scope}));{propagated}}};")
    return _Expression("{" + "".join(lines) + value.code + "}", value.kind,
                       constant=value.constant, owned=value.owned)


def try_expression(g, node, environment):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Lambda)):
        return None
    setup, callback = prepare(g, node.func, environment)
    lines = list(setup)
    try:
        plan = callback.signature.plan(normalize_call(node))
        def argument(expression, parameter):
            value = g.expression(expression, environment)
            if not immutable(value.kind):
                raise _Unsupported(
                    "an immediate lambda's mutable argument needs a shared "
                    "alias-preserving callback frame; that argument adapter "
                    "is not implemented",
                    node=expression, types=((parameter, value.kind),),
                    proof="mutable callback argument identity")
            name = g.temporary()
            code = value.code if value.owned else g.coerce(value, value.kind)
            lines.append(f"let {name}:{rust_type(value.kind)}={code};")
            return _Expression(name, value.kind, owned=False)
        bound = plan.capture(argument, defaults=dict(callback.defaults))
    except CallBindingError as error:
        raise _Unsupported(
            f"binding this immediate lambda call requires unsupported argument "
            f"expansion or Python TypeError emission ({error})",
            node=node, operation="immediate lambda call binding") from error
    value = invoke(g, callback, (), environment, node, bound=bound)
    return _Expression("{" + "".join(lines) + value.code + "}", value.kind,
                       constant=value.constant, owned=value.owned)
