"""Original source __reversed__ calls return their actual values unchanged."""


def sites(model):
    if not hasattr(model,'source_reversal_sites'):model.source_reversal_sites={}
    return model.source_reversal_sites


def analyze(model,plan,node,value,environment):
    from .native_classes import shape,InstanceType
    from .native_source_lengths import member,analyze_slot
    kind=shape(value)
    if not isinstance(kind,InstanceType):return None
    selected=member(model,kind,('__reversed__',),node)
    if selected is None:return None
    site=analyze_slot(model,plan,node,value,environment,'__reversed__',identity='reversed')
    sites(model)[plan.index,id(node),kind]=site
    # Unlike __iter__, Python does not require this result to be an iterator.
    # Consumers decide whether a returned list/None/object can be iterated.
    return site.callback.result


def emit(emitter,node,value,wanted):
    from .native_classes import Expression,InstanceType,ClassUnsupported
    from .native_source_lengths import member,emit_slot
    if not isinstance(value.kind,InstanceType):return None
    selected=member(emitter.model,value.kind,('__reversed__',),node)
    if selected is None:return None
    site=sites(emitter.model).get((emitter.plan.index,id(node),value.kind))
    if site is None:
        raise ClassUnsupported(node,'source __reversed__ has no matching original callback/effect boundary',proof='source reverse callback lookup and argument order')
    before,result=emit_slot(emitter,node,value,site)
    return Expression('{'+before+emitter.coerce(result,wanted,node)+'}',wanted)
