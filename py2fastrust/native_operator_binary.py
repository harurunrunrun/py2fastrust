"""Canonical nonmutating operator callables share original typed operations."""
import ast
from dataclasses import dataclass

OPERATIONS={'add':ast.Add,'sub':ast.Sub,'mul':ast.Mult,'and_':ast.BitAnd,'or_':ast.BitOr,
            'xor':ast.BitXor,'lshift':ast.LShift,'rshift':ast.RShift,
            'floordiv':ast.FloorDiv,'mod':ast.Mod,'truediv':ast.Div}


@dataclass
class OperatorCall:
    result:object
    error:str|None=None


class OperatorAdapter:
    NAMES=frozenset(OPERATIONS)
    TYPES=frozenset()

    @staticmethod
    def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
        error=None
        if keywords:error=f'TypeError: _operator.{identity.name}() takes no keyword arguments'
        elif len(positional)!=2:error=f'TypeError: {identity.name} expected 2 arguments, got {len(positional)}'
        if error:return OperatorCall(factory('none'),error)
        return OperatorCall(model.binary(plan,node,OPERATIONS[identity.name](),*positional,identity=('operator',identity),environment=environment))

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native import _string
        from .native_classes import Expression,shape
        wanted=shape(record.result)
        if record.error is not None:return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(record.error)+'.to_owned())',node),wanted)
        return emitter.binary(OPERATIONS[identity.name](),*positional,node,wanted,identity=('operator',identity))
