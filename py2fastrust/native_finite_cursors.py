"""Finite alternatives carry existing registered cursor handles directly.

The ordinary native union enum owns the selected Rc handle. It is not another
Python iterator object and must never allocate or reset an underlying cursor.
"""
from .native_types import alternatives


def members(registry,kind):
    parts=alternatives(kind)
    return parts if len(parts)>1 and all(registry.owns(part)for part in parts)else()


def signature(kind):
    from .native_class_iterators import iterator_kind
    return kind.index if iterator_kind(kind)else kind


def item(registry,kind):
    parts=members(registry,kind)
    if not parts:return None
    from .native_classes import Cell
    # Retain the actual producer cells, including mutable allocation origins.
    # No source element cell is widened merely to transport the alternative.
    return Cell('union',tuple(part.record.element for part in parts))


def construct(registry,emitter,node,source,wanted):
    if not members(registry,source.kind):return None
    from .native_classes import Expression,ClassUnsupported
    if wanted is None or wanted==source.kind:return source
    if not(registry.owns(wanted)or members(registry,wanted)):
        raise ClassUnsupported(node,'this existing cursor alternative cannot be reconstructed as a different source-cursor family; a proved identity-preserving cursor ABI is required',types=(('source',source.kind),('target',wanted)),proof='existing cursor-handle alternative transport')
    return Expression(emitter.coerce(source,wanted,node),wanted)


def pull(registry,emitter,node,value,active):
    if not members(registry,value.kind):return None
    from .native_classes import Expression,shape,ClassUnsupported
    from .native_unions import project
    wanted=shape(item(registry,value.kind))
    if wanted is None:
        raise ClassUnsupported(node,'the finite cursor alternatives do not yet have a resolved yielded-value representation',types=(('iterator',value.kind),),proof='resolved finite cursor element ABI')
    def branch(kind,code):
        # The containing enum is captured by the ordinary pull boundary. Its
        # existing Rc payload therefore outlives every provider loan here.
        # Borrow it directly rather than borrowing a temporary Rc clone.
        pulled=registry._pull(emitter,node,Expression('('+code+')',kind),active)
        current=emitter.fresh()
        converted=emitter.coerce(Expression(current,pulled.kind),wanted,node)
        return '('+pulled.code+').map(|'+current+'|'+converted+')'
    return Expression(project(value.kind,value.code,branch),wanted)


def mark_emitted(registry,kind):
    for part in members(registry,kind)or(kind,):
        if registry.owns(part):part.record.emitted=True
