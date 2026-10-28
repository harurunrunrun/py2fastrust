"""Consume solved semantic facts at native allocations and CFG headers."""
from functools import wraps

from .native_types import (ListType,SharedListType,TupleType,EmptyType,EMPTY,immutable,rust_type,
                          is_maybe,maybe_type,join_types,unmaybe)
from .native_key_types import SetType,DictType
from .native_constraints import native_kind,canonical_kind


EMPTY_HELPERS='''
// No Python value inhabits an unconstrained container field.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
enum NativeEmpty {}
fn native_empty<T>(value:NativeEmpty)->T {match value {}}
'''


MAP_HELPERS='''
fn native_typed_literal<T,const N:usize>(values:[T;N])->Result<Vec<T>,String> {
    let mut result=Vec::new();
    native_typed_reserve(&mut result,N)?;
    result.extend(values);
    Ok(result)
}
fn native_typed_map<A,T,F:FnMut(A)->T>(values:Vec<A>,mut convert:F)->Result<Vec<T>,String> {
    let mut result=Vec::new();
    native_typed_reserve(&mut result,values.len())?;
    result.extend(values.into_iter().map(&mut convert));
    Ok(result)
}
'''


def facts_for(generator,node):
    facts=getattr(generator,"constraint_facts",None)
    unit=getattr(generator,"source_unit",None)
    if facts is None or unit is None:return None,None
    try:return facts,unit.ordinal(node)
    except KeyError:return None,None


def allocation_expression(g,node,environment):
    from .native import _Expression,_Unsupported
    facts,site=facts_for(g,node)
    if facts is None or site not in facts.allocations:return None
    term=g.type_analysis.graph.expressions[site]
    if term.operation not in {"list","set","dict","call"}:return None
    kind=facts.storage.get(site,facts.allocations[site])
    if kind is None:
        raise _Unsupported("the allocation's element/key/value kinds remain unresolved after type analysis; a finite typed storage representation has not been established",node=node,types=(("allocation",None),),proof="finite allocation-field types")
    if term.operation=="call":
        # The semantic allocation fact proves the callable identity and result
        # shape; source spelling alone cannot establish a container operation.
        callee=term.operands[0]
        from .native_constraints import MethodValue
        call=facts.calls.get(site)
        proved_copy=(call is not None and not call.identity.unknown and not call.identity.unbound
                     and bool(call.identity.alternatives) and all(isinstance(identity,MethodValue) and identity.name=="copy" for identity in call.identity.alternatives))
        if (isinstance(kind,ListType) and immutable(kind.element) and proved_copy and callee.operation=="attribute"
                and not term.operands[1] and not term.operands[2]):
            source=g.expression(g.type_analysis.graph.nodes[callee.operands[0].site],environment)
            shape=canonical_kind(source.kind)
            if isinstance(shape,ListType) and immutable(shape.element):
                g.has_typed_lists=g.has_lists=True
                g.register_type(source.kind)
                return _Expression(g.at(f"native_typed_copy(&({source.code}))",node),source.kind,length=source.length)
        # Nonempty iterable materializations retain their typed stream lowering.
        if site not in facts.constructors:return None
    kind=native_kind(kind,g.bits)
    if isinstance(kind,SharedListType):
        from .native_nested_lists import allocation
        return allocation(g,node,environment,kind,term)
    if isinstance(kind,ListType) and not immutable(kind.element):return None
    if isinstance(kind,(SetType,DictType)):
        from .native_key_containers import _construct,key_kind
        if not key_kind(kind.key):
            raise _Unsupported("this collection key requires Python hash/equality protocol handling beyond the registered native key representations",node=node,types=(("key",kind.key),),proof="hash/equality semantics for the key")
        if isinstance(kind,DictType)and not immutable(kind.value):
            raise _Unsupported("dictionary values contain mutable storage whose alias identity cannot be preserved by the selected owned-value representation",node=node,types=(("dictionary",kind),),proof="shared mutable value storage")
        if term.operation=="dict":
            keys=[];values=[]
            for key,item in term.operands:
                keys.append(g.expression(g.type_analysis.graph.nodes[key.site],environment))
                values.append(g.expression(g.type_analysis.graph.nodes[item.site],environment))
        elif term.operation=="set":
            keys=[g.expression(g.type_analysis.graph.nodes[item.site],environment) for item in term.operands];values=None
        else:keys=[];values=None if isinstance(kind,SetType) else []
        return _construct(g,keys,values,node,kind=kind)
    if kind in {"set_int","dict_int"}:
        g.has_sets|=kind=="set_int";g.has_dicts|=kind=="dict_int"
        owner=g.temporary();lines=[f"let mut {owner}:{rust_type(kind)}="+("NativeSet::new();" if kind=="set_int" else "NativeDict::new();")]
        children=term.operands if term.operation in {"set","dict"} else ()
        for item in children:
            key,item=(item,None) if kind=="set_int" else item
            expression=g.expression(g.type_analysis.graph.nodes[key.site],environment)
            name=g.temporary();lines.append(f"let {name}={g.coerce(expression,'int')};")
            if kind=="dict_int":
                expression=g.expression(g.type_analysis.graph.nodes[item.site],environment)
                value=g.temporary();lines.append(f"let {value}={g.coerce(expression,'int')};")
                lines.append(f"{owner}.set({name},{value});")
            else:lines.append(f"{owner}.insert({name});")
        return _Expression("{"+" ".join(lines)+f"{owner}}}",kind,length=len(children),nonempty=bool(children))
    if kind=="matrix_int":return None
    if kind=="list_int" or isinstance(kind,ListType):
        element="int" if kind=="list_int" else kind.element
        g.register_type(kind);g.has_lists=True
        values=[g.expression(g.type_analysis.graph.nodes[item.site],environment) for item in term.operands] if term.operation=="list" else []
        if values:
            g.has_typed_lists=True
            elements=",".join(value.code if value.kind==element and value.owned else g.coerce(value,element) for value in values)
            code=g.at(f"native_typed_literal([{elements}])",node)
        else:code=f"Vec::<{rust_type(element)}>::new()"
        return _Expression(code,kind,length=len(values))
    return None


def reset_statement(g,node,environment):
    """Consume solved clear-epoch shapes only after unique-owner proof."""
    import ast
    from .native import _Binding,_Expression,_Unsupported
    if not isinstance(node,ast.Expr):return None
    facts,site=facts_for(g,node.value)
    if facts is None or site not in facts.resets:return None
    term=g.type_analysis.graph.expressions[site]
    callee=term.operands[0]
    if callee.operation!="attribute" or callee.data!="clear" or callee.operands[0].operation!="name":raise _Unsupported
    name=callee.operands[0].data;binding=environment.get(name)
    if not isinstance(binding,_Binding) or is_maybe(binding.kind):raise _Unsupported
    if name in g.iterating_lists or binding.slot in g.borrowed_slots:
        raise _Unsupported(f"clearing {name!r} changes its element representation while an iterator or borrow still observes its storage; this shared storage transition is not implemented",node=node,types=((name,binding.kind),),proof="no live borrows during storage transition")
    if any(other!=name and isinstance(value,_Binding) and value.slot==binding.slot for other,value in environment.items()):
        raise _Unsupported(f"clearing {name!r} would replace storage that is also referenced by another name; an alias-preserving shared representation transition is not implemented",node=node,types=((name,binding.kind),),proof="shared mutable identity through clear()")
    if isinstance(binding.kind,SharedListType):
        # clear changes contents, never the captured list object's identity.
        # A later incompatible element layout still needs a shared union carrier.
        def fits(old,new):
            return isinstance(new,EmptyType) or old==new or isinstance(old,ListType)and isinstance(new,ListType)and fits(old.element,new.element)
        reset=facts.resets[site]
        if reset is not None and not fits(canonical_kind(binding.kind),canonical_kind(reset)):
            raise _Unsupported("clear followed by a different shared-list element layout needs an alias-preserving union storage adapter",node=node,types=(("old",binding.kind),("new",reset)),proof="shared allocation element-layout transition")
        return None
    kind=facts.resets[site]
    if kind is None:raise _Unsupported
    kind=native_kind(kind,g.bits);g.register_type(kind)
    if kind==binding.kind:
        environment[name]=_Binding(binding.slot,g.binding(_Expression("",kind,length=0)))
        return f"{binding.slot}.clear();",environment
    slot=g.bind(name,_Expression("",kind,length=0),environment)
    if isinstance(kind,ListType) or kind=="list_int":new=f"Vec::<{rust_type(canonical_kind(kind).element)}>::new()"
    elif isinstance(kind,SetType):new="NativeKeySet::new()"
    elif isinstance(kind,DictType):new="NativeKeyDict::new()"
    elif kind=="set_int":g.has_sets=True;new="NativeSet::new()"
    elif kind=="dict_int":g.has_dicts=True;new="NativeDict::new()"
    else:raise _Unsupported
    return f"{binding.slot}.clear();\n{slot} = {new};",environment


def converted_result(g,node,result):
    from .native import _Expression,_Unsupported
    facts,site=facts_for(g,node)
    if facts is None or site not in facts.allocations:return result
    expected=facts.storage.get(site,facts.allocations[site])
    if expected is None:raise _Unsupported
    expected=native_kind(expected,g.bits)
    if result.kind==expected:return result
    if isinstance(expected,SharedListType):
        from .native_nested_lists import wrap_result
        return wrap_result(g,result,expected,node)
    source=canonical_kind(result.kind)
    if not isinstance(source,ListType) or not isinstance(canonical_kind(expected),ListType):return result
    target=canonical_kind(expected)
    if not result.owned or not immutable(source.element) or not immutable(target.element):raise _Unsupported
    g.register_type(expected);g.has_typed_lists=g.has_lists=True
    item=g.temporary()
    conversion=g.coerce(_Expression(item,source.element),target.element)
    call=g.at(f"native_typed_map({result.code},|{item}|{conversion})",node)
    return _Expression(call,expected,length=result.length)


def result_shapes(method):
    @wraps(method)
    def lower(self,node,environment):
        from .native_nested_lists import try_expression as shared_expression
        shared=shared_expression(self,node,environment)
        if shared is not None:return converted_result(self,node,shared)
        from .native_lengths import try_expression as length_expression
        length=length_expression(self,node,environment)
        if length is not None:return converted_result(self,node,length)
        from .native_callbacks import try_expression as callback_expression
        callback=callback_expression(self,node,environment)
        if callback is not None:return converted_result(self,node,callback)
        return converted_result(self,node,method(self,node,environment))
    return lower


def loop_header(g,node,environment):
    from .native import _Binding,_Expression,_MaybeInfo,_Unsupported
    facts,site=facts_for(g,node)
    if facts is None:return "",g.after_loop(environment)
    state=facts.headers.get(site,{})
    # Every state carrier can survive a skipped assignment on a later
    # iteration, even when its only explicit read occurs after the loop.
    live=set(state)
    # The graph already contains test reads and explicit target binding. This
    # liveness query only selects carrier slots; it infers no source types.
    loop=g.type_analysis.graph.loops[site]
    term=loop.operands[0] if loop.operation=="while" else None
    if term is not None:
        def names(expression):
            if expression.operation=="name":return {expression.data}
            result=set()
            def children(operand):
                if hasattr(operand,"operation"):return names(operand)
                if isinstance(operand,tuple):return set().union(*(children(child) for child in operand)) if operand else set()
                return set()
            for operand in expression.operands:result|=children(operand)
            return result
        live|=names(term)
    if loop.operation=="for":
        # Target names come from normalized semantic target facts, not a type
        # inference walk over the loop body.
        from .native_constraints import target_names
        live-=target_names(loop.data)
    header=g.after_loop(environment);initializers=[];initialized=set()
    for name in sorted(live):
        fact=state.get(name)
        if fact is None:continue
        old=environment.get(name)
        if old is not None and not isinstance(old,_Binding):continue
        if fact.kind is None:
            raise _Unsupported(f"the compiler has not resolved a finite merged type for loop variable {name!r}, so its loop-carried native storage cannot be selected",node=node,types=((name,None),),proof="type fixed point across loop backedges")
        kind=native_kind(facts.header_storage.get(site,{}).get(name,fact.kind),g.bits)
        optional=fact.maybe_unbound or isinstance(old,_Binding) and is_maybe(old.kind)
        wanted=maybe_type(kind) if optional else kind
        if isinstance(old,_Binding) and old.kind==wanted:continue
        if not isinstance(old,_Binding) and not optional:continue
        slot=g.slot(wanted)
        owner=g.function.node.name if g.function else g.entry_scope
        header[name]=_Binding(slot,_MaybeInfo(kind,owner) if optional else g.binding(_Expression("",kind)))
        initializers.append(f"{slot}="+(g.coerce(_Expression(old.slot,old.kind),wanted) if isinstance(old,_Binding) else "None")+";")
        initialized.add(slot)
    g.constraint_header_slots[site]=initialized
    return "\n".join(initializers),header



def finish_loop(g,node,entry,header,context,body,remaining,nonempty,may_repeat,zero):
    """Plan each CFG transfer once and reject unproved mutable duplication."""
    from .native import _Binding,_Expression,_EdgeMove,_Unsupported,_static_reference
    from .native_types import default_value
    if remaining is not None:
        marker="// "+g.temporary()+"_edge"
        context["edges"].append((marker,"normal",remaining))
        body+="\n"+marker
    edges=context["edges"]
    initialized=g.constraint_header_slots.get(g.source_unit.ordinal(node),set())
    # Header initializers already transferred entry values. The zero-iteration
    # path observes those same initialized carriers instead of a moved source.
    effective_entry={name:header[name] if isinstance(header.get(name),_Binding) and header[name].slot in initialized else value
                     for name,value in entry.items()}
    effective_entry.update({name:value for name,value in header.items()
                            if name not in effective_entry and isinstance(value,_Binding) and value.slot in initialized and is_maybe(value.kind)})
    environments=([effective_entry] if not nonempty else [])+[environment for _,_,environment in edges]
    if zero:environments=[effective_entry]
    joined,post_moves=g.join(environments,preferred=header,structured=True)
    if joined is None:joined=g.after_loop(effective_entry)
    initializers=[]
    entry_slots={value.slot for value in effective_entry.values() if isinstance(value,_Binding)}
    for name,binding in joined.items():
        if not isinstance(binding,_Binding) or binding.slot in entry_slots or binding.slot in initialized:continue
        old=effective_entry.get(name)
        if isinstance(old,_Binding) and (not nonempty or zero):
            # A distinct mutable exit carrier must not consume storage needed
            # by the first iteration. A shared carrier is selected above when
            # the header and exit have the same shape.
            if not immutable(unmaybe(old.kind)) and not isinstance(unmaybe(old.kind),SharedListType) and any(isinstance(value,_Binding) and value.slot==old.slot for value in header.values()):
                raise _Unsupported
            default=g.coerce(_Expression(old.slot,old.kind),binding.kind)
        else:
            default=None if is_maybe(binding.kind) else default_value(binding.kind,g.literal(0))
            if default is None:default="None"
        initializers.append(f"{binding.slot} = {default};")
    live=g.read_before_write(node.body)
    if hasattr(node,"test"):
        import ast
        live|={value.id for value in ast.walk(node.test) if isinstance(value,ast.Name) and isinstance(value.ctx,ast.Load)}
    from .native_constraints import target_names
    loop=g.type_analysis.graph.loops[g.source_unit.ordinal(node)]
    targets=target_names(loop.data) if loop.operation=="for" else set()
    live-=targets
    replacements={};offset=0 if nonempty else 1
    for index,(marker,edge_kind,environment) in enumerate(edges):
        transfers=[];retained=set()
        if edge_kind!="break" and may_repeat and not zero:
            for name,previous in header.items():
                if name in targets:continue
                current=environment.get(name)
                if _static_reference(previous):
                    if name in live and current is not previous:
                        raise _Unsupported(f"loop variable {name!r} changes callable identity while still live; native callable versioning/dispatch for this loop carrier is not implemented",node=node,proof="callable identity across loop backedges")
                    continue
                if not isinstance(previous,_Binding):continue
                compatible=isinstance(current,_Binding) and join_types(canonical_kind(previous.kind),canonical_kind(current.kind))==canonical_kind(previous.kind)
                if not compatible:
                    if name in live:raise _Unsupported
                    continue
                if current.slot!=previous.slot:transfers.append(_EdgeMove(previous.slot,previous.kind,current))
                else:retained.add(previous.slot)
        if not zero:transfers+=post_moves[index+offset]
        destinations={}
        for transfer in transfers:
            old=destinations.get(transfer.destination)
            if old is not None and old!=transfer:raise _Unsupported
            destinations[transfer.destination]=transfer
        moved=set()
        for transfer in destinations.values():
            source=transfer.source
            if source is not None and not immutable(unmaybe(source.kind)) and not isinstance(unmaybe(source.kind),SharedListType):
                if source.slot in retained or source.slot in moved:
                    raise _Unsupported("this loop transfer would both retain and move, or move twice, the same mutable value; alias-preserving shared loop carriers are not implemented for this merge",node=node,operation="loop state transfer",types=(("value",source.kind),),proof="single transfer of mutable identity")
                moved.add(source.slot)
        replacements[marker]="\n".join(transfer.render(g) for transfer in destinations.values())
    body="\n".join(replacements.get(line,line) for line in body.split("\n"))
    return "\n".join(initializers),body,g.after_loop(joined)
