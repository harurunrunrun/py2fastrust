"""Preselection proofs for values needing the shared typed-frame storage ABI."""
from .native_types import ListType,TupleType,NullableType,MaybeType,UnionType,EmptyType


def frame_storable(kind):
    """Storage proof only; each consuming operation still proves its protocol."""
    if isinstance(kind,EmptyType)or kind in {"int","bool","int_bool","float","str","bytes","none","range"}:return True
    if isinstance(kind,(NullableType,MaybeType)):return frame_storable(kind.value)
    if isinstance(kind,ListType):return frame_storable(kind.element)
    if isinstance(kind,TupleType):return all(frame_storable(field)for field in kind.fields)
    if isinstance(kind,UnionType):return all(frame_storable(branch)for branch in kind.alternatives)
    return getattr(kind,"_native_function_reference",False)or getattr(kind,"_native_class_iterator",False)


def _mutable_list(kind):
    if isinstance(kind,ListType):return True
    if isinstance(kind,(NullableType,MaybeType)):return _mutable_list(kind.value)
    if isinstance(kind,TupleType):return any(_mutable_list(field)for field in kind.fields)
    if isinstance(kind,UnionType):return any(_mutable_list(branch)for branch in kind.alternatives)
    return False


def shared_tuple_storage(analysis):
    # The ordinary tuple ABI accepts immutable payloads. A solved mutable list
    # payload needs shared handles, also when no class/function syntax is used.
    return any(isinstance(kind,TupleType)and _mutable_list(kind)and frame_storable(kind)
               for facts in analysis.scopes.values()for kind in facts.expressions.values())
