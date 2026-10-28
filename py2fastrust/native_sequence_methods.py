"""One operation lowering for owned and shared builtin sequence storage."""
from .native import _Expression,_Unsupported
from .native_types import EmptyType,immutable,list_type
from .native_sequence_plans import element_type


def lower(g,storage,method,bound,node,environment,*,sort_key=None):
    """Consume already captured explicit values; borrow contents at the operation."""
    element=storage.element
    if not immutable(element):raise _Unsupported
    name=method.name
    if name=="append":
        value=bound["value"]
        owned=value.code if value.kind==element and value.owned else g.coerce(value,element)
        code=g.at(f"native_typed_push({storage.mutable},{owned})",node)
    elif name=="extend":
        value=bound["iterable"]
        if not list_type(value.kind):raise _Unsupported
        source=element_type(value.kind)
        if not immutable(source):raise _Unsupported
        if not storage.shared and value.owned:
            if source==element:
                code=g.at(f"native_typed_extend({storage.mutable},{value.code})",node)
            else:
                item=g.temporary()
                converted=g.coerce(_Expression(item,source),element)
                code=g.at(f"native_typed_extend_mapped({storage.mutable},{value.code},|{item}|{converted})",node)
        else:
            sequence=f"&({value.code}.borrow())[..]" if storage.shared else f"&({value.code})[..]"
            # Shared contents are snapshotted before taking a mutable borrow,
            # including x.extend(x). Captured owned vectors need no second copy.
            if source==element:copied=g.at(f"native_typed_copy({sequence})",node)
            else:
                item=g.temporary()
                converted=g.coerce(_Expression(f"{item}.clone()",source),element)
                copied=g.at(f"native_typed_mapped_copy({sequence},|{item}|{converted})",node)
            snapshot=g.temporary()
            code=(f"{{let {snapshot}={copied};"
                  +g.at(f"native_typed_extend({storage.mutable},{snapshot})",node)+"}")
    elif name in {"clear","reverse"}:
        code=f"({storage.mutable}).{name}()"
    elif name=="copy":
        code=storage.own(g.at(f"native_typed_copy({storage.read})",node))
    elif name=="pop":
        index=_bound(g,bound.get("index"),"-1_i128")
        code=g.at(f"native_sequence_pop({storage.mutable},{index})",node)
    elif name in {"index","count"}:
        from .native_list_methods import _supported
        needle=bound["value"]
        if not _supported(element)or not _supported(needle.kind):raise _Unsupported
        item=g.temporary()
        if isinstance(element,EmptyType):equal=f"match *{item} {{}}"
        elif isinstance(needle.kind,EmptyType):equal=f"match {needle.code} {{}}"
        else:
            from .native_tuples import _equal
            equal=_equal(g,_Expression(f"(*{item})",element,owned=False),needle)
        if name=="count":code=f"native_sequence_count({storage.read},|{item}|{equal})"
        else:
            start=_bound(g,bound.get("start"),"0_i128")
            stop="None" if "stop"not in bound or bound["stop"].kind=="none" else f"Some({_bound(g,bound['stop'],None)})"
            code=g.at(f"native_sequence_index({storage.read},{start},{stop},|{item}|{equal})",node)
        code=f"({code}) as NativeInt" if g.bits else f"Int::from_i128(({code}) as i128)"
    elif name=="sort":
        from .native_typed_lists import _sort_code
        reverse=g.truth(bound["reverse"]) if "reverse"in bound else "false"
        direction=g.temporary()
        # Python converts reverse only after evaluating all explicit arguments,
        # before sorting borrows or temporarily empties the selected list. The
        # value may alias this receiver, so it cannot be read by the comparator.
        setup=f"let {direction}={reverse};"
        code=("{"+setup+"()}" if isinstance(element,EmptyType) else
              "{"+setup+_sort_code(g,f"({storage.mutable})",element,node,environment,direction,sort_key)+"}")
    else:raise _Unsupported
    kind=(storage.kind if method.result=="copy" else element if method.result=="element"else method.result)
    return _Expression(code,kind)


def _bound(g,value,default):
    if value is None:return default
    if value.kind not in {"int","bool","int_bool"}:raise _Unsupported
    code=g.number(value)
    return f"({code}) as i128" if g.bits else f"({code}).to_i128().unwrap_or_else(||if ({code}).is_negative(){{i128::MIN}}else{{i128::MAX}})"


HELPERS=r'''
fn native_typed_extend<T>(values:&mut Vec<T>,additional:Vec<T>)->Result<(),String> {
    native_typed_reserve(values,additional.len())?;
    values.extend(additional);Ok(())
}
fn native_typed_extend_mapped<A,B,F:FnMut(A)->B>(values:&mut Vec<B>,additional:Vec<A>,convert:F)->Result<(),String> {
    native_typed_reserve(values,additional.len())?;
    values.extend(additional.into_iter().map(convert));Ok(())
}
fn native_typed_mapped_copy<A,B,F:FnMut(&A)->B>(values:&[A],convert:F)->Result<Vec<B>,String> {
    let mut result=Vec::new();native_typed_reserve(&mut result,values.len())?;
    result.extend(values.iter().map(convert));Ok(result)
}
'''
