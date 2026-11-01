"""Typed value lookup in a live namespace owned by a compiled module."""
import ast


def analyze_item(model,plan,node,owner,index,environment):
    from .native_classes import ClassUnsupported,shape
    if not getattr(shape(owner),'_native_namespace_view',False):return None
    if not(isinstance(node.slice,ast.Constant)and type(node.slice.value)is str):
        raise ClassUnsupported(node.slice,'this live module dictionary lookup needs a statically known text key; arbitrary keys need the complete heterogeneous builtin/module dictionary protocol',proof='typed namespace value alternatives')
    name=node.slice.value
    choices=[]
    result=model.cell(plan,node)
    linker=model.module_linker
    for module in linker.modules.values():
        key=model.unit.global_name(module.name,name)
        if key not in model.namespace.incoming:
            if key in linker.namespace_initial_names(module):
                raise ClassUnsupported(node.slice,f'module dictionary value {name!r} needs an import-spec/builtin namespace object that is not represented by this native module path',proof='implicit namespace value representation')
            continue
        model.namespace.active.add(key)
        value=model.namespace.refresh(key,node)
        kind=shape(value)
        if kind is not None:
            from .native_classes import domain
            from .native_module_linking import ModuleType,ClassReferenceType
            if domain(kind)not in model.DATA and not isinstance(kind,(ModuleType,ClassReferenceType)):
                raise ClassUnsupported(node.slice,'this namespace entry needs a stored value representation beyond its canonical intrinsic adapter',types=(('value',kind),),proof='stored namespace value protocol')
            model.namespace.contribute(result,value,node,force=True)
        choices.append((module.number,key,value))
    if not choices:result=model.cell(plan,node,'none')
    linker.globals_items[(plan.index,id(node))]=(name,tuple(choices))
    return model.remember(plan,node,result)


def emit_item(emitter,node):
    linker=emitter.model.module_linker
    record=linker.globals_items.get((emitter.plan.index,id(node)))
    if record is None:return None
    from .native import _string
    from .native_classes import Expression,shape
    name,choices=record
    before,owner=emitter.capture(emitter.expression(node.value))
    more,index=emitter.capture(emitter.expression(node.slice))
    wanted=emitter.kind(node)
    message=_string('KeyError: '+repr(name))
    error=emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({message}.into())',node)
    arms=[]
    for number,key,cell in choices:
        field=emitter.model.namespace.index(key)
        raw=emitter.at(f'{{let value={owner.code}.0.borrow().value_{field}.clone();value.ok_or_else(||{message}.to_owned())}}',node)
        value=emitter.coerce(Expression(raw,shape(cell)),wanted,node)
        arms.append(f'{number}=>{value}')
    discriminator=emitter.fresh()
    code=(f'{{{before}{more}let {discriminator}={owner.code}.0.borrow().class_module_id;'
          f'match {discriminator}{{'+','.join(arms)+(','if arms else'')+'_=>'+error+'}}')
    return Expression(code,wanted)
