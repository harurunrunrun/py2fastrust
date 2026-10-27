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
    try:plan=context(g,environment).method(node)
    except CallBindingError as error:raise _Unsupported from error
    if plan is None or plan.identity.name not in {"index","count","pop"}:return None
    receiver=plan.receiver.captured
    if not list_type(receiver.kind):return None
    element="int" if receiver.kind=="list_int" else receiver.kind.element
    if not _supported(element):raise _Unsupported
    g.has_lists=g.has_typed_lists=True
    g.register_type(receiver.kind)
    lines=[]
    owner=g.temporary()
    binding_name=None
    mutable=None
    if receiver.owned:
        lines.append(f"let mut {owner}={receiver.code};")
        sequence=f"&{owner}"
        mutable=f"&mut {owner}"
    else:
        # A named receiver is resolved before arguments, but its contents are
        # borrowed only after their effects (for example a.index(a.pop())).
        if g.type_analysis is None or g.source_unit is None:raise _Unsupported
        term=g.type_analysis.graph.expressions[g.source_unit.ordinal(plan.receiver.expression)]
        if term.operation!="name":raise _Unsupported
        lines.append(f"let _=&({receiver.code});")
        sequence=f"&({receiver.code})[..]"
        binding_name=term.data
        if plan.identity.name=="pop":
            binding=environment.get(binding_name)
            if (not isinstance(binding,_Binding) or binding_name in g.iterating_lists
                    or binding.slot in g.borrowed_slots):raise _Unsupported
            mutable=(f'{binding.slot}.as_mut().expect("validated list receiver")' if is_maybe(binding.kind)
                     else f"&mut {binding.slot}")
    bound={}
    for operand in plan.invocation.explicit_order:
        value=g.expression(operand.expression,environment)
        if operand.parameter=="value":
            if not _supported(value.kind):raise _Unsupported
            name=g.temporary()
            lines.append(f"let {name}={value.code};")
            bound["value"]=_Expression(name,value.kind,owned=False)
        else:
            if value.kind not in {"int","bool","int_bool"}:raise _Unsupported
            name=g.temporary()
            lines.append(f"let {name}={g.number(value)};")
            bound[operand.parameter]=(f"{name} as i128" if g.bits else
                f"{name}.to_i128().unwrap_or_else(||if {name}.is_negative(){{i128::MIN}}else{{i128::MAX}})")
    if plan.identity.name=="pop":
        if binding_name is not None:
            binding=environment[binding_name]
            g.expression_mutations.append(binding)
            if not is_maybe(binding.kind):
                length=getattr(binding.info,"length",None)
                length=max(0,length-1) if length is not None else None
                g.update_info(environment,binding_name,g.binding(_Expression("",receiver.kind,length=length)))
        call=g.at(f"native_sequence_pop({mutable},{bound.get('index','-1_i128')})",node)
        return _Expression("{"+" ".join(lines)+call+"}",element)
    needle=bound["value"]
    item=g.temporary()
    if isinstance(element,EmptyType):equal=f"match *{item} {{}}"
    elif isinstance(needle.kind,EmptyType):equal=f"match {needle.code} {{}}"
    else:
        from .native_tuples import _equal
        equal=_equal(g,_Expression(f"(*{item})",element,owned=False),needle)
    if plan.identity.name=="count":
        call=f"native_sequence_count({sequence},|{item}|{equal})"
    else:
        start=bound.get("start","0_i128")
        stop=f"Some({bound['stop']})" if "stop" in bound else "None"
        call=g.at(f"native_sequence_index({sequence},{start},{stop},|{item}|{equal})",node)
    result=f"({call}) as NativeInt" if g.bits else f"Int::from_i128(({call}) as i128)"
    return _Expression("{"+" ".join(lines)+result+"}","int")
