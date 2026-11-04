"""Forward an exact synchronous constructor result at its source return site."""
import ast
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class Request:
    node: object
    kind: object
    code: str|None=None


@contextmanager
def capture(emitter,node):
    from .native_class_calls import synchronous
    from .native_classes import shape
    previous=getattr(emitter,'tail_constructor_request',None)
    request=None
    if (isinstance(node,ast.Call)and synchronous(emitter.model,emitter.plan)
            and getattr(emitter,'iterator_callback_context',None)is None):
        kind=emitter.kind(node)
        if kind==shape(emitter.plan.result):request=Request(node,kind)
    emitter.tail_constructor_request=request
    try:yield request
    finally:emitter.tail_constructor_request=previous


def register(emitter,node,constructor,callee,invocation,setup,context):
    from .native_classes import InstanceType
    from .native_class_calls import call,synchronous
    request=getattr(emitter,'tail_constructor_request',None)
    if (request is None or request.node is not node
            or request.kind!=InstanceType(emitter.model.class_key(constructor))
            or not synchronous(emitter.model,callee)
            or getattr(emitter,'iterator_callback_context',None)is not None):return
    result=call(emitter,invocation,callee,node,propagate=False)
    if result is not None:request.code='{'+ '\n'.join(setup)+context+result+'}'


def wrap(emitter,node,before):
    request=getattr(emitter,'tail_constructor_request',None)
    if request is not None and request.node is node and request.code is not None:
        request.code='{'+before+request.code+'}'
