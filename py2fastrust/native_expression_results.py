"""Typed carriers for actual conditional/boolean values, preserving ownership.

A result may move a unique owned container or retain a proved shared reference.
Borrowed mutable contents are never copied to manufacture a result value.
"""
from .native_types import (ListType,SharedListType,NullableType,UnionType,
    join_types,reference_cloneable)


def _layout(kind):
    from .native_constraints import canonical_kind
    # Canonicalize legacy owned Vec spellings, preserving physical Rc handles.
    if isinstance(kind,SharedListType):return kind
    if isinstance(kind,NullableType):return NullableType(_layout(kind.value))
    if isinstance(kind,UnionType):
        from .native_types import union_type
        return union_type(*(_layout(part) for part in kind.alternatives))
    return canonical_kind(kind) if kind in {"list_int","matrix_int"} else kind


def has_shared(kind):
    """Whether a physical result contains an identity-preserving list handle."""
    from .native_types import TupleType,TupleSequenceType
    if isinstance(kind,SharedListType):return True
    if isinstance(kind,NullableType):return has_shared(kind.value)
    if isinstance(kind,UnionType):return any(has_shared(part) for part in kind.alternatives)
    if isinstance(kind,TupleType):return any(has_shared(part) for part in kind.fields)
    if isinstance(kind,(ListType,TupleSequenceType)):return has_shared(kind.element)
    return False


def join_layouts(left,right):
    if isinstance(left,SharedListType) or isinstance(right,SharedListType):
        # A shared object cannot change element representation by copying it.
        if isinstance(left,ListType) and isinstance(right,ListType):
            from .native_types import union_type
            return union_type(left,right)
    return join_types(left,right)


def kind(g,values,node):
    from .native import _Unsupported
    from .native_constraints import native_kind
    result=None
    for value in values:
        if not value.owned and not reference_cloneable(value.kind):
            raise _Unsupported("the selected conditional value borrows mutable storage without an identity-preserving shared handle",node=node,types=(("operand",value.kind),),proof="actual-value result ownership")
        layout=_layout(value.kind)
        result=layout if result is None else join_layouts(result,layout)
        if result is None:
            raise _Unsupported("conditional alternatives require incompatible native object layouts; an existing shared object cannot be copied to change its element representation",node=node,types=tuple((f"alternative {i+1}",item.kind)for i,item in enumerate(values)),proof="actual-value shared object layout")
    if result is None:raise _Unsupported("conditional expression has no result alternatives",node=node)
    result=native_kind(result,g.bits)
    g.register_type(result)
    return result
