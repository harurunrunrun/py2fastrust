"""Typed sequence methods through canonical method and ordered operand plans."""
from .native import _Binding, _Expression, _Unsupported
from .native_types import EmptyType, list_type, is_maybe


HELPERS=r'''
fn native_sequence_bound(length:usize,bound:i128)->usize {
    if bound<0 {bound.saturating_add(length as i128).max(0) as usize}
    else {bound.min(length as i128) as usize}
}
fn native_sequence_index<T,F:FnMut(&T)->bool>(values:&[T],start:i128,stop:Option<i128>,mut equal:F)->Result<usize,String> {
    let start=native_sequence_bound(values.len(),start);
    let stop=stop.map_or(values.len(),|stop|native_sequence_bound(values.len(),stop));
    for index in start..stop {if equal(&values[index]) {return Ok(index);}}
    Err("ValueError: list.index(x): x not in list".into())
}
fn native_sequence_count<T,F:FnMut(&T)->bool>(values:&[T],mut equal:F)->usize {
    values.iter().filter(|item|equal(item)).count()
}
fn native_sequence_pop<T>(values:&mut Vec<T>,index:i128)->Result<T,String> {
    let index=isize::try_from(index).map_err(|_|"OverflowError: Python int too large to convert to C ssize_t".to_owned())? as i128;
    if values.is_empty(){return Err("IndexError: pop from empty list".into());}
    let index=if index<0 {index+values.len() as i128}else{index};
    let index=usize::try_from(index).ok().filter(|index|*index<values.len())
        .ok_or_else(||"IndexError: pop index out of range".to_owned())?;
    Ok(values.remove(index))
}
'''


def _supported(kind):
    from .native_tuples import _scalar
    return isinstance(kind,EmptyType) or _scalar(kind)


def try_expression(g,node,environment):
    from .native_stream_plans import context
    from .call_semantics import CallBindingError
    from .native_sequence_plans import sequence_method
    from .native_sequence_storage import capture_owned
    from .native_sequence_methods import lower
    try:plan=context(g,environment).method(node)
    except CallBindingError as error:raise _Unsupported from error
    if plan is None:return None
    receiver=plan.receiver.captured
    method=sequence_method(receiver.kind,plan.identity.name)
    if method is None:return None
    g.has_lists=g.has_typed_lists=True
    g.register_type(receiver.kind)
    storage=capture_owned(g,receiver,plan.receiver.expression,environment,mutates=method.mutates)
    lines=list(storage.setup)
    bound={}
    sort_key=None
    depth=len(g.iterating_lists)
    g.iterating_lists.extend(storage.forbidden_owners)
    try:
        for operand in plan.invocation.explicit_order:
            if method.name=="sort"and operand.parameter=="key":
                from .references import BuiltinIdentity,callable_reference
                import ast
                if isinstance(operand.expression,ast.Name):
                    reference=callable_reference(g,operand.expression,environment)
                    if getattr(reference,"_native_reference",False):
                        sort_key=operand.expression
                        continue
                value=g.expression(operand.expression,environment)
                if value.kind!="none":raise _Unsupported
            else:value=g.expression(operand.expression,environment)
            if method.name=="sort"and operand.parameter=="reverse":
                from .native_sequence_storage import deferred_truth
                deferred=deferred_truth(g,value,operand.expression,environment)
                if deferred is not None:
                    setup,truth_value,owners=deferred
                    lines.extend(setup)
                    bound[operand.parameter]=truth_value
                    g.iterating_lists.extend(owners)
                    continue
            temporary=g.temporary()
            code=f"({value.code}).clone()"if not value.owned else value.code
            lines.append(f"let {temporary}={code};")
            bound[operand.parameter]=_Expression(temporary,value.kind)
    finally:
        del g.iterating_lists[depth:]
    if method.mutates and storage.mutation_binding is not None:
        g.expression_mutations.append(storage.mutation_binding)
    if method.mutates and storage.binding_name is not None:
        name=storage.binding_name
        binding=environment[name]
        g.expression_mutations.append(binding)
        if not is_maybe(binding.kind):
            length=getattr(binding.info,"length",None)
            if method.name=="clear":length=0
            elif method.name=="append":length=None if length is None else length+1
            elif method.name=="pop":length=None if length is None else max(0,length-1)
            elif method.name=="extend":length=None
            g.update_info(environment,name,g.binding(_Expression("",receiver.kind,length=length)))
    result=lower(g,storage,method,bound,node,environment,sort_key=sort_key)
    return _Expression("{"+" ".join(lines)+result.code+"}",result.kind)
