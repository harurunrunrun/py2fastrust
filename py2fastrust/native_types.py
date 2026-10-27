"""Hashable structural types shared by direct Rust lowering layers."""
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class EmptyType:
    """Bottom element type: no source value can inhabit an unconstrained field."""


EMPTY=EmptyType()


@dataclass(frozen=True)
class TupleType:
    fields: tuple[object, ...]


@dataclass(frozen=True)
class ListType:
    element: object


@dataclass(frozen=True)
class MaybeType:
    value: object


@dataclass(frozen=True)
class NullableType:
    """A Python value that is None or value; distinct from an unbound name."""
    value: object


@dataclass(frozen=True)
class UnionType:
    """Canonical finite alternatives, each with its own concrete Rust type."""
    alternatives: tuple[object, ...]


def alternatives(kind):
    if isinstance(kind,UnionType):
        return kind.alternatives
    if isinstance(kind,NullableType):
        return ("none",)+alternatives(kind.value)
    return (kind,)


def union_type(*kinds):
    values=set()
    for kind in kinds:
        values.update(alternatives(kind))
    values={kind for kind in values if not isinstance(kind,EmptyType)}
    if not values:return EMPTY if kinds else None
    if "int_bool" in values or {"int","bool"} <= values:
        values.difference_update({"int","bool"})
        values.add("int_bool")
    nullable="none" in values and len(values)>1
    if nullable:values.remove("none")
    ordered=tuple(sorted(values,key=kind_tag))
    result=ordered[0] if len(ordered)==1 else UnionType(ordered)
    return NullableType(result) if nullable else result


def union_name(kind):
    assert isinstance(kind,UnionType)
    return "NativeUnion"+sha256(kind_tag(kind).encode()).hexdigest()[:16]


def union_variant(kind,alternative):
    return union_name(kind)+"::V"+str(kind.alternatives.index(alternative))


def union_declaration(kind,render=None,clone=True):
    """Pure adapter boundary: class emitters may supply their leaf renderer."""
    render=rust_type if render is None else render
    derive="#[derive(Clone)]\n" if clone else ""
    fields=",".join(f"V{index}({render(value)})" for index,value in enumerate(kind.alternatives))
    return derive+f"enum {union_name(kind)} {{{fields}}}"


@dataclass(frozen=True)
class TypedListInfo:
    kind: ListType
    length: int | None = None


def is_maybe(kind):
    return isinstance(kind,MaybeType) or isinstance(kind,str) and kind.startswith("maybe_")


def unmaybe(kind):
    if isinstance(kind,MaybeType):
        return kind.value
    return kind.removeprefix("maybe_") if isinstance(kind,str) else kind


def maybe_type(kind):
    return "maybe_"+kind if isinstance(kind,str) else MaybeType(kind)


def tuple_code(fields):
    fields=tuple(fields)
    return "("+",".join(fields)+("," if len(fields)==1 else "")+")"


def tuple_field(code,index):
    return f"({code}).{index}"


def rust_type(kind):
    return render_type(kind)


def render_type(kind, leaf_override=None):
    """Render canonical types, optionally overriding storage for selected leaves.

    The callback receives (kind, recurse) and returns None to retain the shared
    representation. This permits shared handles without redefining tuple, union,
    nullable or unbound value semantics.
    """
    def recurse(value):return render_type(value,leaf_override)
    if leaf_override is not None:
        replacement=leaf_override(kind,recurse)
        if replacement is not None:return replacement
    if isinstance(kind,EmptyType):return "NativeEmpty"
    if is_maybe(kind):
        return "Option<"+recurse(unmaybe(kind))+">"
    if isinstance(kind,NullableType):return "Option<"+recurse(kind.value)+">"
    if isinstance(kind,UnionType):return union_name(kind)
    if isinstance(kind,TupleType):
        return tuple_code(recurse(field) for field in kind.fields)
    if isinstance(kind,ListType):
        return "Vec<"+recurse(kind.element)+">"
    if getattr(kind,"_key_container",False):
        from .native_key_types import container_type
        return container_type(kind)
    return {"int":"NativeInt","bool":"bool","int_bool":"NativeScalar","str":"String",
            "bytes":"Vec<u8>","float":"f64","none":"()","list_int":"Vec<NativeInt>",
            "matrix_int":"Vec<Vec<NativeInt>>","dict_int":"NativeDict","set_int":"NativeSet",
            "deque_int":"std::collections::VecDeque<NativeInt>"}[kind]


def kind_tag(kind):
    if isinstance(kind,EmptyType):return "empty"
    if hasattr(kind,"_native_kind_tag"):return kind._native_kind_tag
    if is_maybe(kind):
        return "maybe_"+kind_tag(unmaybe(kind))
    if isinstance(kind,NullableType):return "nullable_"+kind_tag(kind.value)+"_end"
    if isinstance(kind,UnionType):return "union_"+"_".join(kind_tag(value) for value in kind.alternatives)+"_end"
    if isinstance(kind,TupleType):
        return "tuple"+str(len(kind.fields))+"_"+"_".join(kind_tag(field) for field in kind.fields)+"_end"
    if isinstance(kind,ListType):
        return "list_"+kind_tag(kind.element)+"_end"
    if getattr(kind,"_key_container",False):
        return kind._key_container+"_"+kind_tag(kind.key)+("_"+kind_tag(kind.value) if kind._key_container=="dict" else "")+"_end"
    return kind


def immutable(kind):
    return (isinstance(kind,EmptyType)
            or isinstance(kind,UnionType) and all(immutable(value) for value in kind.alternatives)
            or isinstance(kind,NullableType) and immutable(kind.value)
            or isinstance(kind,TupleType) and all(immutable(field) for field in kind.fields)
            or kind in {"int","bool","int_bool","str","bytes","float","none"})


def join_types(left,right):
    if isinstance(left,EmptyType):return right
    if isinstance(right,EmptyType):return left
    if left==right:
        return left
    if left in {"int","bool","int_bool"} and right in {"int","bool","int_bool"}:
        return "int_bool"
    if isinstance(left,TupleType) and isinstance(right,TupleType) and len(left.fields)==len(right.fields):
        fields=tuple(join_types(a,b) for a,b in zip(left.fields,right.fields))
        return None if None in fields else TupleType(fields)
    if isinstance(left,ListType) and isinstance(right,ListType):
        element=join_types(left.element,right.element)
        return None if element is None else ListType(element)
    if is_maybe(left) or is_maybe(right):return None
    return union_type(left,right)


def list_type(kind):
    return kind=="list_int" or isinstance(kind,ListType)


def default_value(kind,zero):
    if is_maybe(kind):return "None"
    if isinstance(kind,NullableType):return "None"
    if isinstance(kind,UnionType):
        value=kind.alternatives[0]
        return f"{union_variant(kind,value)}({default_value(value,zero)})"
    if isinstance(kind,TupleType):return tuple_code(default_value(field,zero) for field in kind.fields)
    if isinstance(kind,ListType):return "Vec::new()"
    if getattr(kind,"_key_container",False):return "NativeKeySet::new()" if kind._key_container=="set" else "NativeKeyDict::new()"
    return {"none":"()","int":zero,"bool":"false","int_bool":f"NativeScalar::Int({zero})","str":"String::new()",
            "bytes":"Vec::<u8>::new()","float":"0.0_f64","list_int":"Vec::new()",
            "matrix_int":"Vec::new()","set_int":"NativeSet::new()","dict_int":"NativeDict::new()",
            "deque_int":"std::collections::VecDeque::new()"}[kind]
