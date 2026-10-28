"""Direct builtin heap operations over typed list storage.

The heap is the original Python list object. Generic Rust swaps implement the
binary-heap invariant; no encoded Python instruction or universal value is
created. The comparator proof excludes user callbacks and fallible protocols.
The min/max public API is described at docs.python.org/3.14/library/heapq.html.
"""
import ast

from .call_semantics import FunctionSignature,CallBindingError,normalize_call
from .native import _Binding,_Expression,_Unsupported
from .native_types import (EmptyType,TupleType,TupleSequenceType,UnionType,
                          alternatives,immutable,list_type,is_maybe)


CORE=('heapify','heappush','heappop','heappushpop','heapreplace')
NAMES=CORE+tuple(name+'_max'for name in CORE)+('merge','nlargest','nsmallest')


HELPERS=r'''
fn native_heap_bubble<T,F:FnMut(&T,&T)->bool>(values:&mut [T],floor:usize,mut at:usize,earlier:&mut F) {
    while at>floor {
        let parent=(at-1)/2;
        if !earlier(&values[at],&values[parent]){break;}
        values.swap(at,parent);at=parent;
    }
}
fn native_heap_sink<T,F:FnMut(&T,&T)->bool>(values:&mut [T],start:usize,earlier:&mut F) {
    let mut at=start;
    while let Some(left)=at.checked_mul(2).and_then(|value|value.checked_add(1)) {
        if left>=values.len(){break;}
        let child=match left.checked_add(1) {
            Some(right)if right<values.len()&&!earlier(&values[left],&values[right])=>right,
            _=>left,
        };
        values.swap(at,child);at=child;
    }
    native_heap_bubble(values,start,at,earlier);
}
fn native_heapify<T,F:FnMut(&T,&T)->bool>(values:&mut Vec<T>,mut earlier:F) {
    for start in(0..values.len()/2).rev(){native_heap_sink(values,start,&mut earlier);}
}
fn native_heappush<T,F:FnMut(&T,&T)->bool>(values:&mut Vec<T>,item:T,mut earlier:F)->Result<(),String> {
    values.len().checked_add(1).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError: heap is too large".to_owned())?;
    values.try_reserve(1).map_err(|_|"MemoryError: cannot allocate heap".to_owned())?;
    values.push(item);let at=values.len()-1;native_heap_bubble(values,0,at,&mut earlier);Ok(())
}
fn native_heappop<T,F:FnMut(&T,&T)->bool>(values:&mut Vec<T>,mut earlier:F)->Result<T,String> {
    let last=values.pop().ok_or_else(||"IndexError: index out of range".to_owned())?;
    if values.is_empty(){return Ok(last);}
    let result=std::mem::replace(&mut values[0],last);native_heap_sink(values,0,&mut earlier);Ok(result)
}
fn native_heapreplace<T,F:FnMut(&T,&T)->bool>(values:&mut Vec<T>,item:T,mut earlier:F)->Result<T,String> {
    let root=values.first_mut().ok_or_else(||"IndexError: index out of range".to_owned())?;
    let result=std::mem::replace(root,item);native_heap_sink(values,0,&mut earlier);Ok(result)
}
fn native_heappushpop<T,F:FnMut(&T,&T)->bool>(values:&mut Vec<T>,item:T,mut earlier:F)->T {
    if values.first().is_some_and(|root|earlier(root,&item)) {
        let result=std::mem::replace(&mut values[0],item);native_heap_sink(values,0,&mut earlier);result
    }else{item}
}
'''


def orderable(kind,*,nested=False):
    if isinstance(kind,EmptyType):return True
    if kind in {'int','bool','int_bool','str','bytes'}:return True
    if kind=='float':return not nested
    if isinstance(kind,UnionType):
        return not nested and all(choice in {'int','bool','int_bool','float'}for choice in alternatives(kind))
    if kind=='none':return nested
    if isinstance(kind,TupleType):return all(orderable(child,nested=True)for child in kind.fields)
    if isinstance(kind,TupleSequenceType):return orderable(kind.element,nested=True)
    return False


def _comparator(g,element,node,maximum):
    if not orderable(element):
        raise _Unsupported('heap comparisons require a proved non-fallible builtin < protocol; custom comparisons, floating tuple identity/NaN and mixed unorderable alternatives are not implemented by this typed heap adapter',node=node,types=(('element',element),),proof='side-effect-free heap comparison protocol')
    if isinstance(element,EmptyType):return '|_,_|false'
    from .native_tuple_sequences import total_order
    left,right=g.temporary(),g.temporary()
    a=_Expression(f'(*{left})',element,owned=False);b=_Expression(f'(*{right})',element,owned=False)
    if maximum:a,b=b,a
    if element=='float'or isinstance(element,UnionType)and 'float'in alternatives(element):
        if not g.bits:
            raise _Unsupported('the BigInt path has no exact float comparison representation for heap items',node=node,types=(('element',element),),proof='BigInt/float heap comparison')
        from .native_comparisons import ordering
        # Bare floats use only <, including unordered NaN comparisons. Tuple
        # float payloads remain excluded: tuple equality has identity shortcuts.
        return f'|{left},{right}|{ordering(g,a,b,ast.Lt(),node)}'
    order=total_order(g,a,b,node)
    return f'|{left},{right}|matches!({order},std::cmp::Ordering::Less)'


def lower(g,node,environment,function):
    name=function.name
    if name not in CORE and name.removesuffix('_max')not in CORE:
        raise _Unsupported(f'heapq.{name} needs lazy multi-iterator or callable-key selection semantics; that typed stream adapter is not implemented yet',node=node,operation=f'heapq.{name}',proof='ordered lazy stream/key selection')
    maximum=name.endswith('_max');operation=name.removesuffix('_max')
    parameters=('heap','item')if operation in {'heappush','heappushpop','heapreplace'}else('heap',)
    signature=FunctionSignature.declaration(parameters,positional_only=parameters)
    try:plan=signature.plan(normalize_call(node))
    except CallBindingError as error:
        raise _Unsupported(f'heapq.{name} argument binding is invalid: {error}',node=node,operation=f'heapq.{name}',proof='positional-only builtin call binding')from None
    from .native_sequence_storage import capture_owned
    from .native_sequence_plans import element_type
    lines=[];storage=None;receiver=None;item=None;heap_binding=None;mutation_start=len(g.expression_mutations)
    guard_depth=len(g.iterating_lists)
    try:
        for argument,parameter in zip(plan.arguments.evaluation_order,plan.argument_parameters):
            if parameter=='heap':
                receiver=g.expression(argument.expression,environment)
                if not list_type(receiver.kind):
                    raise _Unsupported('heapq mutates the supplied builtin list; other sequence/iterator kinds are not valid heap storage',node=argument.expression,types=(('heap',receiver.kind),),proof='mutable builtin-list heap storage')
                storage=capture_owned(g,receiver,argument.expression,environment,mutates=True)
                lines.extend(storage.setup)
                heap_binding=environment.get(storage.binding_name)if storage.binding_name is not None else None
                g.iterating_lists.extend(storage.forbidden_owners)
            else:
                value=g.expression(argument.expression,environment);temporary=g.temporary()
                if not immutable(value.kind):
                    raise _Unsupported('heap items on this native path require immutable values; capturing arbitrary mutable payload aliases, even for an empty combined operation, is not implemented',node=argument.expression,types=(('item',value.kind),),proof='immutable heap item and alias-preserving argument capture')
                code=value.code if value.owned else g.coerce(value,value.kind)
                lines.append(f'let {temporary}={code};');item=_Expression(temporary,value.kind)
    finally:
        del g.iterating_lists[guard_depth:]
    assert storage is not None
    # An Rc capture retains the original list even if a later argument rebinds
    # its source name. Do not transfer the old object's facts to that new name.
    same_binding=True
    if storage.binding_name is not None and heap_binding is not None:
        current=environment.get(storage.binding_name)
        same_binding=isinstance(current,_Binding)and current.slot==heap_binding.slot
        if not same_binding and not storage.shared:
            raise _Unsupported('the captured heap storage representation changed while evaluating a later argument; an identity-preserving handle across that clear/rebinding transition is not implemented',node=node,proof='captured heap identity through argument effects')
    if storage.mutable is None:raise _Unsupported('heap mutation has no mutable view of this storage',node=node,proof='exclusive mutable heap view')
    # A known empty heap stays untouched by pushpop only if evaluating the item
    # cannot mutate that captured object. Other cases inspect it at runtime.
    touched=False
    if storage.binding_name is not None:
        binding=environment.get(storage.binding_name)
        slots={getattr(binding,'slot',None),getattr(heap_binding,'slot',None),getattr(storage.mutation_binding,'slot',None)}-{None}
        touched=any(getattr(value,'slot',None)in slots for value in g.expression_mutations[mutation_start:])
    else:touched=storage.shared or not receiver.owned or bool(storage.forbidden_owners)
    if operation=='heappushpop'and receiver.length==0 and not touched:
        return _Expression('{'+''.join(lines)+item.code+'}',item.kind)
    element=element_type(receiver.kind)
    if not immutable(element):
        raise _Unsupported('heap elements require stable immutable storage in this owned-vector path; shared mutable/custom element heaps remain unsupported',node=node,types=(('element',element),),proof='immutable heap element storage')
    compare=_comparator(g,element,node,maximum)
    if item is not None:
        item_code=item.code if item.kind==element else g.coerce(item,element)
    g.has_native_modules=g.has_lists=g.has_typed_lists=True
    g.register_type(receiver.kind)
    arguments=storage.mutable+(','+item_code if item is not None else'')+','+compare
    if operation=='heapify':code=f'native_heapify({arguments})';kind='none'
    elif operation=='heappush':code=g.at(f'native_heappush({arguments})',node);kind='none'
    elif operation=='heappushpop':code=f'native_heappushpop({arguments})';kind=element
    else:code=g.at(f'native_{operation}({arguments})',node);kind=element
    if storage.mutation_binding is not None:g.expression_mutations.append(storage.mutation_binding)
    if storage.binding_name is not None and same_binding:
        binding=environment[storage.binding_name];g.expression_mutations.append(binding)
        if not is_maybe(binding.kind):
            length=getattr(binding.info,'length',None)
            if operation=='heappush':length=None if length is None else length+1
            elif operation=='heappop':length=None if length is None else max(0,length-1)
            g.update_info(environment,storage.binding_name,g.binding(_Expression('',receiver.kind,length=length)))
    if storage.shared:
        # End the temporary RefMut before dropping the captured Rc local; a
        # borrow in the block's tail expression would otherwise outlive it.
        result=g.temporary();lines.append(f'let {result}={code};');code=result
    return _Expression('{'+''.join(lines)+code+'}',kind)
