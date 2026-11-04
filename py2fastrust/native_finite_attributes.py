"""Finite plain-instance data attributes with real per-alternative errors."""
from .native_types import alternatives,ListType,SharedListType,TupleType,TupleSequenceType

BUILTIN_TYPES={'none':type(None),'int':int,'bool':bool,'int_bool':int,
               'float':float,'str':str,'bytes':bytes,'list':list,'tuple':tuple,
               'tuple_sequence':tuple,'range':range}


def _owners(model,plan,node,receiver):
    from .native_classes import InstanceType,ClassUnsupported,shape,domain
    from .native_unions import union_kind
    kind=shape(receiver)
    if not union_kind(kind):return None
    choices=alternatives(kind)
    if not any(isinstance(part,InstanceType)for part in choices):return None
    name=model.resolved_name(plan,node)
    if name.startswith('__')and name.endswith('__'):return None
    owners=[]
    for part in choices:
        if isinstance(part,InstanceType):
            owner=model.classes[part.name]
            if name in owner.methods:return None
            registry=getattr(model,'class_namespaces',None)
            if registry is not None and(owner.index,name)in registry.members:return None
            owners.append(owner)
        elif part is None and not model.final:continue
        else:
            if not(isinstance(part,str)or type(part)in{ListType,SharedListType,TupleType,TupleSequenceType}):return None
            builtin=BUILTIN_TYPES.get(domain(part))
            if builtin is None:return None
            if hasattr(builtin,node.attr):
                raise ClassUnsupported(node,f'builtin {builtin.__name__!r} defines attribute {node.attr!r}; lookup across this builtin attribute and instance data needs a typed builtin descriptor/member adapter, which is not implemented',types=(('builtin receiver',part),),proof='builtin attribute lookup within finite data-attribute alternatives')
    return owners


def analyze(model,plan,node,receiver,*,value=None):
    owners=_owners(model,plan,node,receiver)
    if owners is None:return None
    result=model.cell(plan,node)
    for owner in owners:
        field=model.field(owner,model.resolved_name(plan,node),node,writing=value is not None)
        if value is not None:model.contribute(field,value,node)
        if not model.namespace.contribute(result,field,node,force=True):model.contribute(result,field,node)
    if not hasattr(model,'finite_attribute_sites'):model.finite_attribute_sites=set()
    model.finite_attribute_sites.add((plan.index,id(node)))
    return model.remember(plan,node,result)


def selected(model,plan,node):
    return(plan.index,id(node))in getattr(model,'finite_attribute_sites',())


def emit(emitter,node,receiver,wanted,*,value=None):
    from .native_classes import Expression,InstanceType,shape
    from .native_unions import project
    from .native_class_builtins import _type_name
    name=emitter.model.resolved_name(emitter.plan,node)
    def branch(kind,code):
        if isinstance(kind,InstanceType):
            owner=emitter.model.classes[kind.name]
            field=owner.fields[name]
            index=list(owner.fields).index(name)
            if value is None:
                loaded=Expression(emitter.at(f'class_get_{owner.index}_{index}(&({code}))',node),shape(field.cell))
                return emitter.coerce(loaded,wanted,node)
            converted=emitter.coerce(value,shape(field.cell),node)
            from .native_copy_scalar_fields import store
            return '{'+store(emitter.model,owner,code,index,converted)+'()}'
        typename=_type_name(emitter,Expression(code,kind),node)
        suffix=' and no __dict__ for setting new attributes'if value is not None else''
        message='format!("AttributeError: \'{}\' object has no attribute '+repr(node.attr)+suffix+'",'+typename+')'
        return emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({message})',node)
    return Expression(project(receiver.kind,receiver.code,branch),wanted)
