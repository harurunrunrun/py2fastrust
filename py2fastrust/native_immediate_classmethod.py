"""Keep an immediately invoked canonical classmethod payload on the stack."""
import ast
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class Request:
    node: object
    target: object
    used: bool=False
    direct_definition: int|None=None
    direct_used: bool=False
    module: bool=True


def candidate(emitter,node):
    if not isinstance(node,ast.Attribute):return None
    from .native_aot_callables import AotFunctionType
    from .native_class_descriptors import ClassMethodTarget
    from .native_classes import InstanceType
    from .native_module_linking import ClassReferenceType
    kind=emitter.kind(node)
    if not isinstance(kind,AotFunctionType)or len(kind.targets)!=1:return None
    target=kind.targets[0]
    if not isinstance(target,ClassMethodTarget):return None
    registry=getattr(emitter.model,'class_namespaces',None)
    if registry is None:return None
    key=(emitter.plan.index,id(node))
    records=registry.attribute_reads.get(key)
    if records is None or len(records)!=1 or registry.instance_reads.get(key,False):return None
    member=records[0]
    if member.descriptor!='classmethod'or member.plan is None:return None
    if emitter.model.callable_cells.definition(member.plan)!=target.definition:return None
    receiver=emitter.kind(node.value)
    if not isinstance(receiver,(InstanceType,ClassReferenceType)):return None
    if isinstance(receiver,ClassReferenceType)and receiver.definition!=member.owner.index:return None
    if isinstance(receiver,InstanceType)and receiver.name!=emitter.model.class_key(member.owner):return None
    request=Request(node,target)
    # Only a captured exact class reference can use the existing immutable
    # direct-definition proof. Instance binding retains its ordinary adapter.
    from .native_class_calls import synchronous
    if isinstance(receiver,ClassReferenceType)and synchronous(emitter.model,member.plan):
        from .native_immutable_class_functions import prepared_definition
        stored=dict(emitter.model.namespace.fields())[member.key]
        number=prepared_definition(registry,member,stored)
        if number==target.definition:request.direct_definition=number
    return request


@contextmanager
def capture_callee(emitter,node):
    previous=getattr(emitter,'immediate_classmethod_request',None)
    request=candidate(emitter,node)
    emitter.immediate_classmethod_request=request
    try:yield request
    finally:emitter.immediate_classmethod_request=previous


def capture_operand(emitter,node,request):
    """Capture only the approved effects of a private class receiver."""
    if request is None or request.direct_definition is None:return None
    from .native_operand_demands import capture_access
    captured=capture_access(emitter,node,request)
    if captured is None:return None
    request.used=request.direct_used=True
    request.module=False
    return captured


def stack_payload(emitter,node,target,fields):
    request=getattr(emitter,'immediate_classmethod_request',None)
    if request is None or request.node is not node or request.target!=target:return None
    request.used=True
    return 'ClassBoundMethod'+str(target.definition)+'{'+fields+'}'


def direct_payload(emitter,node,reference,member):
    request=getattr(emitter,'immediate_classmethod_request',None)
    if (request is None or request.node is not node or request.direct_definition is None
            or request.target.definition!=request.direct_definition
            or request.target.class_definition!=member.owner.index):return None
    from .native_classes import Expression
    from .native_aot_callables import AotFunctionType
    receiver,module=emitter.fresh(),emitter.fresh()
    request.used=request.direct_used=True
    from .native_call_context_effects import incoming_module
    request.module=incoming_module(emitter.model,member.plan)
    # The outer emitter already captured this class exactly once. Hold both
    # receiver and actual defining generation before any explicit argument.
    code=('{let '+receiver+'='+reference.code+';'
          +('let '+module+'='+receiver+'.module.clone();('+receiver+','+module+')'
            if request.module else receiver)+'}')
    return Expression(code,AotFunctionType.from_targets((request.target,)))


def invoke(emitter,node,request,site,callee,positional,keywords,wanted):
    from .native import _Expression,_string
    def error(message):
        return emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({_string(message)}.to_owned())',node)
    if request.direct_used:
        provider=emitter.model.callable_cells
        if request.target in site.errors:return _Expression(error(site.errors[request.target]),wanted)
        from .native_aot_callables import AotFunctionType,CallSite,emit_definition_body
        from .native_operand_demands import ClassOperand
        if isinstance(callee,ClassOperand):
            nested=CallSite(provider.model.cell_for_kind(AotFunctionType((request.direct_definition,))),site.result)
            code=emit_definition_body(emitter,node,nested,request.direct_definition,
                [callee]+positional,keywords,wanted,error)
            context=provider.call_context_setup(emitter,provider.plans[request.direct_definition])
            return _Expression('{'+context+code+'}',wanted)
        receiver=_Expression('class_selected_method.0'if request.module else'class_selected_method',request.target._native_receiver_kind)
        nested=CallSite(provider.model.cell_for_kind(AotFunctionType((request.direct_definition,))),site.result)
        code=emit_definition_body(emitter,node,nested,request.direct_definition,
            [receiver]+positional,keywords,wanted,error)
        context=provider.call_context_setup(emitter,provider.plans[request.direct_definition])
        return _Expression('{let class_selected_method='+callee.code+';'
            +('let class_defining_module=class_selected_method.1;'if request.module else'')
            +context+code+'}',wanted)
    code=emitter.model.callable_cells.bound_methods.emit(
        emitter,node,request.target,site,positional,keywords,wanted,error)
    return _Expression('{let class_selected_method='+callee.code+';'+code+'}',wanted)
