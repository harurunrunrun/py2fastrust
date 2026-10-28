"""Ordering of proved immutable values through ordinary Rust operations."""
import ast

from .native_types import TupleType,TupleSequenceType, immutable


ORDERING = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
_INTEGERS = {"int", "bool", "int_bool"}


def _type_name(value):
    from .native import _Unsupported, _string
    if isinstance(value.kind, (TupleType,TupleSequenceType)):
        return _string("tuple")
    if value.kind == "int_bool":
        return (f'match &({value.code}){{NativeScalar::Bool(_)=>"bool",'
                'NativeScalar::Int(_)=>"int"}')
    if value.kind not in {"none", "int", "bool", "float", "str", "bytes"}:
        raise _Unsupported
    return _string("NoneType" if value.kind == "none" else value.kind)


def _unsupported_pair(g, left, right, operator, node):
    from .native import _string
    message = (f"TypeError: '{ORDERING[type(operator)]}' not supported between "
               "instances of '{}' and '{}'")
    error = f'Err::<bool,String>(format!({_string(message)},{_type_name(left)},{_type_name(right)}))'
    return g.at(error, node)


def ordering(g, left, right, operator, node):
    """Order captured values; retain Python errors and partial float order.

    This function never evaluates an AST expression. Callers capture operands
    in their original order, so recursive enum matches and tuple fields cannot
    replay user functions or consume later chained-comparison operands.
    """
    from .native import _Expression, _Unsupported
    from .native_unions import project, union_kind
    if type(operator) not in ORDERING:
        raise _Unsupported("the selected ordering adapter only handles '<', '<=', '>' and '>='; no adapter for this requested comparison was selected",node=node,operation=f"comparison {type(operator).__name__!r}",types=(("left",left.kind),("right",right.kind)),proof="comparison-operator adapter selection")
    if not immutable(left.kind) or not immutable(right.kind):
        raise _Unsupported("this native ordering adapter handles recursively immutable values; mutable-container/alternative ordering and its alias-preserving Python sequence semantics are not implemented",node=node,operation=f"comparison {ORDERING[type(operator)]!r}",types=(("left",left.kind),("right",right.kind)),proof="native mutable-sequence comparison semantics")
    if union_kind(left.kind) or union_kind(right.kind):
        return project(left.kind, left.code, lambda a, x: project(right.kind, right.code,
            lambda b, y: ordering(g, _Expression(x, a, owned=False),
                                  _Expression(y, b, owned=False), operator, node)))

    if isinstance(left.kind,TupleSequenceType)or isinstance(right.kind,TupleSequenceType):
        from .native_tuple_sequences import _ordering
        return _ordering(g,left,right,operator,node)
    symbol = ORDERING[type(operator)]
    if isinstance(left.kind, TupleType) or isinstance(right.kind, TupleType):
        from .native_tuples import _scalar, tuple_compare
        # Tuple equality includes identity shortcuts. The common tuple proof
        # deliberately excludes float payloads, including NaN identity cases.
        for value in (left, right):
            if isinstance(value.kind, TupleType) and not _scalar(value.kind):
                raise _Unsupported("tuple element comparison needs Python identity-aware equality shortcuts, including floating NaN and custom/mutable payload semantics; that element comparator is not implemented for this tuple",node=node,operation=f"tuple comparison {symbol!r}",types=(("left",left.kind),("right",right.kind)),proof="identity-aware tuple element equality and ordering")
        if isinstance(left.kind, TupleType) and isinstance(right.kind, TupleType):
            return tuple_compare(g, left, right, operator, node)
        return _unsupported_pair(g, left, right, operator, node)
    if left.kind in _INTEGERS and right.kind in _INTEGERS:
        return f"({g.number(left)}){symbol}({g.number(right)})"
    if left.kind == right.kind and left.kind in {"str", "bytes", "float"}:
        return f"({left.code}){symbol}({right.code})"
    if (left.kind == "float" and right.kind in _INTEGERS
            or right.kind == "float" and left.kind in _INTEGERS):
        if not g.bits:
            # BigInt/float interoperation still needs a shared exact proof.
            raise _Unsupported("exact arbitrary-precision-integer/binary64 comparison is not implemented on the BigInt path; converting the integer to float would lose ordering precision",node=node,operation=f"integer/float comparison {symbol!r}",types=(("left",left.kind),("right",right.kind)),proof="exact BigInt/float ordering and NaN behavior")
        g.has_extended_scalars = True
        integer = g.number(right if left.kind == "float" else left)
        floating = left.code if left.kind == "float" else right.code
        order = f"native_integer_float_compare({integer},{floating})"
        if left.kind == "float":
            order += ".map(std::cmp::Ordering::reverse)"
        variants = {ast.Lt: "Less", ast.LtE: "Less | std::cmp::Ordering::Equal",
                    ast.Gt: "Greater", ast.GtE: "Greater | std::cmp::Ordering::Equal"}
        return f"matches!({order},Some(std::cmp::Ordering::{variants[type(operator)]}))"
    return _unsupported_pair(g, left, right, operator, node)
