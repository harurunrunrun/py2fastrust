"""Defer immutable composite snapshots that still contain compiler unknowns.

Known mutable leaves retain their established shared-cell contribution route.
A real Python None is the complete string kind 'none', never a pending field.
The fair body solver revisits the original producing expression after its
parameter, imported constructor and callback facts become available.
"""
from .native_types import TupleType,UnionType,NullableType,ListType,TupleSequenceType,alternatives


def deferred(kind):
    from .native_class_globals import complete
    if not isinstance(kind,(TupleType,UnionType,NullableType))or complete(kind):return False
    def value_shape(value):
        if value is None:return True
        if isinstance(value,TupleType):return all(value_shape(field)for field in value.fields)
        if isinstance(value,(UnionType,NullableType)):return all(value_shape(child)for child in alternatives(value))
        # Transport actual mutable allocations/cursors through the existing
        # storage adapter, rather than withholding their producer-cell links.
        if isinstance(value,(ListType,TupleSequenceType)):return False
        return complete(value)
    return value_shape(kind)
