"""Captured ASCII str/bytes case conversion with the builtin call protocol."""
import ast

from .native_types import alternatives

NAMES=frozenset({'upper','lower'})


def requires_frames(unit,analysis):
    from .native_constraints import MethodValue
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    return any(isinstance(identity,MethodValue)and identity.name in NAMES
        and builtin_text_receiver_kinds(unit,scope,nodes.get(ordinal),identity)
        for scope in analysis.scopes.values()for ordinal,fact in scope.calls.items()
        for identity in fact.identity.alternatives)


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import Cell,shape
    if node.func.attr not in NAMES:return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(kind in {'str','bytes'}for kind in kinds):return None
    if not hasattr(model,'ascii_case_sites'):model.ascii_case_sites={}
    model.ascii_case_sites[(plan.index,id(node))]=node.func.attr
    result=model.cell(plan,node)
    for kind in kinds:model.contribute(result,Cell(kind),node)
    return result


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_classes import Expression,ClassUnsupported
    from .native_class_builtins import _error
    from .native import _string
    from .native_unions import project,union_kind
    name=getattr(emitter.model,'ascii_case_sites',{}).get((emitter.plan.index,id(node)))
    if name is None:return None
    def branch(kind,text):
        if keywords:
            message=f'TypeError: {kind}.{name}() takes no keyword arguments'
            return _error(emitter,node,wanted,_string(message)+'.to_owned()').code
        if arguments:
            message=f'TypeError: {kind}.{name}() takes no arguments ({len(arguments)} given)'
            return _error(emitter,node,wanted,_string(message)+'.to_owned()').code
        if kind=='str'and emitter.model.string_mode!='ascii':
            raise ClassUnsupported(node,f'str.{name}() in Unicode mode requires Python 3.14 case-mapping data and context-sensitive casing; this native adapter currently implements ASCII strings and bytes',proof='Python Unicode case mapping and conditional casing')
        converted=f'({text}).to_ascii_{name}case()'
        if kind=='str':converted='NativeText::from('+converted+')'
        return emitter.coerce(Expression(converted,kind),wanted,node)
    code=project(receiver.kind,receiver.code,branch)if union_kind(receiver.kind)else branch(receiver.kind,receiver.code)
    return Expression(code,wanted)
