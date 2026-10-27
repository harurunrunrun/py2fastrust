"""Backend factories for normalized producer operations."""

from .native import _Expression, _Unsupported
from .native_stream_plans import Normalizer, ProducerKind, ProducerPlan
from .call_semantics import CallBindingError
from dataclasses import dataclass


@dataclass(frozen=True)
class RangeCapture:
    lower:str
    upper:str
    step:str
    call_site:int|None

@dataclass(frozen=True)
class RangeCode:
    setup:str
    iterator:str
    arguments:object
    captures:RangeCapture
    def __iter__(self):
        yield self.setup;yield self.iterator;yield self.arguments


def integer_range(g,node,environment):
    try:
        plan=node if isinstance(node,ProducerPlan) else Normalizer(g,environment).producer(node)
    except CallBindingError as error:
        raise _Unsupported from error
    if plan.kind is not ProducerKind.RANGE:
        raise _Unsupported
    provided={}
    for operand in plan.binding.explicit_order:
        value=g.expression(operand.expression,environment)
        if value.kind not in {"int","bool","int_bool"}:
            raise _Unsupported
        provided[operand.parameter]=value
    arguments=[provided.get("start",_Expression(g.literal(0),"int",0)),provided["stop"],
               provided.get("step",_Expression(g.literal(1),"int",1))]
    names=[g.temporary()for _ in arguments]
    setup="\n".join(f"let {name}={g.number(value)};"for name,value in zip(names,arguments))
    if g.bits and arguments[2].constant==1:
        iterator=f"({names[0]}..{names[1]})"
    elif g.bits and arguments[2].constant==-1:
        iterator=f"({names[1]}..{names[0]}).rev().map(|native_descending_value:NativeInt|native_descending_value.wrapping_add(1))"
    else:
        iterator=g.at(f"NativeRange::new({','.join(names)})",plan.node)
    unit=getattr(g,"source_unit",None)
    try:call_site=unit.ordinal(plan.node)if unit is not None else None
    except KeyError:call_site=None
    return RangeCode(setup,iterator,arguments,RangeCapture(*names,call_site))
