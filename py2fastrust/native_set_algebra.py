"""Builtin set operators |, &, - and ^ on the CPython-order set table kernel.

Each operator follows the corresponding Objects/setobject.c v3.14.4 algorithm
(set_or, set_intersection, set_difference with set_copy_and_difference and
set_difference_update_internal, set_symmetric_difference_impl), so later
traversal observes CPython's table order. Keys come from the operand side that
CPython iterates; the result record admits the key kinds of every such side.
"""
import ast

OPERATORS=(ast.BitOr,ast.BitAnd,ast.Sub,ast.BitXor)


def _set_kinds(value):
    from .native_classes import shape
    from .native_class_mappings import mapping_kind
    from .native_types import alternatives
    kinds=alternatives(shape(value))
    if kinds and all(mapping_kind(kind)and kind.record.category=='set'and kind.record.flavor=='set'for kind in kinds):
        return kinds
    return None


def requires_frames(unit,analysis):
    from .native_constraints import Allocation
    from .native_key_types import SetType
    from .native_types import alternatives
    def actual(ordinal):
        for facts in analysis.scopes.values():
            value=facts.values.get(ordinal)
            if any(isinstance(part,SetType)or isinstance(part,Allocation)and part.category=='set'for part in getattr(value,'alternatives',())):
                return True
            if any(isinstance(kind,SetType)for kind in alternatives(facts.expressions.get(ordinal))):return True
        return False
    for node in ast.walk(unit.tree):
        operator=node.op if isinstance(node,(ast.BinOp,ast.AugAssign))else None
        if isinstance(operator,OPERATORS):
            left=node.left if isinstance(node,ast.BinOp)else node.target
            right=node.right if isinstance(node,ast.BinOp)else node.value
            if actual(unit.ordinal(left))or actual(unit.ordinal(right)):return True
    return False


def analyze(model,plan,node,operator,left,right,identity):
    if not isinstance(node,(ast.BinOp,ast.AugAssign))or not isinstance(operator,OPERATORS):return None
    first,second=_set_kinds(left),_set_kinds(right)
    if first is None or second is None:return None
    if isinstance(node,ast.AugAssign):
        # In-place operators keep the target object; |=, &= and ^= may store
        # keys taken from the right operand's table.
        if not isinstance(operator,ast.Sub):
            for target in first:
                for source in second:model.mappings.contribute_key(target.record,source.record.key,node)
        return left
    record=model.mappings.record(plan,node,'set','operator')
    sources=first if isinstance(operator,ast.Sub)else first+second
    for kind in sources:model.mappings.contribute_key(record,kind.record.key,node)
    return model.cell(plan,node,record.kind,identity=identity)


def emit(emitter,operator,left,right,node,wanted):
    from .native_classes import Expression,shape
    from .native_class_mappings import mapping_kind
    if isinstance(node,ast.AugAssign)and isinstance(operator,OPERATORS):return _emit_inplace(emitter,operator,left,right,node)
    if not(isinstance(node,ast.BinOp)and isinstance(operator,OPERATORS)):return None
    if not(_admitted(emitter,left.kind)and _admitted(emitter,right.kind)):return None
    record=emitter.model.mappings.sites.get((emitter.plan.index,id(node),'set','set'))
    if record is None:return None
    own=record.kind
    from .native_unions import project,union_kind
    first,second_value=_uniform(emitter,left),_uniform(emitter,right)
    if first is not None and second_value is not None:left,right=first,second_value
    if union_kind(left.kind)or union_kind(right.kind):
        second=lambda kind,code,first:_binary(emitter,operator,first,Expression(code,kind),node,own).code
        result=Expression(project(left.kind,left.code,lambda kind,text:project(right.kind,right.code,lambda other,value:second(other,value,Expression(text,kind)))),own)
    else:result=_binary(emitter,operator,left,right,node,own)
    return result if wanted==own else Expression(emitter.coerce(result,wanted,node),wanted)


def _uniform(emitter,value):
    """Share one handle when every allocation alternative has the same table type."""
    from .native_classes import Expression
    from .native_types import UnionType,union_variant
    kind=value.kind
    if not isinstance(kind,UnionType):return value
    sets=emitter.model.mappings.cpython_sets
    payloads={sets.payload(emitter,choice.record)for choice in kind.alternatives}
    if len(payloads)!=1:return None
    handle=emitter.fresh()
    arms='|'.join(union_variant(kind,choice)+'('+handle+')'for choice in kind.alternatives)
    return Expression(f'match &({value.code}){{{arms}=>{handle}.clone()}}',kind.alternatives[0])


def _admitted(emitter,kind):
    from .native_class_mappings import mapping_kind
    from .native_types import alternatives
    sets=emitter.model.mappings.cpython_sets
    choices=alternatives(kind)
    return bool(choices)and all(mapping_kind(choice)and choice.record.category=='set'and choice.record.flavor=='set'and sets.owns(choice)for choice in choices)


def _binary(emitter,operator,left,right,node,wanted):
    from .native_classes import Expression,shape
    sets=emitter.model.mappings.cpython_sets
    record=wanted.record;record.emitted=True
    a,b,owner=(emitter.fresh()for _ in range(3))
    A,B,R=Expression(a,left.kind),Expression(b,right.kind),Expression(owner,wanted)
    code=f'let {a}=({left.code}).clone();let {b}=({right.code}).clone();let {owner}={sets.new(emitter,record)};'
    same=sets.payload(emitter,left.kind.record)==sets.payload(emitter,right.kind.record)
    identical=f'Rc::ptr_eq(&{a},&{b})'if same else'false'
    length=lambda side:side.code+'.borrow().len()'
    from .native_statement_lifetimes import _single_block
    block=lambda inner:inner if _single_block(inner)else'{'+inner+'}'

    def scan(source,lookup,keep,target):
        loan,key=emitter.fresh(),emitter.fresh()
        kind=shape(source.kind.record.key)
        test=sets.query(emitter,node,lookup,Expression(key+'.clone()',kind))
        add=sets.insert(emitter,node,target,Expression(key+'.clone()',kind))
        condition=test if keep else '!('+test+')'
        return f'{{let {loan}={source.code}.borrow();for ({key},_,_)in {loan}.entries(){{if {condition}{{{add}}}}}}}'

    def discard_all(source,target):
        loan,key=emitter.fresh(),emitter.fresh()
        kind=shape(source.kind.record.key)
        return f'{{let {loan}={source.code}.borrow();for ({key},_,_)in {loan}.entries(){{{sets.query(emitter,node,target,Expression(key+".clone()",kind),remove=True)};}}}}'

    if isinstance(operator,ast.BitOr):
        code+=sets.merge(emitter,node,R,A)+f'if !({identical})'+block(sets.merge(emitter,node,R,B))
    elif isinstance(operator,ast.BitAnd):
        code+=(f'if {identical}'+block(sets.merge(emitter,node,R,A))+f'else if {length(B)}>{length(A)}'+block(scan(A,B,True,R))
               +'else'+block(scan(B,A,True,R)))
    elif isinstance(operator,ast.Sub):
        # set_copy_and_difference, including its 8x intersection shortcut and
        # dummy compaction, versus the direct scan of the left table.
        common=emitter.fresh();C=Expression(common,wanted)
        shortcut=(f'let {common}={sets.new(emitter,record)};{scan(R,B,True,C)}{discard_all(C,R)}')
        copied=(sets.merge(emitter,node,R,A)+
                f'if ({length(B)}>>3)>{length(R)}'+block(shortcut)+'else'+block(discard_all(B,R))+
                emitter.at(owner+'.borrow_mut().compact_after_discards()',node)+';')
        code+=f'if ({length(A)}>>2)>{length(B)}'+block(copied)+'else'+block(scan(A,B,False,R))
    else:
        loan,key=emitter.fresh(),emitter.fresh()
        kind=shape(left.kind.record.key)
        removed=sets.query(emitter,node,R,Expression(key+'.clone()',kind),remove=True)
        add=sets.insert(emitter,node,R,Expression(key+'.clone()',kind))
        code+=sets.merge(emitter,node,R,B)+f'{{let {loan}={a}.borrow();for ({key},_,_)in {loan}.entries(){{if !({removed}){{{add}}}}}}}'
    return Expression('{'+code+owner+'}',wanted)


def _emit_inplace(emitter,operator,left,right,node):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    if not(_admitted(emitter,left.kind)and _admitted(emitter,right.kind)):return None
    first,second=_uniform(emitter,left),_uniform(emitter,right)
    if first is not None and second is not None:
        result=_inplace(emitter,operator,first,second,node)
        return result if first.kind==left.kind else Expression('{'+result.code+';'+left.code+'}',left.kind)
    if not(union_kind(left.kind)or union_kind(right.kind)):return _inplace(emitter,operator,left,right,node)
    target,source=emitter.fresh(),emitter.fresh()
    apply=lambda kind,code,first:'{'+_inplace(emitter,operator,first,Expression(code,kind),node).code+';}'
    body=project(left.kind,target,lambda kind,text:project(right.kind,source,lambda other,value:apply(other,value,Expression(text,kind))))
    return Expression(f'{{let {target}=({left.code}).clone();let {source}=({right.code}).clone();{body};{target}}}',left.kind)


def _inplace(emitter,operator,left,right,node):
    """set_ior, set_iand, set_isub and set_ixor on the target's own table."""
    from .native_classes import Expression,shape
    sets=emitter.model.mappings.cpython_sets
    from .native_statement_lifetimes import _single_block
    block=lambda inner:inner if _single_block(inner)else'{'+inner+'}'
    a,b=emitter.fresh(),emitter.fresh()
    A,B=Expression(a,left.kind),Expression(b,right.kind)
    code=f'let {a}=({left.code}).clone();let {b}=({right.code}).clone();'
    same=sets.payload(emitter,left.kind.record)==sets.payload(emitter,right.kind.record)
    identical=f'Rc::ptr_eq(&{a},&{b})'if same else'false'
    length=lambda side:side.code+'.borrow().len()'
    record=left.kind.record

    def each(source,body):
        loan,key=emitter.fresh(),emitter.fresh()
        kind=shape(source.kind.record.key)
        return f'{{let {loan}={source.code}.borrow();for ({key},_,_)in {loan}.entries(){{'+body(Expression(key+'.clone()',kind))+'}}'

    def intersection_into(target):
        # set_intersection(so=A, other=B) with its size swap and copy shortcut.
        scan=lambda source,lookup:each(source,lambda key:'if '+sets.query(emitter,node,lookup,key)+'{'+sets.insert(emitter,node,target,key)+'}')
        return (f'if {identical}'+block(sets.merge(emitter,node,target,A))+f'else if {length(B)}>{length(A)}'+block(scan(A,B))+'else'+block(scan(B,A)))

    if isinstance(operator,ast.BitOr):
        code+=sets.merge(emitter,node,A,B)
    elif isinstance(operator,ast.BitAnd):
        temporary=emitter.fresh();T=Expression(temporary,left.kind)
        code+=f'let {temporary}={sets.new(emitter,record)};'+intersection_into(T)
        code+=f'{a}.borrow_mut().swap_body(&mut {temporary}.borrow_mut());'
    elif isinstance(operator,ast.Sub):
        common=emitter.fresh();C=Expression(common,left.kind)
        discard=lambda source:each(source,lambda key:sets.query(emitter,node,A,key,remove=True)+';')
        shortcut=(f'let {common}={sets.new(emitter,record)};'
                  +each(A,lambda key:'if '+sets.query(emitter,node,B,key)+'{'+sets.insert(emitter,node,C,key)+'}')+discard(C))
        update=(f'if ({length(B)}>>3)>{length(A)}'+block(shortcut)+'else'+block(discard(B))
                +emitter.at(a+'.borrow_mut().compact_after_discards()',node)+';')
        code+=f'if {identical}{{{a}.borrow_mut().clear();}}else'+block(update)
    else:
        toggle=each(B,lambda key:'if !('+sets.query(emitter,node,A,key,remove=True)+'){'+sets.insert(emitter,node,A,key)+'}')
        code+=f'if {identical}{{{a}.borrow_mut().clear();}}else'+block(toggle)
    return Expression('{'+code+a+'}',left.kind)


def comparison(emitter,operator,left,right,node):
    """set_richcompare for two builtin sets: sizes, then set_issubset."""
    from .native_classes import Expression,shape
    if not isinstance(operator,(ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE)):return None
    from .native_unions import union_kind
    if union_kind(left.kind)or union_kind(right.kind):return None
    if not(_admitted(emitter,left.kind)and _admitted(emitter,right.kind)):return None
    sets=emitter.model.mappings.cpython_sets
    a,b=emitter.fresh(),emitter.fresh()
    A,B=Expression(a,left.kind),Expression(b,right.kind)

    def subset(small,large):
        loan,key=emitter.fresh(),emitter.fresh()
        kind=shape(small.kind.record.key)
        test=sets.query(emitter,node,large,Expression(key+'.clone()',kind))
        return f'{{let {loan}={small.code}.borrow();let found={loan}.entries().all(|({key},_,_)|{test});found}}'
    size=lambda side:side.code+'.borrow().len()'
    if isinstance(operator,(ast.Eq,ast.NotEq)):code=f'{size(A)}=={size(B)}&&{subset(A,B)}'
    elif isinstance(operator,ast.LtE):code=f'{size(A)}<={size(B)}&&{subset(A,B)}'
    elif isinstance(operator,ast.Lt):code=f'{size(A)}<{size(B)}&&{subset(A,B)}'
    elif isinstance(operator,ast.GtE):code=f'{size(B)}<={size(A)}&&{subset(B,A)}'
    else:code=f'{size(B)}<{size(A)}&&{subset(B,A)}'
    code=f'{{let {a}=({left.code}).clone();let {b}=({right.code}).clone();{code}}}'
    return '!('+code+')'if isinstance(operator,ast.NotEq)else code
