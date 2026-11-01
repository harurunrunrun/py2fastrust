"""Captured member adapters used by independently scoped compiled modules."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MemberCall:
    result: object
    error: str|None=None


class MathAdapter:
    from .native_math_calls import NAMES

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_math_calls import analyze
        return MemberCall(analyze(model,plan,node,identity,positional,keywords,environment))

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native_math_calls import emit
        return emit(emitter,node,identity,positional,dict(keywords))


class SysAdapter:
    NAMES=frozenset({'exit','setrecursionlimit','getrecursionlimit'})

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_classes import ClassUnsupported,shape
        if identity.name=='exit':
            from .native_exit import analyze,binding_error
            return MemberCall(analyze(model,plan,node,identity,positional,keywords,factory=factory),binding_error(identity,len(positional),keywords))
        count=1 if identity.name=='setrecursionlimit'else 0
        error=None
        if keywords:
            error=f'TypeError: sys.{identity.name}() takes no keyword arguments'
        elif len(positional)!=count:
            error=f'TypeError: sys.{identity.name}() takes exactly {count} arguments ({len(positional)} given)'
        if identity.name=='setrecursionlimit'and error is None:
            from .native_types import alternatives
            kind=shape(positional[0])
            if kind is not None and any(choice not in {'int','int_bool','bool'}for choice in alternatives(kind)):
                raise ClassUnsupported(node,'this recursion limit argument needs the Python integer-index protocol',types=(('argument',kind),),proof='canonical recursion limit integer protocol')
        return MemberCall(factory('none'if count else'int'),error)

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native import _string
        from .native_classes import Expression,shape
        kind=shape(record.result)
        if identity.name=='exit':
            from .native_exit import emit
            return emit(emitter,node,identity,positional,keywords,kind)
        if record.error is not None:
            return Expression(emitter.at(f'Err::<{emitter.rust_type(kind)},String>({_string(record.error)}.into())',node),kind)
        if identity.name=='getrecursionlimit':
            return Expression('class_from_usize(class_scope.control.borrow().limit)','int')
        limit=emitter.at(f'class_recursion_limit(&({emitter.number(positional[0])}))',node)
        temporary=emitter.fresh()
        failure=emitter.at(f'Err::<(),String>(format!("RecursionError: cannot set the recursion limit to {{}} at the recursion depth {{}}: the limit is too low",{temporary},class_scope.control.borrow().depth))',node)
        code=f'{{let {temporary}={limit};if {temporary}<=class_scope.control.borrow().depth{{{failure};}}class_scope.control.borrow_mut().limit={temporary};()}}'
        return Expression(code,'none')
