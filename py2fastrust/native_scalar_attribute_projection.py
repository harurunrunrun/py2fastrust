"""Read an ordinary scalar field through a stable local instance slot."""
import ast


def read(emitter,node):
    if(not isinstance(node,ast.Attribute)or not isinstance(node.ctx,ast.Load)
            or not isinstance(node.value,ast.Name)):return None
    if(getattr(emitter,'logical_binding_scope',None)is not None
            or getattr(emitter,'comprehension_bindings',None)):
        return None
    model=emitter.model;root=node.value;unit=model.unit
    if unit is None or model.is_module_plan(emitter.plan):return None
    binding=model.namespace.owners.get(unit.ordinal(root))
    if(binding is None or unit.scopes[binding.owner].kind!='function'
            or binding.owner!=unit.scope_for(emitter.plan.node).ordinal):
        return None
    if model.lexical.field_for(root)is not None or model.namespace.owns(emitter.plan,root):return None
    name=model.resolved_name(emitter.plan,root)
    if name not in emitter.plan.locals:return None
    from .native_classes import InstanceType,Expression,shape
    receiver=emitter.kind(root)
    if type(receiver)is not InstanceType:return None
    stored=model.namespace.local_kind(emitter.plan,name)
    if stored is not None and stored!=receiver:return None
    if(name,receiver)not in emitter.slots:return None
    # The emitter's place accessor may address a movable owned frame field.
    slot=emitter.slot(name,receiver)
    owner=model.classes[receiver.name]
    field=model.resolved_name(emitter.plan,node)
    if field not in owner.fields or field in owner.methods:return None
    if any(name in owner.methods for name in ('__getattribute__','__getattr__')):return None
    registry=getattr(model,'class_namespaces',None)
    if registry is not None:
        if(emitter.plan.index,id(node))in registry.attribute_reads:return None
        if(owner.index,field)in registry.members:return None
    from .native_finite_attributes import selected
    if selected(model,emitter.plan,node):return None
    wanted=emitter.kind(node)
    if wanted not in ('int','bool','float','none')or shape(owner.fields[field].cell)!=wanted:return None
    if wanted=='int'and model.integer=='bigint':return None
    from .native import _string
    message=f"UnboundLocalError: cannot access local variable '{model.display_name(name)}' where it is not associated with a value"
    reference=emitter.fresh()
    from .native_primitive_parameter_places import reference as parameter_reference
    direct=parameter_reference(emitter,root)
    from .native_scalar_data_parameters import read as data_parameter_read
    view=data_parameter_read(emitter,root)
    if view is not None:direct=view.code
    checked=direct if direct is not None else emitter.at(f'{slot}.as_ref().ok_or_else(||{_string(message)}.to_owned())',root)
    index=list(owner.fields).index(field)
    loaded=emitter.at(f'class_get_{owner.index}_{index}({reference})',node)
    code='{let '+reference+'='+checked+';'+loaded+'}'
    # Preserve the existing lazy loop cache and its first-read error timing.
    from .native_class_loop_fields import read as cached
    return Expression(cached(emitter,node,code,wanted),wanted)
