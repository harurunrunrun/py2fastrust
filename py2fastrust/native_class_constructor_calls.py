"""Invoke captured source class references through their real initializer ABI."""
from dataclasses import dataclass


@dataclass
class ConstructorSite:
    owner: object
    result: object
    error: str|None=None


def analyze(provider,plan,node,kind,arguments,positional,keywords,environment,*,identity=None):
    from .native_classes import Cell,ClassUnsupported,shape
    from .native_aot_callables import binding_error
    from .call_semantics import CallBindingError
    from .native_types import EMPTY,EmptyType,alternatives
    model=provider.model
    owner=next(owner for owner in model.classes.values()if owner.index==kind.definition)
    if model.class_namespaces.named_tuples.records.get(owner.index)is not None:
        raise ClassUnsupported(node,'captured NamedTuple factories require their nominal tuple constructor ABI; this source-class callback adapter only implements ordinary instance allocation',proof='captured nominal tuple construction')
    constructor=owner.methods.get('__init__')
    failure=None
    if constructor is not None:
        try:constructor.signature.plan(arguments,implicit_count=1,allow_variadic=True)
        except CallBindingError as error:failure=binding_error(constructor,arguments,error,implicit_count=1)
    elif positional or keywords:
        failure=f'TypeError: {owner.node.name}() takes no arguments'
    if failure:return ConstructorSite(owner,Cell(EMPTY),failure)
    owner.used=True
    result=model.cell(plan,node,'object',(model.class_key(owner),),identity=('captured_constructor',owner.index,identity))
    if constructor is not None:
        model.bind_captured(plan,node,constructor,[result]+positional,keywords,environment)
        if model.final and any(part!='none'and not isinstance(part,EmptyType)for part in alternatives(shape(constructor.result))):
            raise ClassUnsupported(node,'this __init__ can return a non-None value; a captured constructor must validate that return and raise Python TypeError, which this constructor ABI does not yet implement',proof='initializer return-value validation')
    return ConstructorSite(owner,result)



def analyze_invalid_direct(model,plan,node,owner,reference,arguments,positional,keywords,environment):
    """Invalid direct bindings still evaluate each captured explicit operand."""
    from .call_semantics import CallBindingError
    constructor=owner.methods.get('__init__')
    if constructor is None:
        invalid=bool(positional or keywords)
    else:
        try:constructor.signature.plan(arguments,implicit_count=1,allow_variadic=True)
        except CallBindingError:invalid=True
        else:invalid=False
    if not invalid:return None
    from .native_aot_callables import analyze_values
    site=analyze_values(model.callable_cells,plan,node,reference,arguments,positional,keywords,environment)
    model.callable_cells.sites[(plan.index,id(node))]=site
    model.module_linker.class_calls.pop((plan.index,id(node)),None)
    return model.remember(plan,node,site.result)


def emit(emitter,node,site,reference,positional,keywords,wanted,*,source_call_location=None,defining_context=None):
    from .native import _string
    from .native_classes import Expression,shape,ClassUnsupported,InstanceType
    from .call_semantics import CallBindingError
    owner=site.owner
    if site.error:
        return emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(site.error)+'.to_owned())',node)
    constructor=owner.methods.get('__init__')
    values=[]
    if constructor is not None:
        default_emitter=emitter.model.emitter(constructor)
        from .native_variadic import pack_emission
        try:
            bound=constructor.signature.without_receiver().bind(positional,keywords,default_emitter.captured_defaults(constructor),pack_positional=lambda members:pack_emission(emitter,constructor,members,node))
        except CallBindingError as error:raise ClassUnsupported(node,str(error))from None
        values=[emitter.coerce(value,shape(constructor.arguments[name]),node)for name,value in zip(bound.parameters,bound.values)]
    from .native_class_identity_demand import token as identity_token
    from .native_source_state import call_arguments
    state_values=call_arguments(emitter,node,constructor)if constructor is not None else None
    from .native_class_value_demands import marker_constructor
    prefix=([] if state_values is not None and marker_constructor(emitter.model,owner)
            else emitter.constructor_context_arguments(owner,reference.code if defining_context is None else defining_context))
    identity_setup=''
    if identity_token(emitter.model,owner):
        identity=emitter.fresh()
        identity_setup=f'let {identity}='+emitter.at('class_value_next_id()',source_call_location or node)+';'
        prefix.append(identity)
    values=prefix+values
    name='class_construct_'+str(owner.index)
    if state_values is not None:
        name='class_state_construct_'+str(owner.index)
        values.extend(state_values)
    from .native_scalar_data_results import constructor_name
    name=constructor_name(emitter,node,owner,name)
    invocation=name+'(class_scope.clone()'+(','+','.join(values)if values else'')+')'
    from .native_class_calls import call
    invocation=call(emitter,invocation,constructor,source_call_location or node)
    context=(''if defining_context is not None else
             emitter.prepare_call_context(constructor,None,owner,reference.code+'.module.clone()',node=node))
    return emitter.coerce(Expression('{'+identity_setup+context+invocation+'}',InstanceType(emitter.model.class_key(owner))),wanted,node)
