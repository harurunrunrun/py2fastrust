"""Tuple construction through the shared typed iterator ownership protocol."""
from .native_types import TupleType,TupleSequenceType


def analyze_tuple(model,plan,node,arguments,keywords,environment,factory):
    from .native_classes import Cell,shape,ClassUnsupported
    if len(arguments)>1 or keywords:
        raise ClassUnsupported(node,'tuple construction requires zero or one positional iterable; invalid builtin argument binding has no captured tuple-call adapter yet',proof='tuple constructor signature')
    if not arguments:return factory('tuple',())
    source=arguments[0];kind=shape(source)
    if isinstance(kind,TupleType):return factory('tuple',source.root().args)
    if isinstance(kind,TupleSequenceType):return factory('tuple_sequence',source.root().args)
    iterator=model.iterators.source(plan,node,source)
    item=model.iterators.demand(plan,node,Cell(iterator),environment)
    model.materialized_tuple=True
    result=factory('tuple_sequence',(Cell(),))
    model.contribute(result.root().args[0],item,node)
    return result


def emit_tuple(emitter,node,arguments,wanted):
    from .native_classes import Expression
    if not arguments:return Expression('()',wanted)
    source=arguments[0]
    if isinstance(source.kind,(TupleType,TupleSequenceType)):return emitter.encoded(source.code,source.kind,wanted,node)
    from .native_class_iterators import iterator_kind
    if iterator_kind(source.kind):before,iterator='',source
    else:before,iterator=emitter.capture(emitter.model.iterators.construct(emitter,node,source))
    pulled=emitter.model.iterators.pull(emitter,node,iterator)
    values,item=(emitter.fresh()for _ in range(2))
    converted=emitter.coerce(Expression(item,pulled.kind),wanted.element,node)
    reserve=emitter.at(values+'.try_reserve(1).map_err(|_|"MemoryError: cannot allocate tuple".to_owned())',node)
    code='{'+before+'let mut '+values+'=Vec::<'+emitter.rust_type(wanted.element)+'>::new();loop{let Some('+item+')=('+pulled.code+')else{break;};'+reserve+';'+values+'.push('+converted+');}NativeTuple::from_vec('+values+')}'
    return Expression(code,wanted)
