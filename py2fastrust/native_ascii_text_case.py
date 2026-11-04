"""Captured ASCII str/bytes case conversion with the builtin call protocol."""
import ast

from .native_types import alternatives

NAMES=frozenset({'upper','lower'})
TEXT=frozenset({'str','bytes'})
SCALARS=frozenset({'int','bool','int_bool','float','none'})


def requires_frames(unit,analysis):
    from .native_constraints import MethodValue
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for scope in analysis.scopes.values():
        for ordinal,fact in scope.calls.items():
            node=nodes.get(ordinal)
            for identity in fact.identity.alternatives:
                if not isinstance(identity,MethodValue)or identity.name not in NAMES:continue
                kinds=builtin_text_receiver_kinds(unit,scope,node,identity,allowed=TEXT|SCALARS)
                if not kinds or not kinds&TEXT:continue
                if kinds<=TEXT:return True
                # Select before emission, including unsupported signatures
                # whose typed validation explains the missing lookup step.
                # A stored method needs a separate descriptor adapter.
                if (isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)
                        and identity.site==unit.ordinal(node.func)):return True
    return False


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import Cell,shape,ClassUnsupported
    if node.func.attr not in NAMES:return None
    kinds=alternatives(shape(receiver))
    if not kinds or not any(kind in TEXT for kind in kinds)or not all(kind in TEXT|SCALARS for kind in kinds):return None
    if any(kind in SCALARS for kind in kinds)and(node.args or node.keywords):
        raise ClassUnsupported(node,f'mixed builtin receivers for {node.func.attr}() with explicit arguments require attribute lookup before argument effects; this native adapter currently supports zero-argument mixed builtin calls',proof='pre-argument lookup for mixed builtin text methods')
    if not hasattr(model,'ascii_case_sites'):model.ascii_case_sites={}
    model.ascii_case_sites[(plan.index,id(node))]=node.func.attr
    result=model.cell(plan,node)
    for kind in kinds:
        if kind in TEXT:model.contribute(result,Cell(kind),node)
    return result


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_classes import Expression,ClassUnsupported
    from .native_class_builtins import _error,_type_name
    from .native import _string
    from .native_unions import project,union_kind
    name=getattr(emitter.model,'ascii_case_sites',{}).get((emitter.plan.index,id(node)))
    if name is None:return None
    def branch(kind,text):
        if kind in SCALARS:
            message=_string("AttributeError: '{}' object has no attribute '"+name+"'")
            return _error(emitter,node,wanted,'format!('+message+','+_type_name(emitter,Expression(text,kind),node)+')').code
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
