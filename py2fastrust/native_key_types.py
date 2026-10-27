"""Structural types for uniquely owned containers with immutable keys."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SetType:
    key: object
    _key_container = "set"


@dataclass(frozen=True)
class DictType:
    key: object
    value: object
    _key_container = "dict"


@dataclass(frozen=True)
class KeyInfo:
    kind: object
    length: int | None = None
    nonempty: bool = False
    _key_info = True


def canonical_tuple(fields):
    """Avoid Rust's tuple Eq/Hash arity limit without boxing any field."""
    from .native_types import tuple_code
    fields=tuple(fields)
    if len(fields)<=12:return tuple_code(fields)
    midpoint=len(fields)//2
    return tuple_code((canonical_tuple(fields[:midpoint]),canonical_tuple(fields[midpoint:])))


def compatible_keys(left,right):
    from .native_types import TupleType,EmptyType
    if isinstance(left,EmptyType) or isinstance(right,EmptyType):return True
    if left in {"int","bool","int_bool"} and right in {"int","bool","int_bool"}:return True
    if left==right=="str":return True
    return (isinstance(left,TupleType) and isinstance(right,TupleType) and len(left.fields)==len(right.fields)
            and all(compatible_keys(a,b) for a,b in zip(left.fields,right.fields)))


def canonical_type(kind):
    from .native_types import TupleType,EmptyType
    if isinstance(kind,EmptyType):return "NativeEmpty"
    if kind in {"int","bool","int_bool"}:return "NativeInt"
    if kind=="str":return "String"
    if isinstance(kind,TupleType):return canonical_tuple(canonical_type(field) for field in kind.fields)
    raise KeyError(kind)


def container_type(kind):
    from .native_types import rust_type
    if isinstance(kind,SetType):return f"NativeKeySet<{rust_type(kind.key)},{canonical_type(kind.key)}>"
    return f"NativeKeyDict<{rust_type(kind.key)},{rust_type(kind.value)},{canonical_type(kind.key)}>"
