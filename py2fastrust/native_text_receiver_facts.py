"""Resolve builtin text receiver domains from canonical solved call facts."""
import ast
from .native_types import alternatives


def builtin_text_receiver_kinds(unit,facts,node,identity,*,allowed=frozenset({'str','bytes'})):
    from .native_constraints import MethodValue
    if not isinstance(identity,MethodValue):return frozenset()
    receiver=identity.receiver
    if receiver.unknown or receiver.unbound:return frozenset()
    if receiver.alternatives and receiver.alternatives<=allowed:return receiver.alternatives
    # A projected container/tuple field keeps its symbolic allocation path in
    # MethodValue. Only the solved expression at this exact attribute read can
    # supply its closed builtin domain; an unrelated alias site cannot do so.
    if not(isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)
           and identity.site==unit.ordinal(node.func)):return frozenset()
    kind=facts.expressions.get(unit.ordinal(node.func.value))
    choices=alternatives(kind)if kind is not None else()
    return frozenset(choices)if choices and all(choice in allowed for choice in choices)else frozenset()
