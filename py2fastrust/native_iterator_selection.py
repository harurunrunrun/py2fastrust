"""Prove immediate map consumption without constructing a persistent frame."""
import ast

from .native_builtin_values import UNARY_BUILTINS, unary_capability
from .native_frame_references import _static_builtin_call
from .native_types import ListType, TupleType, TupleSequenceType, DequeType
from .native_key_types import SetType, DictType
from .references import BuiltinIdentity


def _elements(unit, facts, source):
    kind = facts.expressions.get(unit.ordinal(source))
    if isinstance(kind, (ListType, TupleSequenceType, DequeType)):
        return (kind.element,)
    if isinstance(kind, TupleType):
        return kind.fields
    if isinstance(kind, (SetType, DictType)):
        return (kind.key,)
    if kind == "str":
        return ("str",)
    if kind == "bytes":
        return ("int",)
    if isinstance(source, ast.Call):
        call = facts.calls.get(unit.ordinal(source))
        if (call is not None and not call.identity.unknown and not call.identity.unbound
                and call.identity.alternatives == frozenset({BuiltinIdentity("range")})
                and _static_builtin_call(BuiltinIdentity("range"), source)
                and all(facts.expressions.get(unit.ordinal(arg)) in {"int", "bool", "int_bool"}
                        for arg in source.args)):
            return ("int",)
    return None


def immediate_map_unpack(unit, analysis, node, identity):
    """Use the existing scalar adapter only when every reached call proves it."""
    if identity != BuiltinIdentity("map") or not _static_builtin_call(identity, node):
        return False
    seen = False
    for facts in analysis.scopes.values():
        call = facts.calls.get(unit.ordinal(node))
        if call is None:
            continue
        seen = True
        if (call.identity.unknown or call.identity.unbound
                or call.identity.alternatives != frozenset({identity})):
            return False
        callback = facts.values.get(unit.ordinal(node.args[0]))
        if (callback is None or callback.unknown or callback.unbound
                or len(callback.alternatives) != 1):
            return False
        target = next(iter(callback.alternatives))
        if not isinstance(target, BuiltinIdentity) or target.name not in UNARY_BUILTINS:
            return False
        elements = _elements(unit, facts, node.args[1])
        if not elements or not all(unary_capability(target, kind) for kind in elements):
            return False
    return seen
