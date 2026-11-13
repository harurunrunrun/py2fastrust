"""Closed native Copy carriers for shallow dictionary payload copying."""
from .native_types import NullableType,TupleType


def copy_kind(kind,integer):
    if type(kind)is str:
        return kind in {'bool','float','none'}or kind in {'int','int_bool'}and integer in {'i64','i128'}
    if type(kind)is TupleType:return all(copy_kind(part,integer)for part in kind.fields)
    if type(kind)is NullableType:return copy_kind(kind.value,integer)
    return False


def method(name,key,value,integer):
    return name+'_bits'if copy_kind(key,integer)and copy_kind(value,integer)else name
