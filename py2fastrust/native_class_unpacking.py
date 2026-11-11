"""Unpack a shared typed iterator before storing any target at this level."""
import ast
from dataclasses import dataclass

from .native_class_iterators import iterator_kind


def has_star(target):
    return any(isinstance(node,ast.Starred)for node in target.elts)


def requires_frames(unit,analysis):
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    logical={unit.scope_for(node).ordinal for node in nodes.values()
             if isinstance(node,(ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp))}
    scopes={0}
    for definition,_ in analysis.scopes:
        if definition is not None:scopes.add(unit.scope_for(nodes[definition]).ordinal)
    for node in ast.walk(unit.tree):
        if not isinstance(node,ast.Starred)or not isinstance(node.ctx,ast.Store):continue
        scope=unit.nodes[unit.ordinal(node)].scope
        while scope is not None and(scope in logical or unit.scopes[scope].kind=='comprehension'):scope=unit.scopes[scope].parent
        if scope in scopes:return True
    # The ordinary stream target binder handles fixed tuples, but dynamic
    # list rows need the ordered native unpack adapter. Ordinary assignment
    # already has its own length-checked list adapter and keeps that route.
    from .native_constraints import Allocation,TupleValue
    from .native_positional_selection import Provenance
    flow=Provenance(getattr(analysis,'heap',{}))
    def needs_list(target,value):
        if not isinstance(target,(ast.Tuple,ast.List)):return False
        members=flow.resolve(value)
        if members is None:return False
        for member in members:
            if isinstance(member,Allocation)and member.category=='list':return True
            if isinstance(member,TupleValue)and len(member.fields)==len(target.elts):
                if any(needs_list(child,field)for child,field in zip(target.elts,member.fields)):return True
        return False
    for facts in analysis.scopes.values():
        for node in nodes.values():
            if isinstance(node,(ast.For,ast.comprehension)):
                value=flow.field(facts.values.get(unit.ordinal(node.iter)),'iteration')
                if needs_list(node.target,value):return True
    return False


@dataclass
class Unpack:
    star:int|None
    source_kind:object=None
    fields:object=None
    rest:object=None


def _sites(model):
    if not hasattr(model,'unpack_sites'):model.unpack_sites={}
    return model.unpack_sites


def analyze(model, plan, target, value, environment,*,bind_target=None):
    from .native_classes import Cell,shape
    from .native_types import EMPTY
    from .native_unions import union_kind
    from .native_class_iterators import default_noniterable
    from .native_list_positions import analyze_unpack
    positional=analyze_unpack(model,plan,target,value,environment,bind_target)
    if positional is not None:
        _sites(model)[(plan.index,id(target))]=positional
        return True
    from .native_finite_tuple_unpacking import analyze as analyze_finite
    finite=analyze_finite(model,plan,target,value,environment,bind_target=bind_target)
    if finite is not None:
        _sites(model)[(plan.index,id(target))]=finite
        return True
    def bind(node,item):
        if bind_target is not None:bind_target(node,item)
        else:model.target(plan,node,item,environment)
    star=next((i for i,node in enumerate(target.elts)if isinstance(node,ast.Starred)),None)
    source=value.root()
    mismatch=source.tag=='tuple'and star is None and len(source.args)!=len(target.elts)
    if star is None and not(iterator_kind(shape(value))or union_kind(shape(value))or default_noniterable(model,shape(value))or mismatch):
        return False
    record=Unpack(star)
    if source.tag=='tuple':
        fields=source.args;record.fields=fields
        minimum=len(target.elts)-(star is not None)
        enough=len(fields)>=minimum and(star is not None or len(fields)==minimum)
        for i,node in enumerate(target.elts):
            if i==star:
                rest=model.cell(plan,node,'list',(Cell(),))
                tail=len(target.elts)-star-1
                members=fields[star:len(fields)-tail]if enough else()
                for member in members:model.contribute(rest.root().args[0],member,node)
                if not members:model.contribute(rest.root().args[0],Cell(EMPTY),node)
                record.rest=rest
                bind(node.value,rest)
            else:
                index=i if star is None or i<star else len(fields)-len(target.elts)+i
                bind(node,fields[index]if enough else Cell(EMPTY))
    else:
        record.source_kind=model.iterators.source(plan,target,value)
        member=model.iterators.demand(plan,target,Cell(record.source_kind),environment)
        for i,node in enumerate(target.elts):
            if i==star:
                rest=model.cell(plan,node,'list',(Cell(),))
                model.contribute(rest.root().args[0],member,node)
                record.rest=rest
                bind(node.value,rest)
            else:bind(node,member)
    _sites(model)[(plan.index,id(target))]=record
    return True


def emit(emitter, target, value,*,assign_target=None):
    from .native import _string
    from .native_classes import Expression,shape
    assign=assign_target or emitter.assign
    record=_sites(emitter.model).get((emitter.plan.index,id(target)))
    if record is None:
        return None
    if getattr(record,'_positional_list_unpack',False):
        from .native_list_positions import emit_unpack
        return emit_unpack(emitter,target,value,record,assign_target)
    if getattr(record,'_finite_tuple_unpack',False):
        from .native_finite_tuple_unpacking import emit as emit_finite
        return emit_finite(emitter,target,value,record,assign_target=assign_target)
    setup, source = emitter.capture(value)
    expected=len(target.elts)
    if record.fields is not None:
        count=len(record.fields);minimum=expected-(record.star is not None)
        if count<minimum or record.star is None and count>expected:
            if count<minimum:
                wanted=('at least 'if record.star is not None else'')+str(minimum)
                message=f'ValueError: not enough values to unpack (expected {wanted}, got {count})'
            else:message=f'ValueError: too many values to unpack (expected {expected})'
            return setup+emitter.at('Err::<(),String>('+_string(message)+'.to_owned())',target)+';'
        members=[]
        for i,node in enumerate(target.elts):
            if i==record.star:
                tail=expected-record.star-1;kind=shape(record.rest)
                values=[emitter.coerce(Expression(source.code+'.'+str(j)+'.clone()',shape(record.fields[j])),kind.element,node)
                        for j in range(i,count-tail)]
                members.append(Expression('class_list(vec!['+','.join(values)+'])',kind))
            else:
                index=i if record.star is None or i<record.star else count-expected+i
                members.append(Expression(source.code+'.'+str(index)+'.clone()',shape(record.fields[index])))
        captured=[]
        for member in members:
            before,member=emitter.capture(member);setup+=before;captured.append(member)
        return setup+''.join(assign(node.value if isinstance(node,ast.Starred)else node,member)
                             for node,member in zip(target.elts,captured))
    from .native_class_builtins import _type_name
    constructed=emitter.model.iterators.construct(emitter,target,source,kind=record.source_kind,
        not_iterable=lambda value:'format!("TypeError: cannot unpack non-iterable {} object",'+_type_name(emitter,value,target)+')')
    before,source=emitter.capture(constructed);setup+=before
    pulled = emitter.model.iterators.pull(emitter, target, source)
    if record.star is not None:
        values,item=(emitter.fresh()for _ in range(2))
        setup+='let mut '+values+':Vec<'+emitter.rust_type(pulled.kind)+'>=Vec::new();'
        reserve=emitter.at(values+'.try_reserve(1).map_err(|_|"MemoryError: cannot allocate unpacked remainder".to_owned())',target)
        setup+='while let Some('+item+')=('+pulled.code+'){'+reserve+';'+values+'.push('+item+');}'
        return setup+emit_star_values(emitter,target,record,values,pulled.kind,assign_target=assign_target)
    members = []
    for index in range(expected):
        name = emitter.fresh()
        message = f"ValueError: not enough values to unpack (expected {expected}, got {index})"
        missing = emitter.at(f'Err::<{emitter.rust_type(pulled.kind)},String>({_string(message)}.to_owned())', target)
        setup += f"let {name}=match {pulled.code}{{Some(value)=>value,None=>{missing}}};"
        members.append(Expression(name, pulled.kind))
    message = f"ValueError: too many values to unpack (expected {expected})"
    excess = emitter.at(f'Err::<(),String>({_string(message)}.to_owned())', target)
    setup += f"if ({pulled.code}).is_some(){{{excess};}}"
    return setup + "".join(assign(node, member) for node, member in zip(target.elts, members))


def emit_star_values(emitter,target,record,values,item_kind,*,assign_target=None):
    """Bind a completed native value snapshot before evaluating any target."""
    from .native import _string
    from .native_classes import Expression,shape
    assign=assign_target or emitter.assign
    expected=len(target.elts);minimum=expected-1;tail=expected-record.star-1
    message=_string(f'ValueError: not enough values to unpack (expected at least {minimum}, got {{}})')
    setup='if '+values+'.len()<'+str(minimum)+'{'+emitter.at('Err::<(),String>(format!('+message+','+values+'.len()))',target)+';}'
    members=[]
    for i,node in enumerate(target.elts):
        if i==record.star:members.append(None);continue
        index=str(i)if i<record.star else values+'.len()-'+str(expected-i)
        before,member=emitter.capture(Expression(values+'['+index+'].clone()',item_kind));setup+=before;members.append(member)
    if tail:setup+=values+'.truncate('+values+'.len()-'+str(tail)+');'
    if record.star:setup+=values+'.drain(..'+str(record.star)+');'
    kind=shape(record.rest)
    if kind.element!=item_kind:
        converted,current=(emitter.fresh()for _ in range(2))
        setup+='let mut '+converted+':Vec<'+emitter.rust_type(kind.element)+'>=Vec::new();'
        setup+=emitter.at(converted+'.try_reserve_exact('+values+'.len()).map_err(|_|"MemoryError: cannot allocate unpacked remainder".to_owned())',target)+';'
        item=emitter.coerce(Expression(current,item_kind),kind.element,target)
        setup+='for '+current+' in '+values+'{'+converted+'.push('+item+');}'
        values=converted
    before,remainder=emitter.capture(Expression('class_list('+values+')',kind));setup+=before;members[record.star]=remainder
    return setup+''.join(assign(node.value if isinstance(node,ast.Starred)else node,member)
                         for node,member in zip(target.elts,members))
