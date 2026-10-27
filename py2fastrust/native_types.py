"""Hashable structural types shared by direct Rust lowering layers."""
from dataclasses import dataclass


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
    if is_maybe(kind):
        return "Option<"+rust_type(unmaybe(kind))+">"
    if isinstance(kind,TupleType):
        return tuple_code(rust_type(field) for field in kind.fields)
    if isinstance(kind,ListType):
        return "Vec<"+rust_type(kind.element)+">"
    if getattr(kind,"_key_container",False):
        from .native_key_types import container_type
        return container_type(kind)
    return {"int":"NativeInt","bool":"bool","int_bool":"NativeScalar","str":"String",
            "bytes":"Vec<u8>","float":"f64","none":"()","list_int":"Vec<NativeInt>",
            "matrix_int":"Vec<Vec<NativeInt>>","dict_int":"NativeDict","set_int":"NativeSet",
            "deque_int":"std::collections::VecDeque<NativeInt>"}[kind]


def kind_tag(kind):
    if is_maybe(kind):
        return "maybe_"+kind_tag(unmaybe(kind))
    if isinstance(kind,TupleType):
        return "tuple"+str(len(kind.fields))+"_"+"_".join(kind_tag(field) for field in kind.fields)+"_end"
    if isinstance(kind,ListType):
        return "list_"+kind_tag(kind.element)+"_end"
    if getattr(kind,"_key_container",False):
        return kind._key_container+"_"+kind_tag(kind.key)+("_"+kind_tag(kind.value) if kind._key_container=="dict" else "")+"_end"
    return kind


def immutable(kind):
    return (isinstance(kind,TupleType) and all(immutable(field) for field in kind.fields)
            or kind in {"int","bool","int_bool","str","bytes","float","none"})


def join_types(left,right):
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
    return None


def list_type(kind):
    return kind=="list_int" or isinstance(kind,ListType)


def default_value(kind,zero):
    if is_maybe(kind):return "None"
    if isinstance(kind,TupleType):return tuple_code(default_value(field,zero) for field in kind.fields)
    if isinstance(kind,ListType):return "Vec::new()"
    if getattr(kind,"_key_container",False):return "NativeKeySet::new()" if kind._key_container=="set" else "NativeKeyDict::new()"
    return {"int":zero,"bool":"false","int_bool":f"NativeScalar::Int({zero})","str":"String::new()",
            "bytes":"Vec::<u8>::new()","float":"0.0_f64","list_int":"Vec::new()",
            "matrix_int":"Vec::new()","set_int":"NativeSet::new()","dict_int":"NativeDict::new()",
            "deque_int":"std::collections::VecDeque::new()"}[kind]
