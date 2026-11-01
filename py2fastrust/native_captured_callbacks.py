"""Compile captured callback descriptors without synthesizing source calls."""
import ast
from dataclasses import dataclass
from .native import _Expression,_Unsupported,_Function
from .references import BuiltinIdentity
from .native_module_calls import BuiltinRef


@dataclass(frozen=True)
class CapturedCallback:
    node:object
    identity:object
    inline:object=None


def prepare(generator,node,identity,environment):
    from .native_callbacks import prepare as prepare_lambda
    prepared=prepare_lambda(generator,node,environment)
    if prepared is not None:
        lines,callback=prepared
        return lines,CapturedCallback(node,identity,callback)
    if isinstance(identity,(BuiltinIdentity,_Function))or isinstance(identity,BuiltinRef)and identity.module=='math':
        from .native_module_calls import _read_reference
        _read_reference(generator,node,environment)
        return (),CapturedCallback(node,identity)
    raise _Unsupported('this callback has no proved static captured callable adapter; a runtime callable frame is required',node=node,proof='original-node captured callback identity')


def invoke(generator,callback,value,environment,node):
    if callback.inline is not None:
        from .native_callbacks import invoke as invoke_lambda
        return invoke_lambda(generator,callback.inline,[value],environment,node)
    if isinstance(callback.identity,BuiltinIdentity):
        from .native_builtin_values import unary
        return unary(generator,callback.identity,value,node)
    if isinstance(callback.identity,BuiltinRef)and callback.identity.module=='math':
        from .native_math_calls import emit
        if not value.owned:value=_Expression(generator.coerce(value,value.kind),value.kind)
        return emit(generator,node,callback.identity,[value],{})
    if isinstance(callback.identity,_Function):
        return generator.user_call_values(node,callback.identity,[value],environment,reference_node=callback.node)
    raise _Unsupported('the captured callback descriptor has no matching direct invocation protocol',node=node,proof='captured callback invocation')
