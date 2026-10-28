"""Typed positional extrema consume canonical calls and ordered argument values."""
import ast

from .native import _Expression, _Unsupported
from .native_stream_plans import ConsumerKind
from .native_types import TupleType,TupleSequenceType, UnionType, NullableType


def comparison(g,left,right,maximum,node):
    operator=ast.Gt() if maximum else ast.Lt()
    if isinstance(left.kind,(TupleType,TupleSequenceType,UnionType,NullableType)) or left.kind=="none":
        from .native_tuples import tuple_compare,_scalar
        if not _scalar(left.kind):raise _Unsupported
        return tuple_compare(g,left,right,operator,node)
    symbol=">" if maximum else "<"
    if left.kind in {"str","bytes","float"}:
        return f"({left.code}){symbol}({right.code})"
    return f"({g.number(left)}){symbol}({g.number(right)})"


def positional(g,plan,environment):
    # All positional arguments are evaluated before any comparison. Keep the
    # first candidate on equality, including bool/int ties and unordered NaNs.
    for operand in plan.binding.explicit_order:
        if operand.parameter=="key":
            value=operand.expression
            if not isinstance(value,ast.Constant) or value.value is not None:raise _Unsupported
    values=[g.expression(node,environment)for node in plan.values]
    kind=g.scalar_kind(values)
    names=[g.temporary()for _ in values]
    setup=[f"let {name}={g.coerce(value,kind)};"for name,value in zip(names,values)]
    best=g.temporary()
    setup.append(f"let mut {best}={names[0]};")
    maximum=plan.kind is ConsumerKind.MAX_ARGUMENTS
    for name in names[1:]:
        test=comparison(g,_Expression(name,kind),_Expression(best,kind),maximum,plan.node)
        setup.append(f"if {test} {{{best}={name};}}")
    constant=None
    if all(value.constant is not None for value in values):
        constant=(max if maximum else min)(value.constant for value in values)
    return _Expression("{"+"\n".join(setup)+f"\n{best}"+"}",kind,constant)
