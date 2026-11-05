"""Project a stable builtin tuple local without cloning unrelated fields."""
import ast

from .native_types import TupleType,NamedTupleType


def read(emitter,node):
    if not isinstance(node,ast.Subscript):return None
    if(getattr(emitter,'logical_binding_scope',None)is not None
            or getattr(emitter,'comprehension_bindings',None)):
        return None
    chain=[];root=node
    while isinstance(root,ast.Subscript):
        if not isinstance(root.slice,ast.Constant)or type(root.slice.value)is not int:return None
        chain.append(root)
        root=root.value
    if not isinstance(root,ast.Name):return None
    model=emitter.model;unit=model.unit
    if unit is None or model.is_module_plan(emitter.plan):return None
    binding=model.namespace.owners.get(unit.ordinal(root))
    if(binding is None or unit.scopes[binding.owner].kind!='function'
            or binding.owner!=unit.scope_for(emitter.plan.node).ordinal):
        return None
    if model.lexical.field_for(root)is not None or model.namespace.owns(emitter.plan,root):return None
    name=model.resolved_name(emitter.plan,root)
    if name not in emitter.plan.locals:return None
    kind=emitter.kind(root)
    if type(kind)is not TupleType:return None
    stored=model.namespace.local_kind(emitter.plan,name)
    if stored is not None and stored!=kind:return None
    slot=emitter.slots.get((name,kind))
    if slot is None:return None
    path=[];current=kind
    for step in reversed(chain):
        if type(current)is not TupleType:return None
        offset=step.slice.value
        if not -len(current.fields)<=offset<len(current.fields):return None
        offset%=len(current.fields)
        current=current.fields[offset]
        if current!=emitter.kind(step)or isinstance(current,NamedTupleType):return None
        path.append(str(offset))
    from .native import _string
    from .native_classes import Expression
    message=f"UnboundLocalError: cannot access local variable '{model.display_name(name)}' where it is not associated with a value"
    reference=emitter.fresh()
    from .native_primitive_parameter_places import reference as parameter_reference
    direct=parameter_reference(emitter,root)
    checked=direct if direct is not None else emitter.at(f'{slot}.as_ref().ok_or_else(||{_string(message)}.to_owned())',root)
    # This short block returns an owned selected leaf; no borrow survives into
    # another argument, callback, or binding replacement.
    return Expression('{let '+reference+'='+checked+';('+reference+'.'+'.'.join(path)+').clone()}',current)
