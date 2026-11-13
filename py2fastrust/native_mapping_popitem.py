"""Canonical typed dictionary popitem with captured owners and closed borrows."""
from .native_types import EMPTY,TupleType,alternatives


def binding_error(count,keywords):
    # The inherited C method reports its defining dict type for all flavors.
    if keywords:return 'TypeError: dict.popitem() takes no keyword arguments'
    if count:return f'TypeError: dict.popitem() takes no arguments ({count} given)'
    return None


def require_origin(model,node,choices):
    if not model.final:return
    from .native_dictionary_positions import proved
    from .native_classes import ClassUnsupported
    if not all(proved(kind,model)for kind in choices):
        raise ClassUnsupported(node,'dict.popitem requires the actual constructor/copy origin to preserve builtin mapping contents and insertion order; this custom or dynamic mapping origin is not implemented',proof='canonical dictionary constructor and insertion-order origin')


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import Cell,shape
    from .native_class_mappings import mapping_kind
    sites=getattr(model,'mapping_popitem_calls',None)
    if sites is not None:sites.pop((plan.index,id(node)),None)
    if node.func.attr!='popitem':return None
    choices=alternatives(shape(receiver))
    if not choices or not all(mapping_kind(kind)and kind.record.category=='dict'for kind in choices):return None
    require_origin(model,node,choices)
    if sites is None:sites=model.mapping_popitem_calls={}
    error=binding_error(len(arguments),keywords);sites[(plan.index,id(node))]=(receiver,error)
    if error:return model.cell(plan,node,EMPTY)
    result=model.cell(plan,node)
    for kind in choices:
        value=Cell('tuple',(kind.record.key,kind.record.value))
        if not model.namespace.contribute(result,value,node,force=True):model.contribute(result,value,node)
    return result


def remove(emitter,node,owner,wanted):
    from .native_classes import Expression,shape
    from .native_class_mappings import canonical
    from .native_unions import project
    emitter.model.mapping_popitem_emitted=True
    setup,owner=emitter.capture(owner)
    def branch(kind,code):
        record=kind.record;read,key=(emitter.fresh()for _ in range(2))
        hashed=canonical(emitter,Expression('(*'+key+').clone()',shape(record.key)))
        call='native_dict_popitem(&mut '+read+'.entries,&mut '+read+'.index,|'+key+'|'+hashed+')'
        value=Expression(emitter.at(call,node),TupleType((shape(record.key),shape(record.value))))
        return '{let mut '+read+'=('+code+').borrow_mut();let '+read+'=&mut *'+read+';'+emitter.coerce(value,wanted,node)+'}'
    return Expression('{'+setup+project(owner.kind,owner.code,branch)+'}',wanted)


def emit(emitter,node):
    from .call_semantics import normalize_call
    site=getattr(emitter.model,'mapping_popitem_calls',{}).get((emitter.plan.index,id(node)))
    if site is None:return None
    setup,owner=emitter.capture(emitter.expression(node.func.value))
    for argument in normalize_call(node).evaluation_order:
        before,_=emitter.capture(emitter.expression(argument.expression));setup+=before
    wanted=emitter.kind(node)
    if site[1]:
        from .native_class_builtins import _error
        from .native import _string
        value=_error(emitter,node,wanted,_string(site[1])+'.to_owned()')
    else:value=remove(emitter,node,owner,wanted)
    from .native_classes import Expression
    return Expression('{'+setup+value.code+'}',wanted)


def runtime(model):
    if not getattr(model,'mapping_popitem_emitted',False):return ''
    from .native_ordered_entries import POPITEM_HELPER
    return POPITEM_HELPER
