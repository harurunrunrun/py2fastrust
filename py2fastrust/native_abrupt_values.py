"""Eager value construction cannot succeed after an uninhabited operand.

EMPTY records an expression with no normal result, not a Python None value.
Original expressions still run in order and raise their original exceptions.
"""
import ast
from .native_types import EMPTY,EmptyType


def empty(value):
    from .native_classes import shape
    return isinstance(shape(value),EmptyType)


def mark(model):
    model.native_abrupt_values_used=True


def bottom(model,plan,node):
    from .native_classes import Cell
    cells=getattr(model,'abrupt_value_cells',None)
    if cells is None:cells=model.abrupt_value_cells={}
    value=cells.setdefault((plan.index,id(node)),Cell(EMPTY))
    mark(model)
    return model.remember(plan,node,value)


def analyze_tuple(model,plan,node,environment):
    prefixes=getattr(model,'abrupt_tuple_prefixes',None)
    if prefixes is None:prefixes=model.abrupt_tuple_prefixes={}
    key=plan.index,id(node)
    prefixes.pop(key,None)
    values=[]
    for index,child in enumerate(node.elts):
        value=model.expression(plan,child,environment);values.append(value)
        if empty(value):
            prefixes[key]=index+1;mark(model)
            return bottom(model,plan,node)
    return model.cell(plan,node,'tuple',tuple(values))


def emit_tuple(emitter,node,wanted):
    from .native_classes import Expression
    count=getattr(emitter.model,'abrupt_tuple_prefixes',{}).get((emitter.plan.index,id(node)))
    if count is None:return None
    setup=''
    for child in node.elts[:count]:
        before,value=emitter.capture(emitter.expression(child));setup+=before
    return Expression('{'+setup+emitter.coerce(value,wanted,node)+'}',wanted)


def emit_statement(emitter,node):
    if not isinstance(node,(ast.Assign,ast.AnnAssign))or node.value is None:return None
    value=emitter.model.records.get((emitter.plan.index,id(node.value)))
    if value is None or not empty(value):return None
    return emitter.expression(node.value).code+';'


def subscript_operand(model,plan,node,value,position):
    sites=getattr(model,'abrupt_subscript_operands',None)
    if sites is None:sites=model.abrupt_subscript_operands={}
    key=plan.index,id(node)
    if position==1:sites.pop(key,None)
    if not empty(value):return None
    sites[key]=position;mark(model)
    return bottom(model,plan,node)


def emit_subscript(emitter,node,wanted):
    from .native_classes import Expression
    count=getattr(emitter.model,'abrupt_subscript_operands',{}).get((emitter.plan.index,id(node)))
    if count is None:return None
    setup,value=emitter.capture(emitter.expression(node.value))
    if count==2:
        more,value=emitter.capture(emitter.expression(node.slice));setup+=more
    return Expression('{'+setup+emitter.coerce(value,wanted,node)+'}',wanted)
