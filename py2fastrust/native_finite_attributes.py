"""Finite plain-instance data attributes with real per-alternative errors."""
from .native_types import alternatives,ListType,SharedListType,TupleType,TupleSequenceType

BUILTIN_TYPES={'none':type(None),'int':int,'bool':bool,'int_bool':int,
               'float':float,'str':str,'bytes':bytes,'list':list,'tuple':tuple,
               'tuple_sequence':tuple,'range':range}


def missing_builtin(kind,name):
    """Prove absence only on closed builtin receivers, never source classes."""
    from .native_classes import domain
    if name.startswith('__')and name.endswith('__'):return False
    choices=alternatives(kind)
    if not choices:return False
    for part in choices:
        if not(isinstance(part,str)or type(part)in{ListType,SharedListType,TupleType,TupleSequenceType}):return False
        builtin=BUILTIN_TYPES.get(domain(part))
        if builtin is None or hasattr(builtin,name):return False
    return True


def requires_frames(unit,analysis):
    import ast
    for node in ast.walk(unit.tree):
        if not isinstance(node,(ast.Attribute,ast.Call)):continue
        receiver=node.value if isinstance(node,ast.Attribute)else node.func
        for facts in analysis.scopes.values():
            kind=facts.expressions.get(unit.ordinal(receiver))
            if kind is None:continue
            if isinstance(node,ast.Attribute):
                if missing_builtin(kind,node.attr):return True
            else:
                from .native_classes import domain
                choices=alternatives(kind)
                if choices and all((isinstance(part,str)or type(part)in{ListType,SharedListType,TupleType,TupleSequenceType})
                                   and domain(part)in BUILTIN_TYPES for part in choices):return True
    return False


def _owners(model,plan,node,receiver):
    from .native_classes import InstanceType,ClassUnsupported,shape,domain
    from .native_unions import union_kind
    kind=shape(receiver)
    if kind is None:return None
    if isinstance(kind,InstanceType):return None
    choices=alternatives(kind)
    instances=any(isinstance(part,InstanceType)for part in choices)
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
                if not instances:return None
                raise ClassUnsupported(node,f'builtin {builtin.__name__!r} defines attribute {node.attr!r}; lookup across this builtin attribute and instance data needs a typed builtin descriptor/member adapter, which is not implemented',types=(('builtin receiver',part),),proof='builtin attribute lookup within finite data-attribute alternatives')
    return owners


def analyze(model,plan,node,receiver,*,value=None):
    owners=_owners(model,plan,node,receiver)
    if owners is None:return None
    result=model.cell(plan,node)
    if not owners:
        from .native_types import EMPTY
        model.contribute(result,model.cell_for_kind(EMPTY),node)
    for owner in owners:
        field=model.field(owner,model.resolved_name(plan,node),node,writing=value is not None)
        if value is not None:model.contribute(field,value,node)
        if not model.namespace.contribute(result,field,node,force=True):model.contribute(result,field,node)
    if not hasattr(model,'finite_attribute_sites'):model.finite_attribute_sites=set()
    model.finite_attribute_sites.add((plan.index,id(node)))
    return model.remember(plan,node,result)


def selected(model,plan,node):
    if(plan.index,id(node))not in getattr(model,'finite_attribute_sites',()):return False
    receiver=model.records.get((plan.index,id(node.value)))
    return receiver is not None and _owners(model,plan,node,receiver)is not None


def emit(emitter,node,receiver,wanted,*,value=None):
    from .native_classes import Expression,InstanceType,shape
    from .native_unions import project
    from .native_class_builtins import _type_name
    name=emitter.model.resolved_name(emitter.plan,node)
    attribute=emitter.model.display_name(name)
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
        message='format!("AttributeError: \'{}\' object has no attribute '+repr(attribute)+suffix+'",'+typename+')'
        return emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({message})',node)
    return Expression(project(receiver.kind,receiver.code,branch),wanted)
