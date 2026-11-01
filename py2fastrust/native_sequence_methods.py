"""One operation lowering for owned and shared builtin sequence storage."""
from .native import _Expression,_Unsupported
from .native_types import EmptyType,immutable,list_type,deque_type
from .native_sequence_plans import element_type


def lower(g,storage,method,bound,node,environment,*,sort_key=None):
    """Consume already captured explicit values; borrow contents at the operation."""
    if deque_type(storage.kind):
        from .native_deques import lower as deque_lower
        return deque_lower(g,storage,method,bound,node,environment)
    if method.error:
        from .native import _string
        return _Expression(g.at(f"Err::<(),String>({_string(method.error)}.into())",node),"none")
    element=storage.element
    from .native_nested_lists import shared_element
    shared_kind=getattr(g,"shared_element",shared_element)
    if not immutable(element)and not(storage.shared and shared_kind(element)):
        raise _Unsupported("this sequence operation has mutable element values, but its element ownership/alias-preserving storage adapter is not implemented",node=node,types=(("receiver",storage.kind),("element",element)),proof="mutable element identity across sequence operations")
    name=method.name
    if name=="append":
        value=bound["value"]
        owned=value.code if value.kind==element and value.owned else g.coerce(value,element)
        code=g.at(f"native_typed_push({storage.mutable},{owned})",node)
    elif name=="insert":
        index=g.temporary()
        value=bound["value"]
        owned=value.code if value.kind==element and value.owned else g.coerce(value,element)
        payload=g.temporary()
        code=(f"{{let {index}={_insert_index(g,bound['index'],node)};let {payload}={owned};"
              +g.at(f"native_sequence_insert({storage.mutable},{index},{payload})",node)+"}")
    elif name=="remove":
        code=_remove(g,storage,bound["value"],node)
    elif name=="extend":
        value=bound["iterable"]
        if not list_type(value.kind):
            raise _Unsupported("list.extend currently consumes a resolved native list; iteration and ordered element conversion for this other iterable representation are not implemented on the shared sequence path",node=node,types=(("receiver",storage.kind),("iterable",value.kind)),proof="ordered iterable consumption and element conversion")
        source=element_type(value.kind)
        if not immutable(source)and not(storage.shared and shared_kind(source)):
            raise _Unsupported("list.extend would copy mutable elements whose shared Python identities must be retained; the identity-preserving element adapter is not implemented for these source/destination storages",node=node,types=(("receiver",storage.kind),("iterable",value.kind)),proof="mutable element sharing during extend")
        if not storage.shared and value.owned:
            if source==element:
                code=g.at(f"native_typed_extend({storage.mutable},{value.code})",node)
            else:
                item=g.temporary()
                converted=g.coerce(_Expression(item,source),element)
                code=g.at(f"native_typed_extend_mapped({storage.mutable},{value.code},|{item}|{converted})",node)
        else:
            from .native_types import SharedListType
            sequence=f"&({value.code}.borrow())[..]" if isinstance(value.kind,SharedListType) or storage.shared and not isinstance(storage.kind,SharedListType) else f"&({value.code})[..]"
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
        custom_equal=getattr(g,"sequence_equal",None)if storage.shared else None
        from .native_types import SharedListType
        if isinstance(storage.kind,SharedListType):
            from .native_nested_lists import equality
            custom_equal=lambda left,right,node:equality(g,left,right,node)
        if custom_equal is None and (not _supported(element)or not _supported(needle.kind)):
            raise _Unsupported(f"list.{name} needs Python equality for this element/needle pair, including their identity or special-method behavior; that equality adapter is not implemented",node=node,types=(("element",element),("needle",needle.kind)),proof="Python sequence-search equality and identity behavior")
        item=g.temporary()
        if isinstance(element,EmptyType):equal=f"match *{item} {{}}"
        elif isinstance(needle.kind,EmptyType):equal=f"match {needle.code} {{}}"
        elif custom_equal is not None:
            equal=custom_equal(_Expression(f"(*{item}).clone()",element),needle,node)
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
              "{"+setup+_sort_code(g,f"({storage.mutable})",element,node,environment,direction,sort_key,
                                   forbidden_owners=storage.forbidden_owners+storage.callback_owners+((storage.binding_name,)if storage.binding_name else()))+"}")
    else:raise _Unsupported(f"the shared sequence operation {name!r} has no native method implementation",node=node,types=(("receiver",storage.kind),))
    kind=(storage.kind if method.result=="copy" else element if method.result=="element"else method.result)
    return _Expression(code,kind)


def _bound(g,value,default):
    if value is None:return default
    if value.kind not in {"int","bool","int_bool"}:
        raise _Unsupported("this sequence index/bound requires Python __index__ conversion or its TypeError; conversion/error emission for this argument type is not implemented",types=(("index/bound",value.kind),),proof="Python integer-index protocol")
    code=g.number(value)
    return f"({code}) as i128" if g.bits else f"({code}).to_i128().unwrap_or_else(||if ({code}).is_negative(){{i128::MIN}}else{{i128::MAX}})"


def _insert_index(g,value,node):
    from .native_unions import project,union_kind
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:_insert_index(g,_Expression(f"({code}).clone()",kind),node))
    if value.kind in {"int","bool","int_bool"}:
        code=g.number(value)
        if g.bits:converted=f"isize::try_from(({code}) as i128).ok()"
        else:converted=f"({code}).to_i128().and_then(|value|isize::try_from(value).ok())"
        return g.at(f'{converted}.ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())',node)
    from .native_comparisons import _type_name
    type_name=getattr(g,"sequence_type_name",_type_name)
    try:label=type_name(value)
    except _Unsupported:
        raise _Unsupported("list.insert index requires Python __index__ conversion for this value; that protocol adapter is not implemented",node=node,types=(("index",value.kind),),proof="Python integer-index protocol")from None
    from .native_classes import InstanceType
    if isinstance(value.kind,InstanceType):
        raise _Unsupported("list.insert index requires Python __index__ conversion for this instance; that protocol adapter is not implemented",node=node,types=(("index",value.kind),),proof="Python integer-index protocol")
    return g.at(f'Err::<isize,String>(format!("TypeError: \'{{}}\' object cannot be interpreted as an integer",{label}))',node)


def _remove(g,storage,needle,node):
    from .native_list_methods import _supported
    from .native_tuples import _equal
    from .native_types import SharedListType
    from .native import _string
    element=storage.element
    missing=g.at(f'Err::<(),String>({_string("ValueError: list.remove(x): x not in list")}.into())',node)
    if isinstance(element,EmptyType):return missing
    custom_equal=getattr(g,"sequence_equal",None)if storage.shared else None
    if isinstance(storage.kind,SharedListType):
        from .native_nested_lists import equality
        custom_equal=lambda left,right,node:equality(g,left,right,node)
    if custom_equal is None and(not _supported(element)or not _supported(needle.kind)):
        raise _Unsupported("list.remove requires Python equality and identity for this element/needle pair; that equality adapter is not implemented",node=node,types=(("element",element),("needle",needle.kind)),proof="Python list removal equality and identity")
    from .native_classes import has_float_payload
    if has_float_payload(element)or has_float_payload(needle.kind):
        raise _Unsupported("list.remove requires identity-aware floating-point equality, including NaN objects; this element/needle adapter is not implemented",node=node,types=(("element",element),("needle",needle.kind)),proof="floating-point identity in list removal")
    cursor,item,found,removed,values,candidate=(g.temporary()for _ in range(6))
    if storage.shared:
        value=_Expression(item,element)
        equal=custom_equal(value,needle,node)if custom_equal else _equal(g,value,needle)
        compare=(f"let {candidate}={{let {values}={storage.read};{values}.get({cursor}).cloned()}};"
                 +f"let {found}=match {candidate}"
                 +f"{{Some({item})=>{{let same={equal};drop({item});same}},None=>{{{missing};unreachable!()}}}};")
    else:
        equal=_equal(g,_Expression(f"(*{item})",element,owned=False),needle)
        compare=(f"let {found}={{({storage.read}).get({cursor}).map(|{item}|{equal})}};"
                 +f"let {found}=match {found}{{Some(value)=>value,None=>{{{missing};unreachable!()}}}};")
    advance=g.at(f'{cursor}.checked_add(1).ok_or_else(||"OverflowError: list removal index overflow".to_owned())',node)
    return (f"{{let mut {cursor}=0_usize;loop{{"+compare
            +f"if {found}{{let {removed}={{let {values}={storage.mutable};"
            +f"if {cursor}<{values}.len(){{Some({values}.remove({cursor}))}}else{{None}}}};drop({removed});break;}}"
            +f"{cursor}={advance};"+"}}")


HELPERS=r'''
fn native_sequence_insert<T>(values:&mut Vec<T>,index:isize,value:T)->Result<(),String> {
    native_typed_reserve(values,1)?;
    let length=isize::try_from(values.len()).map_err(|_|"MemoryError".to_owned())?;
    let position=if index<0 {index.saturating_add(length).max(0) as usize}
        else {(index as usize).min(values.len())};
    values.insert(position,value);Ok(())
}
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
