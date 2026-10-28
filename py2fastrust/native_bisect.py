"""Typed builtin list bisection with captured arguments and explicit bounds."""
import ast

from .call_semantics import CallBindingError,FunctionSignature,normalize_call
from .native import _Binding,_Expression,_Unsupported
from .native_types import EmptyType,TupleType,TupleSequenceType,alternatives,immutable,is_maybe,list_type


HELPERS=r'''
fn native_bisect_search<T,X,F:FnMut(&T,&X)->bool>(values:&[T],item:&X,lo:Option<isize>,hi:Option<isize>,mut advance:F)->Result<usize,String> {
    let mut lo=lo.unwrap_or(0);let mut hi=hi.unwrap_or(-1);
    if lo<0{return Err("ValueError: lo must be non-negative".into());}
    if hi== -1{hi=isize::try_from(values.len()).map_err(|_|"OverflowError: sequence is too large".to_owned())?;}
    while lo<hi {
        let mid=lo+(hi-lo)/2;
        let value=values.get(mid as usize).ok_or_else(||"IndexError: list index out of range".to_owned())?;
        if advance(value,item){lo=mid+1;}else{hi=mid;}
    }
    Ok(lo as usize)
}
fn native_bisect_insert<T,F:FnMut(&T,&T)->bool>(values:&mut Vec<T>,item:T,lo:Option<isize>,hi:Option<isize>,advance:F)->Result<(),String> {
    let index=native_bisect_search(values,&item,lo,hi,advance)?.min(values.len());
    values.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())?;
    values.insert(index,item);Ok(())
}
'''


def helpers(bits):
    conversion=('isize::try_from(*value).ok()'if bits else
                'value.to_i128().and_then(|value|isize::try_from(value).ok())')
    return HELPERS+f'''fn native_bisect_index(value:&NativeInt)->Result<isize,String>{{
    {conversion}.ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())
}}
'''


def _tuple_order(g,left,right,node):
    """Non-fallible tuple order, including fixed/runtime-length products."""
    from .native_tuple_sequences import total_order
    a,b=left.kind,right.kind
    if isinstance(a,TupleSequenceType)and isinstance(b,TupleType):
        result=f'({left.code}).len().cmp(&{len(b.fields)}_usize)'
        for index,kind in reversed(tuple(enumerate(b.fields))):
            x=_Expression(f'({left.code}).as_slice()[{index}]',a.element,owned=False)
            y=_Expression(f'({right.code}).{index}',kind,owned=False)
            step=g.temporary();order=_tuple_order(g,x,y,node)
            result=(f'if ({left.code}).len()<={index}{{std::cmp::Ordering::Less}}else'
                    f'{{let {step}={order};if {step}==std::cmp::Ordering::Equal{{{result}}}else{{{step}}}}}')
        return '{'+result+'}'
    if isinstance(a,TupleType)and isinstance(b,TupleSequenceType):
        return f'({_tuple_order(g,right,left,node)}).reverse()'
    return total_order(g,left,right,node)


def _advance(g,element,item,node,right):
    if isinstance(element,EmptyType):return '|_,_|false'
    if not immutable(element)or not immutable(item):
        raise _Unsupported('bisect comparison requires immutable builtin payloads; mutable/custom comparison protocols are not implemented',node=node,types=(('element',element),('item',item)),proof='non-reentrant typed bisection comparator')
    a,b=g.temporary(),g.temporary()
    left=_Expression(f'(*{a})',element,owned=False);other=_Expression(f'(*{b})',item,owned=False)
    numeric={'int','bool','int_bool','float'}
    if all(set(alternatives(kind))<=numeric for kind in(element,item)):
        from .native_comparisons import ordering
        test=ordering(g,other if right else left,left if right else other,ast.Lt(),node)
        if right:test=f'!({test})'
    elif element==item and element in {'str','bytes'}:
        test=f'({left.code})<({other.code})'if not right else f'!(({other.code})<({left.code}))'
    elif isinstance(element,(TupleType,TupleSequenceType))and isinstance(item,(TupleType,TupleSequenceType)):
        order=_tuple_order(g,other if right else left,left if right else other,node)
        test=f'matches!({order},std::cmp::Ordering::Less)'
        if right:test=f'!({test})'
    else:
        raise _Unsupported('these bisection operands have no proved builtin non-fallible comparison; an exception-aware comparator is still required for mixed unorderable alternatives',node=node,types=(('element',element),('item',item)),proof='typed builtin bisection ordering')
    return f'|{a},{b}|{test}'


def lower(g,node,environment,function):
    mutating=function.name.startswith('insort');right=not function.name.endswith('_left')
    signature=FunctionSignature.declaration(('a','x','lo','hi'),keyword_only=('key',),default_names=('lo','hi','key'))
    try:plan=signature.plan(normalize_call(node))
    except CallBindingError as error:
        raise _Unsupported(f'bisect argument binding is invalid: {error}',node=node,proof='builtin bisection call binding')from None
    from .native_sequence_storage import capture_owned
    from .native_sequence_plans import element_type
    lines=[];storage=None;receiver=None;item=None;bounds={};original=None
    guard_depth=len(g.iterating_lists)
    try:
        for argument,parameter in zip(plan.arguments.evaluation_order,plan.argument_parameters):
            source=argument.expression
            if parameter=='a':
                receiver=g.expression(source,environment)
                if not list_type(receiver.kind):
                    raise _Unsupported('this bisection adapter requires builtin list storage; other sequence protocols are not implemented',node=source,types=(('sequence',receiver.kind),),proof='typed builtin-list bisection storage')
                storage=capture_owned(g,receiver,source,environment,mutates=mutating)
                lines.extend(storage.setup);g.iterating_lists.extend(storage.forbidden_owners)
                original=environment.get(storage.binding_name)if storage.binding_name is not None else None
            else:
                value=g.expression(source,environment)
                if parameter=='key':
                    if value.kind!='none':
                        raise _Unsupported('bisect callable key evaluation requires a per-visited-element callback adapter; only key=None is currently implemented',node=source,proof='bisection key callback timing')
                    if not(isinstance(source,ast.Constant)and source.value is None):lines.append(f'let _={value.code};')
                    continue
                if parameter in {'lo','hi'}and value.kind=='none':
                    if parameter!='hi':raise _Unsupported('lo=None has no integer index protocol',node=source,proof='bisection integer index conversion')
                    if not(isinstance(source,ast.Constant)and source.value is None):lines.append(f'let _={value.code};')
                    bounds[parameter]=None;continue
                if not immutable(value.kind):
                    raise _Unsupported('capturing this bisection argument requires a shared mutable/custom value protocol that is not implemented',node=source,types=((parameter,value.kind),),proof='single argument evaluation preserving value identity')
                temporary=g.temporary();code=value.code if value.owned else g.coerce(value,value.kind)
                lines.append(f'let {temporary}={code};');captured=_Expression(temporary,value.kind)
                if parameter=='x':item=captured
                else:bounds[parameter]=captured
    finally:del g.iterating_lists[guard_depth:]
    assert storage is not None and item is not None
    same_binding=True
    if storage.binding_name is not None and original is not None:
        current=environment.get(storage.binding_name)
        same_binding=isinstance(current,_Binding)and current.slot==original.slot
        if not same_binding and not storage.shared:
            raise _Unsupported('the captured bisection list was rebound during later argument evaluation; its owned-vector identity is not retained across that change',node=node,proof='bisection receiver identity across argument effects')
    indices=[]
    for parameter in('lo','hi'):
        bound=bounds.get(parameter)
        if bound is None:indices.append('None');continue
        temporary=g.temporary();integer=g.number(bound)
        lines.append(f'let {temporary}={g.at(f"native_bisect_index(&({integer}))",node)};');indices.append(f'Some({temporary})')
    element=element_type(receiver.kind)
    if mutating:
        if storage.mutable is None:raise _Unsupported('this bisection list has no mutable storage view',node=node,proof='mutable insort receiver')
        code=item.code if item.kind==element else g.coerce(item,element)
        compare=_advance(g,element,element,node,right)
        operation=f'native_bisect_insert({storage.mutable},{code},{",".join(indices)},{compare})'
        kind='none'
    else:
        compare=_advance(g,element,item.kind,node,right)
        operation=f'native_bisect_search({storage.read},&{item.code},{",".join(indices)},{compare})'
        kind='int'
    code=g.at(operation,node)
    if not mutating:code=f'({code})as NativeInt'if g.bits else f'Int::from_i128(({code})as i128)'
    if storage.shared:
        result=g.temporary();lines.append(f'let {result}={code};');code=result
    if mutating:
        if storage.mutation_binding is not None:g.expression_mutations.append(storage.mutation_binding)
        if storage.binding_name is not None and same_binding:
            binding=environment[storage.binding_name];g.expression_mutations.append(binding)
            if not is_maybe(binding.kind):
                length=getattr(binding.info,'length',None)
                g.update_info(environment,storage.binding_name,g.binding(_Expression('',receiver.kind,length=None if length is None else length+1)))
    g.has_native_modules=g.has_lists=g.has_typed_lists=True;g.register_type(receiver.kind)
    return _Expression('{'+''.join(lines)+code+'}',kind)
