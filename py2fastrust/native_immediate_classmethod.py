"""Keep an immediately invoked canonical classmethod payload on the stack."""
import ast
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class Request:
    node: object
    target: object
    used: bool=False


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
    return Request(node,target)


@contextmanager
def capture_callee(emitter,node):
    previous=getattr(emitter,'immediate_classmethod_request',None)
    request=candidate(emitter,node)
    emitter.immediate_classmethod_request=request
    try:yield request
    finally:emitter.immediate_classmethod_request=previous


def stack_payload(emitter,node,target,fields):
    request=getattr(emitter,'immediate_classmethod_request',None)
    if request is None or request.node is not node or request.target!=target:return None
    request.used=True
    return 'ClassBoundMethod'+str(target.definition)+'{'+fields+'}'


def invoke(emitter,node,request,site,callee,positional,keywords,wanted):
    from .native import _Expression,_string
    def error(message):
        return emitter.at(f'Err::<{emitter.rust_type(wanted)},String>({_string(message)}.to_owned())',node)
    code=emitter.model.callable_cells.bound_methods.emit(
        emitter,node,request.target,site,positional,keywords,wanted,error)
    return _Expression('{let class_selected_method='+callee.code+';'+code+'}',wanted)
