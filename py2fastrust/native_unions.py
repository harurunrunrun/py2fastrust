"""Operations over proved finite native alternatives; no universal value type."""
import ast
from contextvars import ContextVar

from .native_types import (UnionType,NullableType,TupleType,ListType,alternatives,
                          union_variant,union_declaration,immutable,join_types,rust_type)


def union_kind(kind):
    return isinstance(kind,(UnionType,NullableType))


def construct(kind,alternative,code):
    if isinstance(kind,NullableType):
        return f"{{let _={code};None}}" if alternative=="none" else f"Some({construct(kind.value,alternative,code)})"
    if isinstance(kind,UnionType):return f"{union_variant(kind,alternative)}({code})"
    assert kind==alternative
    return code


_projection_depth=ContextVar("native_projection_depth",default=0)


def project(kind,code,callback):
    """Borrow a finite value and generate an exhaustive, hygienic match.

    Callback-generated nested projections must not shadow the outer payload.
    A context-local nesting depth gives deterministic names, restores the caller
    context after errors, and keeps independent concurrent conversions isolated.
    """
    depth=_projection_depth.get()
    token=_projection_depth.set(depth+1)
    nullable=f"native_nullable_value_{depth}"
    union=f"native_union_value_{depth}"
    try:
        if isinstance(kind,NullableType):
            return f"match &({code}){{None=>{callback('none','()')},Some({nullable})=>{project(kind.value,'(*'+nullable+')',callback)}}}"
        if isinstance(kind,UnionType):
            arms=[f"{union_variant(kind,value)}({union})=>{project(value,'(*'+union+')',callback)}"
                  for value in kind.alternatives]
            return f"match &({code}){{{','.join(arms)}}}"
        return callback(kind,code)
    finally:_projection_depth.reset(token)


def coerce_union(value,target,coerce):
    from .native import _Expression,_Unsupported
    if not union_kind(target) and not union_kind(value.kind):return None
    source=value.kind
    if source==target:
        if immutable(target):return f"({value.code}).clone()"
        if not value.owned:raise _Unsupported
        return value.code
    # Moving an owned enum preserves unique mutable payload ownership. Cloning
    # is permitted only for recursively immutable alternatives.
    code=value.code
    if immutable(source):
        code=f"({code}).clone()"
    elif not value.owned:raise _Unsupported
    def inject(kind,inner):
        expression=_Expression(inner,kind)
        if isinstance(target,NullableType):
            if kind=="none":return f"{{let _={inner};None}}"
            return f"Some({coerce(expression,target.value)})"
        if isinstance(target,UnionType):
            from .native_constraints import canonical_kind
            candidates=[part for part in target.alternatives if canonical_kind(part)==canonical_kind(kind) or part=="int_bool" and kind in {"int","bool"}]
            if len(candidates)!=1:raise _Unsupported
            part=candidates[0]
            return f"{union_variant(target,part)}({coerce(expression,part)})"
        return coerce(expression,target)
    def move(kind,inner):
        if isinstance(kind,NullableType):
            return f"match {inner}{{None=>{inject('none','()')},Some(native_nullable_move)=>{move(kind.value,'native_nullable_move')}}}"
        if isinstance(kind,UnionType):
            return f"match {inner}{{"+",".join(f"{union_variant(kind,part)}(native_union_move)=>{move(part,'native_union_move')}" for part in kind.alternatives)+"}"
        return inject(kind,inner)
    return move(source,code)


def leaf_expression(g,node,environment):
    from .native import _Binding,_Expression
    if isinstance(node,ast.Constant) and node.value is None:
        return _Expression("()","none")
    if isinstance(node,ast.Name):
        value=environment.get(node.id)
        if isinstance(value,_Binding) and (union_kind(value.kind) or value.kind=="none"):
            g.register_type(value.kind)
            return _Expression(value.slot,value.kind,owned=False)
    return None


def truth(value,leaf):
    from .native import _Expression
    if value.kind=="none":return f"{{let _=&({value.code});false}}"
    if not union_kind(value.kind):return None
    return project(value.kind,value.code,lambda kind,code:"false" if kind=="none" else leaf(_Expression(code,kind,owned=False)))


def representation(g,value,leaf,quoted=False):
    from .native import _Expression
    if value.kind=="none":return f'{{let _=&({value.code});String::from("None")}}'
    if not union_kind(value.kind):return None
    return project(value.kind,value.code,lambda kind,code:representation(g,_Expression(code,kind,owned=False),leaf,quoted)
                   if kind=="none" else leaf(g,_Expression(code,kind,owned=False),quoted=quoted))


def compare(g,node,values):
    from .native import _Expression,_Unsupported
    if not any(union_kind(value.kind) or value.kind=="none" for value in values):return None
    if any(not isinstance(op,(ast.Is,ast.IsNot,ast.Eq,ast.NotEq)) for op in node.ops):raise _Unsupported
    names=[g.temporary() for _ in values]
    def pair(left,right,operator):
        def both(a,x,b,y):
            if isinstance(operator,(ast.Is,ast.IsNot)):
                if a!="none" and b!="none":raise _Unsupported
                result=str(a==b=="none").lower()
            elif a=="none" or b=="none":result=str(a==b).lower()
            else:
                from .native_tuples import tuple_compare
                result=tuple_compare(g,_Expression(x,a,owned=False),_Expression(y,b,owned=False),ast.Eq(),node)
            return f"!({result})" if isinstance(operator,(ast.IsNot,ast.NotEq)) else result
        return project(left.kind,left.code,lambda a,x:project(right.kind,right.code,lambda b,y:both(a,x,b,y)))
    tail="true"
    for index in reversed(range(len(node.ops))):
        left=_Expression(f"(*{names[index]})",values[index].kind,owned=False)
        right=_Expression(f"(*{names[index+1]})",values[index+1].kind,owned=False)
        check=pair(left,right,node.ops[index])
        tail=f"{{let {names[index+1]}=&({values[index+1].code});({check})&&({tail})}}"
    return _Expression(f"{{let {names[0]}=&({values[0].code});{tail}}}","bool")


def render_types(kinds):
    return "\n".join(union_declaration(kind,clone=immutable(kind)) for kind in sorted(kinds,key=rust_type))
