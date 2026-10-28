"""One dispatch point for already lowered ordinary comparison operands."""
import ast

from .native_types import TupleType,deque_type


def compare_values(g,node,values,environment=None):
    from .native import _Expression,_Unsupported
    # A finite wrapper can itself contain shared handles. Dispatch that wrapper
    # before a concrete-list adapter sees only the other operand's layout.
    from .native_unions import union_kind,compare as finite_compare
    if any(union_kind(value.kind) for value in values):
        return finite_compare(g,node,values)
    from .native_nested_lists import comparison as shared_comparison
    shared=shared_comparison(g,node,values)
    if shared is not None:return shared
    from .native_deques import comparison as deque_comparison
    if any(deque_type(value.kind) for value in values):
        deque=deque_comparison(g,node,values,environment)
        if deque is not None:return deque
    if len(node.ops)==1 and isinstance(node.ops[0],(ast.In,ast.NotIn)):
        from .native_key_containers import comparison as keyed_comparison
        keyed=keyed_comparison(g,node,values)
        if keyed is not None:return keyed
    from .native_tuple_sequences import comparison as sequence_comparison
    sequence=sequence_comparison(g,node,values)
    if sequence is not None:return sequence
    from .native_unions import compare as finite_compare
    finite=finite_compare(g,node,values)
    if finite is not None:return finite
    if any(isinstance(value.kind,TupleType)for value in values):
        from .native_tuples import comparison as tuple_comparison
        return tuple_comparison(g,node,values)
    if any(value.kind=="bytes"for value in values):
        from .native_stdio import comparison as bytes_comparison
        return bytes_comparison(g,node,values)
    if any(value.kind in {"str","float"}for value in values):
        operation=getattr(g,"compare",None)or getattr(g,"text_compare",None)
        if operation is None:raise _Unsupported("scalar comparison lowering is unavailable")
        return operation(node,values)
    if len(node.ops)==1 and isinstance(node.ops[0],(ast.In,ast.NotIn)):
        key,container=values
        if container.kind not in {"dict_int","set_int"}:
            raise _Unsupported("membership for this container type is not implemented")
        if container.kind=="set_int"and key.kind!="int":
            raise _Unsupported("set membership requires a proved integer key")
        item,owner=g.temporary(),g.temporary()
        binding=container.code if container.owned else f"&({container.code})"
        argument=f"&{item}"if container.kind=="set_int"else item
        check=f"{owner}.contains({argument})"
        if isinstance(node.ops[0],ast.NotIn):check=f"!({check})"
        return _Expression(f"{{let {item}={g.number(key)};let {owner}={binding};{check}}}","bool")
    operators={ast.Eq:"==",ast.NotEq:"!=",ast.Lt:"<",ast.LtE:"<=",ast.Gt:">",ast.GtE:">="}
    if any(type(operator)not in operators for operator in node.ops):
        raise _Unsupported("non-None object identity is not proved")
    names=[g.temporary()for _ in values];tail="true"
    for index in reversed(range(len(node.ops))):
        test=f"{names[index]}{operators[type(node.ops[index])]}{names[index+1]}"
        tail=f"{{let {names[index+1]}={g.number(values[index+1])};({test})&&({tail})}}"
    return _Expression(f"{{let {names[0]}={g.number(values[0])};{tail}}}","bool")
