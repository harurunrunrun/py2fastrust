"""Captured member adapters used by independently scoped compiled modules."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MemberCall:
    result: object
    error: str|None=None


class MathAdapter:
    from .native_math_exports import FUNCTION_NAMES as NAMES

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_math_calls import analyze, NAMES as implemented
        if identity.name=='prod':return _analyze_prod(model,plan,node,positional,keywords,environment,factory)
        if identity.name not in implemented:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'math.'+identity.name+' is a canonical exported function, but its native operation and argument protocol are not implemented',
                                   proof='native implementation of math.'+identity.name)
        return MemberCall(analyze(model,plan,node,identity,positional,keywords,environment,factory=factory))

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        if identity.name=='prod':return _emit_prod(emitter,node,record,positional,dict(keywords))
        from .native_math_calls import emit
        return emit(emitter,node,identity,positional,dict(keywords))


@dataclass(frozen=True)
class ProdCall:
    result: object
    iterator: object
    error: str|None=None


def _analyze_prod(model,plan,node,positional,keywords,environment,factory):
    """math.prod(iterable, *, start=1): result = start; result *= item for each item.

    Integer and boolean items and starts multiply exactly in the selected
    integer mode; an empty iterable returns start. Float operands make the
    result type depend on emptiness and stay a positioned diagnostic."""
    from .native_classes import Cell,ClassUnsupported,shape
    from .native_types import alternatives
    names=[name for name,_ in keywords]
    if len(positional)!=1 or any(name!='start'for name in names):
        raise ClassUnsupported(node,'this math.prod binding is not implemented; one iterable and an optional start keyword are',proof='math.prod argument binding')
    iterator=model.iterators.source(plan,node,positional[0],('math_prod',),environment=environment)
    item=model.iterators.demand(plan,node,Cell(iterator),environment)
    start=dict(keywords).get('start',Cell('int'))
    for value in(item,start):
        kinds=alternatives(shape(value))
        if model.final and kinds and not all(kind in {'int','bool','int_bool'}for kind in kinds if kind is not None):
            from .native_types import EmptyType
            if not isinstance(shape(value),EmptyType):
                raise ClassUnsupported(node,'math.prod over these values needs the generic __mul__ protocol; integer and boolean items and starts are implemented',types=(('value',shape(value)),),proof='math.prod multiplication protocol')
    return ProdCall(factory('int'),iterator)


def _emit_prod(emitter,node,record,positional,keywords):
    import ast
    from .native_classes import Expression
    from .native_types import EmptyType
    total,member=emitter.fresh(),emitter.fresh()
    start=keywords.get('start',Expression(emitter.literal(1),'int',1))
    code='let mut '+total+'='+emitter.coerce(start,'int',node)+';'
    before,cursor=emitter.capture(emitter.model.iterators.construct(emitter,node,positional[0],kind=record.iterator))
    code+=before
    pulled=emitter.model.iterators.pull(emitter,node,cursor)
    if isinstance(pulled.kind,EmptyType):action='match '+member+'{}'
    else:
        product=emitter.numeric.binary(ast.Mult(),emitter.scalar(Expression(total+'.clone()','int')),emitter.scalar(Expression(member,pulled.kind)),node)
        action=total+'='+emitter.coerce(product,'int',node)+';'
    code+='loop{let Some('+member+')=('+pulled.code+')else{break;};'+action+'}'
    return Expression('{'+code+total+'}','int')


class SysAdapter:
    NAMES=frozenset({'exit','setrecursionlimit','getrecursionlimit',
                     'set_int_max_str_digits','get_int_max_str_digits'})

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_classes import ClassUnsupported,shape
        from .native_integer_digit_limits import NAMES,analyze
        if identity.name in NAMES:
            return analyze(model,plan,node,identity,positional,keywords,factory=factory)
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
        from .native_integer_digit_limits import NAMES,emit
        if identity.name in NAMES:
            return emit(emitter,node,identity,record,positional,keywords)
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
